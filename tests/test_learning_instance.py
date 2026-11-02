import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import psutil
from learning.instance import InstanceContext
from session import Session


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.a=InstanceContext(self.root,81,'a'*32)
        self.b=InstanceContext(self.root,82,'a'*32)

    def tearDown(self):self.tmp.cleanup()

    def write(self,ctx,pid,cohort='a'*32,closed=False):
        ctx.directory.mkdir(parents=True,exist_ok=True)
        worker=dict(pid=pid,created=1,name='python.exe')
        game=dict(pid=pid+100,created=2,name=f'War3-{ctx.instance_id}.exe')
        ctx.owner.write_text(json.dumps(dict(instance_id=ctx.instance_id,cohort=cohort,closed=closed,worker=worker)))
        ctx.record.write_text(json.dumps(dict(closed=False,processes=[game])))
        return worker,game

    def test_only_live_matching_cohort_owners_can_admit_their_processes(self):
        wa,ga=self.write(self.a,10);wb,gb=self.write(self.b,20)
        outsider=dict(pid=999,name='War3.exe')
        with patch('machine_start.active_processes',return_value=[wa,ga,wb,gb,outsider]), \
             patch.object(Session,'matches',return_value=True):
            self.assertEqual(self.a.foreign_processes(),[outsider])
            self.write(self.b,20,cohort='b'*32)
            self.assertEqual(self.a.foreign_processes(),[wb,gb,outsider])
            self.write(self.b,20)
            with patch.object(Session,'matches',side_effect=lambda row:row['pid']!=20):
                self.assertEqual(self.a.foreign_processes(),[wb,gb,outsider])

    def test_record_and_cleanup_are_scoped_to_one_instance(self):
        self.a.register()
        before=self.a.record.read_bytes()
        _,game=self.write(self.b,20)
        with patch.object(Session,'matches',return_value=True):
            self.assertEqual(self.a.processes(),[])
            self.assertEqual(self.b.processes(),[game])
        self.a.release()
        self.assertEqual(self.a.record.read_bytes(),before)
        self.assertFalse(json.loads(self.b.owner.read_text())['closed'])

    def test_active_or_reused_worker_and_live_owned_game_block_registration(self):
        self.a.register()
        with self.assertRaisesRegex(RuntimeError,'active worker'):self.a.register()
        with self.assertRaisesRegex(RuntimeError,'separate Python'):self.b.register()
        self.a.release()
        self.b.record.write_text(json.dumps(dict(processes=[dict(pid=999)],closed=False)))
        with patch.object(Session,'matches',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'live processes'):self.b.register()

    def test_local_stop_does_not_stop_other_instance_and_lock_is_bounded(self):
        self.a.directory.mkdir(parents=True)
        self.a.stop.write_text('stop only 81')
        with self.assertRaisesRegex(RuntimeError,'STOP'):
            with self.a.launching(None):self.fail('must not launch')
        with patch.object(self.b,'foreign_processes',return_value=[]):
            with self.b.launching(None):pass
        self.assertEqual(self.a.stop.read_text(),'stop only 81')
        with patch('learning.instance.time.time',side_effect=[0,2]), \
             self.assertRaises(TimeoutError):
            with self.b.launching(1):self.fail('expired launch')

    def test_default_global_process_guard_sees_instance_workers_and_games(self):
        import machine_start
        p=psutil.Process()
        worker=dict(pid=p.pid,created=p.create_time(),name=p.name())
        self.a.directory.mkdir(parents=True)
        self.a.owner.write_text(json.dumps(dict(closed=False,worker=worker)))
        with patch.object(machine_start,'ROOT',self.root),patch.object(psutil,'process_iter',return_value=[]):
            self.assertEqual([r['pid'] for r in machine_start.active_processes()],[p.pid])
            self.a.owner.write_text(json.dumps(dict(closed=True,worker=worker)))
            self.assertEqual(machine_start.active_processes(),[])

    def test_invalid_ids_and_owner_corruption_refuse_without_launch(self):
        for ident,cohort in ((73,'a'*32),(85,'a'*32),(True,'a'*32),(81,'../x')):
            with self.assertRaises(ValueError):InstanceContext(self.root,ident,cohort)
        self.a.directory.mkdir(parents=True)
        self.a.owner.write_text('corrupted')
        with self.assertRaises(ValueError):self.a.register()

    def test_four_live_cohort_instances_allowed_but_foreign_fourth_still_blocks(self):
        contexts=[self.a,self.b,InstanceContext(self.root,83,'a'*32),InstanceContext(self.root,84,'a'*32)]
        active=[]
        for index,context in enumerate(contexts,1):active.extend(self.write(context,index*10))
        with patch('machine_start.active_processes',return_value=active),patch.object(Session,'matches',return_value=True):
            for context in contexts:self.assertEqual(context.foreign_processes(),[])
            self.write(contexts[-1],40,cohort='b'*32)
            self.assertEqual(self.a.foreign_processes(),active[-2:])
        self.assertEqual(len({c.record for c in contexts}),4)
        contexts[2].stop.write_text('stop 83 only')
        self.assertEqual([c.instance_id for c in contexts if c.stop.exists()],[83])

    def test_transient_peer_record_denial_retries_but_permanent_or_corrupt_state_blocks(self):
        self.write(self.a,10);self.write(self.b,20)
        original=Path.read_text;denials=[]
        def read(path,*args,**kwargs):
            if path==self.a.owner and len(denials)<2:
                denials.append(path);raise PermissionError('sharing denial')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),patch('attach_match.time.sleep'), \
             patch('machine_start.active_processes',return_value=[]),patch.object(Session,'matches',return_value=True):
            self.assertEqual(self.b.foreign_processes(),[])
            self.assertEqual(len(denials),2)
        with patch.object(Path,'read_text',side_effect=PermissionError('persistent')),patch('attach_match.time.sleep'):
            with self.assertRaises(PermissionError):self.b.foreign_processes()
        self.a.owner.write_text('corrupt')
        with self.assertRaises(ValueError):self.b.foreign_processes()


if __name__=='__main__':unittest.main()
