import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import xml.etree.ElementTree as ET

import auto_load as a
import install_auto_takeover as installer
import persistent_auto_load as service


class PersistentAutoLoadTests(unittest.TestCase):
    def test_task_uses_interactive_current_user_and_only_project_entry(self):
        task=ET.fromstring(installer.task_xml('S-1-5-21-123'))
        ns={'t':installer.NS}
        self.assertEqual(task.find('.//t:LogonTrigger/t:UserId',ns).text,'S-1-5-21-123')
        self.assertEqual(task.find('.//t:Principal/t:LogonType',ns).text,'InteractiveToken')
        self.assertEqual(task.find('.//t:Principal/t:RunLevel',ns).text,'HighestAvailable')
        self.assertEqual(task.find('.//t:ExecutionTimeLimit',ns).text,'PT0S')
        self.assertEqual(task.find('.//t:MultipleInstancesPolicy',ns).text,'IgnoreNew')
        self.assertIn('persistent_auto_load.py',task.find('.//t:Exec/t:Arguments',ns).text)
        self.assertNotIn('Password',installer.task_xml('S-1-5-21-123'))

    def test_disable_persists_across_login_and_requests_graceful_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'config.json';stop=Path(directory)/'STOP'
            config.write_text(json.dumps(dict(enabled=True,enemy_race=1)))
            with patch.object(service,'CONFIG',config),patch.object(a,'STOP',stop):
                service.disable()
                self.assertFalse(service.configuration()['enabled'])
                self.assertTrue(stop.exists())

    def test_persistent_start_does_not_clear_a_stop_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stop=root/'STOP';stop.touch()
            with patch.object(a,'ROOT',root),patch.object(a,'STOP',stop),patch.object(a,'verified_runtime') as runtime:
                self.assertEqual(a.watch(persistent=True),{'result':'stopped'})
            runtime.assert_not_called();self.assertTrue(stop.exists())

    def test_waiting_for_old_watcher_can_be_stopped_without_stealing_lock(self):
        import msvcrt
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stop=root/'STOP';waiting=[]
            with patch.object(a,'ROOT',root),patch.object(a,'STOP',stop),patch.object(msvcrt,'locking',side_effect=OSError('busy')),patch.object(a.time,'sleep',side_effect=lambda _:stop.touch()),patch.object(a,'verified_runtime') as runtime:
                result=a.watch(persistent=True,on_lock_wait=lambda:waiting.append(True))
            self.assertEqual(result,{'result':'stopped'});self.assertEqual(waiting,[True])
            runtime.assert_not_called()

    def test_persistent_watcher_outlives_timeout_and_follows_next_game_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stop=root/'STOP';(root/'artifacts').mkdir()
            (root/'openwar3.json').write_text(json.dumps(dict(game_dir=str(root/'Game'))))
            for name in ('auto_load.py','native/RuntimeAttach.cs','attach_match.py','bridge_diagnostics.py','bot.py'):
                path=root/name;path.parent.mkdir(exist_ok=True);path.write_text('snapshot')
            rows={pid:dict(pid=pid,created=101+pid,name='War3.exe',exe=str(root/'Game/War3.exe')) for pid in (1,2)}
            parent=N(exe=lambda:str(a.PLATFORM_EXE),create_time=lambda:50)
            p1=N(pid=1,info={'name':'War3.exe'},parent=lambda:parent)
            p2=N(pid=2,info={'name':'War3.exe'},parent=lambda:parent)
            calls=[]
            def follow(row,*args,**kw):
                calls.append((row['pid'],kw['ready_timeout']))
                if row['pid']==1:raise RuntimeError('first game failed')
                stop.touch();return 'game_exited'
            with patch.object(a,'ROOT',root),patch.object(a,'UPSTREAM',root),patch.object(a,'STATE',root/'artifacts/state.json'),patch.object(a,'STOP',stop),patch.object(a,'verified_runtime',return_value=root/'dll'),patch.object(a,'build_helper',return_value=root/'helper'),patch.object(a,'identity',side_effect=lambda pid:rows[pid]),patch.object(a.psutil,'process_iter',side_effect=[[],[p1],[p1,p2]]),patch.object(a.time,'time',return_value=100),patch.object(a.time,'monotonic',side_effect=[0,5000,10000,15000,20000]),patch.object(a.time,'sleep'),patch.object(a,'follow_game',side_effect=follow):
                result=a.watch(auto_resume=True,enemy_race=1,persistent=True)
            self.assertEqual(result,{'result':'stopped'})
            self.assertEqual(calls,[(1,None),(2,None)])
            self.assertTrue(json.loads((root/'artifacts/state.json').read_text())['closed'])


if __name__=='__main__':unittest.main()
