import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import practice_video as video
import machine_start


class PracticeVideoTests(unittest.TestCase):
    @contextlib.contextmanager
    def registry(self,mode=None):
        with tempfile.TemporaryDirectory() as tmp:
            values=dict(reswidth=800,resheight=600,colordepth=16,texcolordepth=16,refreshrate=75,
                        gamma=30,modeldetail=1)
            writes=[]
            @contextlib.contextmanager
            def key(*args,**kwargs):yield object()
            def get(key,name):
                if name not in values:raise FileNotFoundError(name)
                return values[name],video.winreg.REG_DWORD
            def put(key,name,reserved,kind,value):
                writes.append((name,value));values[name]=value
            backup=Path(tmp)/'before.json'
            with patch.object(video,'BACKUP',backup), \
                 patch.object(video,'current_display',return_value=mode or dict(width=2560,height=1440,refresh_hz=59,color_depth=32)), \
                 patch.object(machine_start,'active_processes',return_value=[]), \
                 patch.object(video.winreg,'CreateKeyEx',side_effect=key), \
                 patch.object(video.winreg,'OpenKey',side_effect=key), \
                 patch.object(video.winreg,'QueryValueEx',side_effect=get), \
                 patch.object(video.winreg,'SetValueEx',side_effect=put), \
                 patch.object(video.winreg,'FlushKey'):
                yield values,writes,backup

    def test_native_display_and_32_bit_settings_are_written_read_back_without_touching_other_preferences(self):
        with self.registry() as (values,writes,backup):
            result=video.configure_video()
            self.assertEqual({name:values[name] for name in video.NAMES},
                             dict(reswidth=2560,resheight=1440,colordepth=32,texcolordepth=32,refreshrate=59))
            self.assertEqual(result['registry'],{name:values[name] for name in video.NAMES})
            self.assertEqual((values['gamma'],values['modeldetail']),(30,1))
            self.assertEqual({name for name,value in writes},set(video.NAMES))
            original=json.loads(backup.read_text())['values']
            self.assertEqual((original['reswidth']['value'],original['resheight']['value'],
                              original['colordepth']['value']),(800,600,16))

    def test_later_display_changes_do_not_overwrite_original_backup(self):
        with self.registry() as (values,writes,backup):
            video.configure_video();original=backup.read_bytes()
            with patch.object(video,'current_display',return_value=dict(width=1920,height=1080,refresh_hz=60,color_depth=32)):
                video.configure_video()
            self.assertEqual((values['reswidth'],values['resheight'],values['refreshrate']),(1920,1080,60))
            self.assertEqual(backup.read_bytes(),original)

    def test_unknown_refresh_preserves_existing_refresh_and_records_absent_original_value(self):
        with self.registry(dict(width=1920,height=1080,refresh_hz=1,color_depth=32)) as (values,writes,backup):
            del values['texcolordepth']
            video.configure_video()
            self.assertEqual(values['refreshrate'],75)
            self.assertNotIn('refreshrate',[name for name,value in writes])
            self.assertEqual(json.loads(backup.read_text())['values']['texcolordepth'],dict(exists=False))

    def test_active_game_refuses_before_registry_or_backup_changes(self):
        with self.registry() as (values,writes,backup):
            before=dict(values)
            with patch.object(machine_start,'active_processes',return_value=[dict(pid=5,name='War3.exe')]):
                with self.assertRaisesRegex(RuntimeError,'退出当前游戏'):video.configure_video()
            self.assertEqual(values,before)
            self.assertEqual(writes,[])
            self.assertFalse(backup.exists())

    def test_readback_mismatch_never_reports_success(self):
        with self.registry() as (values,writes,backup):
            with patch.object(video.winreg,'SetValueEx',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'回读校验'):video.configure_video()
            self.assertEqual((values['reswidth'],values['resheight']),(800,600))
            self.assertTrue(backup.exists())


if __name__=='__main__':unittest.main()
