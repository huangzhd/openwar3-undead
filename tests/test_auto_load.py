import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import auto_load as a


class AutoLoadTests(unittest.TestCase):
    row=dict(pid=123,created=100,exe=r'C:\Games\War3.exe',name='War3.exe')
    parent=dict(exe=str(a.PLATFORM_EXE),created=50)

    def test_only_new_configured_game_started_by_kk_is_eligible(self):
        self.assertTrue(a.eligible(self.row,self.row['exe'],99,self.parent))
        self.assertFalse(a.eligible(self.row,self.row['exe'],101,self.parent))
        self.assertFalse(a.eligible(self.row,r'C:\Other\War3.exe',99,self.parent))
        self.assertFalse(a.eligible(self.row,self.row['exe'],99,dict(exe=r'C:\Other\Platform.exe',created=50)))
        self.assertFalse(a.eligible(self.row,self.row['exe'],99,dict(self.parent,created=101)))

    def test_changed_pid_is_rejected_before_loader_launch(self):
        with patch.object(a,'still_same',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'身份'):
                a.holder_args(Path('helper'),self.row,Path('dll'),Path('stop'))

    def test_incompatible_game_is_rejected_before_loader_launch(self):
        with patch.object(a,'still_same',return_value=True),patch.object(a,'compatible_dll',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'Game.dll'):
                a.holder_args(Path('helper'),self.row,Path('dll'),Path('stop'))

    def test_denied_or_incomplete_runtime_never_triggers_loading(self):
        for kind in ('access_denied','runtime_incomplete_or_incompatible','process_changed'):
            with tempfile.TemporaryDirectory() as directory,patch.object(a,'probe',return_value={'bridge':False,'bridge_state':kind,'reason':kind}),patch.object(a.subprocess,'Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'不允许加载'):
                    a.follow_game(self.row,None,None,Path(directory),False,3,lambda *args,**kw:None)
                popen.assert_not_called()

    def test_preexisting_runtime_waits_without_injection_and_honors_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            stop=Path(directory)/'stop';stop.touch()
            with patch.object(a,'STOP',stop),patch.object(a,'probe',return_value={'bridge':True,'ready':False}),patch.object(a.subprocess,'Popen') as popen:
                result=a.follow_game(self.row,None,None,Path(directory),False,3,lambda *args,**kw:None)
            self.assertEqual(result,'stopped_or_game_exited');popen.assert_not_called()

    def test_runtime_hash_mismatch_is_not_accepted(self):
        with patch.object(a,'sha',return_value='wrong'):
            with self.assertRaisesRegex(RuntimeError,'SHA256'):a.verified_runtime()

    def test_other_runner_and_reused_runner_are_not_owned(self):
        state=dict(runner_pid=77,runner_created=8)
        with patch.object(a.psutil,'Process',return_value=N(pid=77,create_time=lambda:8,parents=lambda:[N(pid=99)])):
            self.assertFalse(a.owns_runner(N(pid=12),state))
        with patch.object(a.psutil,'Process',return_value=N(pid=77,create_time=lambda:9,parents=lambda:[N(pid=12)])):
            self.assertFalse(a.owns_runner(N(pid=12),state))

    def test_venv_redirector_child_is_owned_when_identity_matches(self):
        with patch.object(a.psutil,'Process',return_value=N(pid=77,create_time=lambda:8,parents=lambda:[N(pid=12)])):
            self.assertTrue(a.owns_runner(N(pid=12),dict(runner_pid=77,runner_created=8)))

    def test_retry_cannot_follow_a_reused_pid_or_changed_runtime(self):
        for digest,same in ((a.RUNTIME_SHA,False),('wrong',True)):
            with patch.object(a,'still_same',return_value=same),patch.object(a.psutil,'Process') as process:
                with self.assertRaisesRegex(RuntimeError,'身份|记录'):
                    a.validate_retry_record(dict(game=self.row,runtime_sha256=digest),self.row['exe'])
                process.assert_not_called()

    def test_retry_requires_same_configured_game_and_kk_parent(self):
        parent=N(exe=lambda:str(a.PLATFORM_EXE),create_time=lambda:50)
        with patch.object(a,'still_same',return_value=True),patch.object(a.psutil,'Process',return_value=N(parent=lambda:parent)):
            record=dict(game=self.row,runtime_sha256=a.RUNTIME_SHA)
            self.assertEqual(a.validate_retry_record(record,self.row['exe']),self.row)
            with self.assertRaisesRegex(RuntimeError,'不是配置'):
                a.validate_retry_record(record,r'C:\Other\War3.exe')

    def test_cancelled_elevation_does_not_start_watcher(self):
        import auto_load_entry as entry
        from unittest.mock import Mock
        shell=N(ShellExecuteW=Mock(return_value=5))
        with patch.object(entry.sys,'argv',['entry']),patch.object(entry.ctypes.windll.shell32,'IsUserAnAdmin',return_value=False),patch.object(entry.ctypes,'WinDLL',return_value=shell),patch.object(a,'watch') as watch:
            self.assertEqual(entry.main(),1)
        watch.assert_not_called()

    def test_connection_defaults_to_pause_and_auto_resume_is_explicit(self):
        import attach_match
        for automatic in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                out=Path(directory);stop=out/'stop';state=out/'attachment.json';command=out/'command.json'
                state.write_text(json.dumps(dict(closed=False,process=self.row,session='owned',runner_pid=77,runner_created=8)),encoding='utf-8')
                child=N(pid=77,poll=lambda:None,wait=lambda timeout:0)
                writes=[];stages=[]
                original=a.atomic_json
                def write(path,value):
                    if path==command:writes.append(value)
                    original(path,value)
                with patch.object(a,'STOP',stop),patch.object(a,'probe',return_value={'bridge':True,'ready':True}),patch.object(a,'still_same',return_value=True),patch.object(a.subprocess,'Popen',return_value=child) as launch,patch.object(a,'owns_runner',return_value=True),patch.object(attach_match,'STATE',state),patch.object(attach_match,'COMMAND',command),patch.object(a,'atomic_json',side_effect=write),patch.object(a.time,'sleep',side_effect=lambda delay:stop.touch()):
                    result=a.follow_game(self.row,None,None,out,automatic,3,lambda stage,**kw:stages.append(stage))
                self.assertEqual(result,'stopped');self.assertEqual(launch.call_count,1)
                self.assertEqual([x['action'] for x in writes], ['resume','release'] if automatic else ['release'])
                self.assertIn('resume_requested' if automatic else 'attached_paused',stages)
