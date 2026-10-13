"""Machine bindings must preserve shared catalogs and reject unsafe startup."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import machine_start
from undead import maps


class MachineStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / 'vendor'
        (self.upstream / 'bin').mkdir(parents=True)
        for name in ('render_hook.dll', 'war3_launch.exe', 'war3_ui_command.exe'):
            (self.upstream / 'bin' / name).write_bytes(b'runtime fixture')
        self.payloads = {'local': b'local package', 'upstream': b'upstream package'}
        self.roots = {}
        for machine, payload in self.payloads.items():
            directory = self.root / machine / 'Maps/dz/versus'
            directory.mkdir(parents=True)
            (directory / (machine + '.w3x')).write_bytes(payload)
            self.roots[machine] = directory.parents[2]
        digest = lambda machine: hashlib.sha256(self.payloads[machine]).hexdigest()
        self.catalog = {'NI': dict(alias='NI', file='upstream.w3x', map_sha256=digest('upstream'),
                                   camps=[{'id': 'ni-1', 'x': 5}], neutral_buildings=[{'code': 'ntav', 'x': 2048}])}
        self.profiles = {
            'upstream': dict(game_dir=str(self.roots['upstream']), maps={}),
            'local': dict(game_dir=str(self.roots['local']), maps={'NI': dict(file='local.w3x', map_sha256=digest('local'))}),
        }
        self.config_path = self.upstream / 'openwar3.json'
        self.original = dict(game_dir=str(self.roots['upstream']), python='old/python', default_map='custom.w3x', unrelated=7)
        self.config_path.write_text(json.dumps(self.original), encoding='utf-8')
        for target, name, value in [
            (maps, 'pool', lambda: self.catalog), (maps, 'profiles', lambda: self.profiles),
            (machine_start, 'pool', lambda: self.catalog), (machine_start, 'profiles', lambda: self.profiles),
            (maps, 'UPSTREAM', self.upstream), (machine_start, 'UPSTREAM', self.upstream),
            (machine_start, 'ROOT', self.root),
        ]:
            obj = patch.object(target, name, value)
            obj.start()
            self.addCleanup(obj.stop)
        obj = patch.object(machine_start, 'active_processes', return_value=[])
        self.active = obj.start()
        self.addCleanup(obj.stop)

    def test_two_packages_resolve_to_same_public_coordinates_without_editing_catalog(self):
        before = json.dumps(self.catalog)
        for machine in self.profiles:
            path, row = maps.resolve_map('NI', dict(game_dir=str(self.roots[machine]), undead_machine_profile=machine))
            self.assertEqual(path.read_bytes(), self.payloads[machine])
            self.assertEqual(row['map_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(row['neutral_buildings'], self.catalog['NI']['neutral_buildings'])
            self.assertEqual(row['camps'], self.catalog['NI']['camps'])
        self.assertEqual(json.dumps(self.catalog), before)

    def test_changed_package_is_rejected_before_any_config_write(self):
        path = self.roots['local'] / 'Maps/dz/versus/local.w3x'
        path.write_bytes(b'changed content with same name')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            machine_start.prepare('local')
        self.assertEqual(json.loads(self.config_path.read_text()), self.original)

    def test_catalog_lookup_supports_both_fingerprints_and_rejects_unknown_bytes(self):
        for machine in self.profiles:
            path = self.roots[machine] / ('Maps/dz/versus/' + machine + '.w3x')
            self.assertEqual(maps.catalog_for_path(path)['camps'], self.catalog['NI']['camps'])
        path.write_bytes(b'unknown map')
        self.assertIsNone(maps.catalog_for_path(path))

    def test_profile_is_inferred_only_from_matching_installation_or_explicit_selection(self):
        for machine in self.profiles:
            directory = str(self.roots[machine]).upper().replace('/', '\\')
            self.assertEqual(maps.profile_name(dict(game_dir=directory)), machine)
        with self.assertRaisesRegex(ValueError, 'Select this machine'):
            maps.profile_name(dict(game_dir='unknown/location'))
        with self.assertRaisesRegex(ValueError, 'Unknown machine'):
            maps.profile_name(dict(game_dir=str(self.roots['local']), undead_machine_profile='typo'))

    def test_prepare_saves_only_ignored_config_and_is_idempotent(self):
        report = machine_start.prepare('local')
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved['python'], sys.executable)
        self.assertEqual(saved['default_map'], 'custom.w3x')
        self.assertEqual(saved['unrelated'], 7)
        self.assertEqual(saved['undead_machine_profile'], 'local')
        backup = list((self.root / 'artifacts').glob('machine-config-before-*.json'))
        self.assertEqual(json.loads(backup[0].read_text()), self.original)
        self.assertEqual(Path(report['maps']['NI']['path']).read_bytes(), self.payloads['local'])
        before = self.config_path.read_bytes()
        self.assertFalse(machine_start.prepare('local')['config_changed'])
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(list((self.root / 'artifacts').glob('machine-config-before-*.json')), backup)

    def test_active_match_blocks_reconfigure_and_duplicate_launch_but_allows_unchanged_check(self):
        self.active.return_value = [dict(pid=123, name='War3-71.exe')]
        with self.assertRaisesRegex(RuntimeError, 'existing game'):
            machine_start.prepare('local')
        self.assertEqual(json.loads(self.config_path.read_text()), self.original)
        self.active.return_value = []
        machine_start.prepare('local')
        self.active.return_value = [dict(pid=123, name='War3-71.exe')]
        before = self.config_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'existing game'):
            machine_start.prepare('local', launching=True)
        self.assertEqual(machine_start.prepare('local')['active_processes'][0]['pid'], 123)
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_installation_override_is_saved_and_reused_without_changing_profile_defaults(self):
        moved = self.root / 'moved'
        self.roots['local'].rename(moved)
        first = machine_start.prepare('local', moved)
        second = machine_start.prepare('local')
        self.assertEqual(first['game_dir'], str(moved))
        self.assertEqual(second['maps'], first['maps'])
        self.assertFalse(second['config_changed'])
        self.assertNotEqual(self.profiles['local']['game_dir'], str(moved))

    def test_wrong_machine_or_missing_runtime_cannot_launch(self):
        (self.upstream / 'bin/war3_launch.exe').unlink()
        with patch.object(sys, 'argv', ['machine_start.py', '--machine', 'local', 'play', '--map', 'NI', '--enemy-race', '4']), patch.object(machine_start.subprocess, 'call') as launch:
            self.assertEqual(machine_start.main(), 1)
            launch.assert_not_called()
        self.assertEqual(json.loads(self.config_path.read_text()), self.original)

    def test_default_check_never_dispatches_play(self):
        with patch.object(sys, 'argv', ['machine_start.py', '--machine', 'local']), patch.object(machine_start.subprocess, 'call', return_value=0) as command:
            self.assertEqual(machine_start.main(), 0)
            self.assertEqual(command.call_args.args[0], [sys.executable, '-B', str(self.root / 'bot.py'), 'check'])
