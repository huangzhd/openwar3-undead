"""Portable placement, failure isolation, preparation and launch ownership."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import training_launcher as launch


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.game=Path(self.temp.name)/'魔兽 游戏';self.root=self.game/'dayuan-training';self.root.mkdir(parents=True)
        for name in ('War3.exe','Game.dll','war3.mpq','War3x.mpq'):(self.game/name).write_bytes(b'fixture')
        self.upstream=self.root/'vendor'/launch.UPSTREAM_NAME

    def test_parent_path_with_spaces_and_chinese_needs_no_saved_machine_path(self):
        self.assertEqual(launch.locate_game(self.root,lambda p:launch.GAME_VERSION),self.game)

    def test_wrong_placement_and_127b_are_rejected(self):
        misplaced=self.root/'another-folder';misplaced.mkdir()
        with self.assertRaisesRegex(ValueError,'文件夹位置'):launch.locate_game(misplaced)
        with self.assertRaisesRegex(ValueError,'1.27b'):launch.locate_game(self.root,lambda p:'1.27.1.7085')

    def test_incomplete_game_is_rejected(self):
        (self.game/'War3x.mpq').unlink()
        with self.assertRaisesRegex(ValueError,'游戏文件不完整'):launch.locate_game(self.root,lambda p:launch.GAME_VERSION)

    def test_config_is_local_relocatable_and_drops_old_machine_overrides(self):
        path=self.upstream/'openwar3.json';path.parent.mkdir(parents=True)
        path.write_text('{"maps_dir":"old-machine", "python":"old-python"}')
        launch.configure(self.root,self.game,self.root/'python/pythonw.exe')
        value=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(value['game_dir'],str(self.game));self.assertEqual(value['maps_dir'],'')
        self.assertEqual(value['undead_machine_profile'],'portable-training')

    def test_damaged_runtime_does_not_write_bin(self):
        (self.upstream/'prebuilt').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'运行组件'):launch.install_runtime(self.upstream)
        self.assertFalse((self.upstream/'bin').exists())

    def test_live_game_stops_preparation_before_configuration_changes(self):
        with patch.object(launch,'locate_game',return_value=self.game),patch.object(launch,'active_games',return_value=['War3.exe']):
            with self.assertRaisesRegex(RuntimeError,'先关闭'):launch.prepare(self.root,lambda _:None)
        self.assertFalse((self.upstream/'openwar3.json').exists())

    def test_missing_or_corrupt_table_regenerates_and_relocation_invalidates_cache(self):
        signature=launch.game_signature(self.game);folder=self.upstream/'data/game';folder.mkdir(parents=True)
        launch.atomic_json(folder/'dayuan-prepared.json',signature)
        for name in launch.TABLES:(folder/name).write_text('table')
        for name in launch.GENERATED:(folder/name).write_text('{"fixture":1}')
        self.assertTrue(launch.data_ready(self.upstream,signature))
        (folder/'items.json').write_text('{}');self.assertFalse(launch.data_ready(self.upstream,signature))
        (folder/'items.json').write_text('{"fixture":1}')
        self.assertFalse(launch.data_ready(self.upstream,dict(signature,game_dir='another-path')))

    def test_generator_failure_stops_before_readiness_marker_or_panel(self):
        with patch.object(launch,'locate_game',return_value=self.game),patch.object(launch,'active_games',return_value=[]),\
             patch.object(launch,'install_runtime'),patch.object(launch,'run_tool',side_effect=RuntimeError('generator failed')):
            with self.assertRaisesRegex(RuntimeError,'generator failed'):launch.prepare(self.root,lambda _:None)
        self.assertFalse((self.upstream/'data/game/dayuan-prepared.json').exists())

    def test_old_cache_and_generated_files_cannot_hide_failed_regeneration(self):
        signature=launch.game_signature(self.game);signature.pop('extractor')
        folder=self.upstream/'data/game';folder.mkdir(parents=True)
        launch.atomic_json(folder/'dayuan-prepared.json',signature)
        for name in launch.TABLES:(folder/name).write_text('old table')
        for name in launch.GENERATED:(folder/name).write_text('{"old":1}')
        self.assertFalse(launch.data_ready(self.upstream,launch.game_signature(self.game)))
        with patch.object(launch,'locate_game',return_value=self.game),patch.object(launch,'active_games',return_value=[]),\
             patch.object(launch,'install_runtime'),patch.object(launch,'run_tool') as run:
            with self.assertRaisesRegex(RuntimeError,'游戏数据不完整'):launch.prepare(self.root,lambda _:None)
        self.assertEqual(run.call_args_list[0].args[0][0],self.root/'portable_game_data.py')
        self.assertFalse((folder/'dayuan-prepared.json').exists())
        self.assertFalse(any((folder/name).exists() for name in launch.GENERATED))

    @unittest.skipUnless(__import__('sys').platform=='win32','Windows file lock')
    def test_duplicate_start_is_blocked_and_lock_recovers_after_exit(self):
        with launch.LauncherLock(self.root):
            with self.assertRaisesRegex(RuntimeError,'已打开'):
                with launch.LauncherLock(self.root):pass
        with launch.LauncherLock(self.root):pass


if __name__=='__main__':unittest.main()
