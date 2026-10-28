import ctypes
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import attach_match as a
from tests.test_attach_0155 import FakeGame


class AtomicStatusTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_real_windows_reader_lock_recovers_without_truncating_old_json(self):
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                                    ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle.restype=wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';a.atomic_json(path,dict(old=True))
            handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            released=False
            def unlock(delay):
                nonlocal released
                self.assertEqual(json.loads(path.read_text()),dict(old=True))
                self.assertTrue(kernel.CloseHandle(handle));released=True
            try:
                with patch.object(a.time,'sleep',side_effect=unlock) as sleep:
                    a.atomic_json(path,dict(new=True))
                sleep.assert_called_once()
                self.assertEqual(json.loads(path.read_text()),dict(new=True))
                self.assertFalse(list(Path(directory).glob('*.tmp')))
            finally:
                if not released:kernel.CloseHandle(handle)

    def test_persistent_denial_is_bounded_and_keeps_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';a.atomic_json(path,dict(old=True))
            with patch.object(a.os,'replace',side_effect=PermissionError('locked')) as replace,patch.object(a.time,'sleep') as sleep:
                with self.assertRaises(PermissionError):a.atomic_json(path,dict(new=True))
            self.assertEqual(replace.call_count,7)
            self.assertLess(sum(x.args[0] for x in sleep.call_args_list),1)
            self.assertEqual(json.loads(path.read_text()),dict(old=True))
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_non_permission_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(a.os,'replace',side_effect=OSError('disk error')),patch.object(a.time,'sleep') as sleep:
                with self.assertRaisesRegex(OSError,'disk error'):a.atomic_json(Path(directory)/'state.json',{})
            sleep.assert_not_called()

    def test_heartbeat_recovers_but_persistent_denial_has_a_deadline(self):
        events=[];publisher=a.StatusPublisher(Path('unused'),lambda event,**kw:events.append(event))
        with patch.object(a,'atomic_json',side_effect=[PermissionError('locked'),None]),patch.object(a.time,'monotonic',return_value=1):
            self.assertFalse(publisher.publish({}))
            self.assertTrue(publisher.publish({}))
        self.assertEqual(events,['attachment_status_write_delayed','attachment_status_write_recovered'])
        with patch.object(a,'atomic_json',side_effect=PermissionError('locked')),patch.object(a.time,'monotonic',side_effect=[20,31]):
            self.assertFalse(publisher.publish({}))
            with self.assertRaisesRegex(RuntimeError,'10秒'):publisher.publish({})

    def test_runner_keeps_processing_commands_and_saves_result_if_final_status_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'undead').mkdir();(root/'data').mkdir()
            for name in ('attach_match.py','attachment_setup.py','kk_control.py','bridge_diagnostics.py','bot.py','data/kk_map_pool.json','data/machine_profiles.json'):
                (root/name).write_text('# fixture')
            state=root/'state.json';command=root/'command.json';game=FakeGame()
            meta=dict(ready=True,process={'pid':123},player=4,epoch=7,clock=100)
            actions=[]
            def step(action):
                actions.append(action)
                return 'released_by_user' if len(actions)>=3 else None
            loop=N(paused=True,step=step)
            original=a.atomic_json;failed=[]
            def write(path,value):
                if path==state and (value.get('closed') or value.get('updated') and not failed):
                    failed.append(True);raise PermissionError('locked status')
                original(path,value)
            with patch.object(a,'ROOT',root),patch.object(a,'STATE',state),patch.object(a,'COMMAND',command),patch.object(a,'RunnerLock',return_value=nullcontext()),patch.object(a,'probe',return_value=meta),patch.object(a,'still_same',return_value=True),patch('undead.game_view.Game',return_value=game),patch.object(a,'Attachment',return_value=loop),patch('attachment_setup.identify_map',return_value=(None,dict(status='unidentified'))),patch('attachment_setup.identify_opponent',return_value=dict(status='verified',controller=1,race=2,race_basis='player_setup')),patch.object(a,'atomic_json',side_effect=write),patch.object(a.time,'sleep'):
                result=a.run_attachment(123)
            self.assertEqual(len(actions),3)
            self.assertEqual(result['reason'],'released_by_user')
            self.assertIn('final_status_write_error',result)
            self.assertTrue(game.closed);self.assertEqual(game.released,[10])
            saved=json.loads(next(root.glob('artifacts/attach-*/result.json')).read_text())
            self.assertEqual(saved['reason'],'released_by_user')
            self.assertIn('final_status_write_error',saved)
