import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootstrap import UPSTREAM
from learning.evidence import audit_sources, freeze_contract


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'artifacts' / 'run'
        (self.out / 'source').mkdir(parents=True)
        self.code = b'print("rule")\n'
        self.manifest = {'bot.py': hashlib.sha256(self.code).hexdigest()}
        (self.root / 'bot.py').write_bytes(self.code)
        (self.out / 'source' / 'bot.py').write_bytes(self.code)
        self.session = self.root / 'artifacts' / 'session.json'
        self.session.write_text(json.dumps(dict(closed=True, processes=[])), encoding='utf-8')
        self.upstream = self.root / 'vendor' / UPSTREAM.name
        for name in ('sdk/python/game.py', 'sdk/python/openwar3/jass_signatures.json',
                     'data/game/units.json', 'data/game/skills.json', 'data/game/DestructableData.slk',
                     'runtime/farm.py', 'bin/render_hook.dll',
                     'bin/war3_launch.exe', 'bin/war3_ui_command.exe'):
            path = self.upstream / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.settings = dict(map_sha256='map-a', observer_player=0, controlled_player=1,
            opponent_player=2, speed=400, opponent_fairness='native_KFAI_unverified')
        self.processes = patch('machine_start.active_processes', return_value=[])
        self.active = self.processes.start()
        self.addCleanup(self.processes.stop)

    def freeze(self):
        return freeze_contract(self.root, self.out, self.manifest, self.settings,
            rules_version='rule-test', opponent='kfai-human', pid=123, epoch=456)

    def test_contract_freezes_bytes_and_preserves_run_binding_without_approval(self):
        report = self.freeze()
        dep = 'vendor/' + UPSTREAM.name + '/sdk/python/game.py'
        self.assertEqual(report['dependencies'][dep], hashlib.sha256(b'sdk/python/game.py').hexdigest())
        self.assertEqual(report['binding'], dict(pid=123, epoch=456))
        self.assertEqual(report['map_sha256'], self.settings['map_sha256'])
        self.assertFalse(report['training_actor_approved'])
        (self.upstream / 'sdk/python/game.py').write_bytes(b'changed')
        audit = audit_sources(self.root, self.out, self.manifest)
        self.assertIn(dep, audit['dependency_mismatches'])
        self.assertFalse(audit['source_unchanged'])
        with self.assertRaises(FileExistsError):self.freeze()

    def test_intact_sources_and_closed_session_can_be_audited_but_never_approved(self):
        self.freeze()
        report = audit_sources(self.root, self.out, self.manifest)
        self.assertTrue(report['source_unchanged'])
        self.assertTrue(report['session_closed'])
        self.assertEqual(report['active_processes'], [])
        self.assertEqual(report['errors'], [])
        self.assertFalse(report['training_actor_approved'])
        saved = (self.out / 'source-audit.json').read_bytes()
        with self.assertRaises(FileExistsError):audit_sources(self.root, self.out, self.manifest)
        self.assertEqual(saved, (self.out / 'source-audit.json').read_bytes())

    def test_signature_and_game_data_edits_fail_the_frozen_dependency_audit(self):
        report = self.freeze()
        names = ('sdk/python/openwar3/jass_signatures.json', 'data/game/units.json')
        for name in names:
            key = 'vendor/' + UPSTREAM.name + '/' + name
            self.assertEqual(report['dependencies'][key], hashlib.sha256(name.encode()).hexdigest())
            (self.upstream / name).write_text('{"changed":true}', encoding='utf-8')
        audit = audit_sources(self.root, self.out, self.manifest)
        self.assertFalse(audit['source_unchanged'])
        self.assertEqual(set(audit['dependency_mismatches']),
                         {'vendor/' + UPSTREAM.name + '/' + name for name in names})

    def test_missing_signature_is_not_hidden_by_other_sdk_json(self):
        (self.upstream / 'sdk/python/openwar3/jass_signatures.json').unlink()
        (self.upstream / 'sdk/python/openwar3/docs.json').write_text('{}', encoding='utf-8')
        report = self.freeze()
        self.assertIn('missing_sdk_data:jass_signatures.json', report['dependency_errors'])
        self.assertFalse(audit_sources(self.root, self.out, self.manifest)['source_unchanged'])

    def test_current_and_frozen_tampering_are_independent_failures(self):
        (self.root / 'bot.py').write_bytes(b'edited')
        (self.out / 'source' / 'bot.py').unlink()
        report = audit_sources(self.root, self.out, self.manifest)
        self.assertEqual(report['mismatches'], ['bot.py'])
        self.assertEqual(report['frozen_mismatches'], ['bot.py'])
        self.assertFalse(report['source_unchanged'])

    def test_traversal_absolute_and_windows_drive_paths_fail_closed(self):
        for name in ('../bot.py', '/bot.py', 'C:\\bot.py', 'C:bot.py', 'sub/../bot.py'):
            with self.subTest(name=name):
                folder = self.out / str(len(list(self.out.iterdir())))
                folder.mkdir()
                report = audit_sources(self.root, folder, {name: self.manifest['bot.py']})
                self.assertEqual(report['mismatches'], [name])
                self.assertEqual(report['frozen_mismatches'], [name])
                self.assertFalse(report['source_unchanged'])

    def test_missing_dependencies_and_unknown_cleanup_cannot_look_successful(self):
        (self.upstream / 'bin/war3_launch.exe').unlink()
        contract = self.freeze()
        self.assertIn('missing_runtime:war3_launch.exe', contract['dependency_errors'])
        self.session.write_text('invalid', encoding='utf-8')
        self.active.side_effect = PermissionError('process inspection failed')
        report = audit_sources(self.root, self.out, self.manifest)
        self.assertFalse(report['source_unchanged'])
        self.assertFalse(report['session_closed'])
        self.assertIsNone(report['active_processes'])
        self.assertEqual({e.get('check') for e in report['errors']}, {'session', 'active_processes'})

    def test_live_processes_and_nonempty_closed_session_are_preserved(self):
        live = [dict(pid=789, name='War3.exe')]
        self.active.return_value = live
        self.session.write_text(json.dumps(dict(closed=True, processes=live)), encoding='utf-8')
        report = audit_sources(self.root, self.out, self.manifest)
        self.assertFalse(report['session_closed'])
        self.assertEqual(report['active_processes'], live)

    def test_instance_audit_requires_own_cleanup_while_peer_can_stay_alive(self):
        from learning.instance import InstanceContext
        from session import Session
        context=InstanceContext(self.root,81,'a'*32)
        context.directory.mkdir(parents=True)
        context.record.write_text(json.dumps(dict(closed=True,processes=[])))
        self.session.write_text(json.dumps(dict(closed=False,processes=[dict(pid=999)])))
        self.active.return_value=[dict(pid=999,name='War3-82.exe')]
        report=audit_sources(self.root,self.out,self.manifest,instance_context=context)
        self.assertTrue(report['session_closed'])
        self.assertEqual(report['active_processes'],[])
        self.assertEqual(report['process_scope'],'owned_instance')
        second=self.out/'unclean';(second/'source').mkdir(parents=True)
        (second/'source'/'bot.py').write_bytes(self.code)
        row=dict(pid=888,created=1,name='War3-81.exe')
        context.record.write_text(json.dumps(dict(closed=False,processes=[row])))
        with patch.object(Session,'matches',return_value=True):
            report=audit_sources(self.root,second,self.manifest,instance_context=context)
        self.assertFalse(report['session_closed'])
        self.assertEqual(report['active_processes'],[row])
