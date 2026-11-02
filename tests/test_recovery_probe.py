import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

from learning import recovery_probe as probe


class RecoveryProbeTests(unittest.TestCase):
    def run_workers(self, cleanup=True, reset_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();instances={}
            class Env:
                def __init__(self,instance_id,cohort):
                    self.id=instance_id;self.resets=0;self.result_value=None;self.dead=False;instances[self.id]=self
                def reset(self,**kw):
                    self.resets+=1;self.clock=1;self.nonce=1;self.dead=False;self.result_value=None
                    if self.resets>1:
                        time.sleep(.07)
                        if reset_failure:self.result_value=dict(cleanup_confirmed=True,termination=dict(classification='runtime_failure',reward=None))
                    return self.observe()
                def observe(self):
                    return dict(token=dict(instance=str(self.id),episode=str(self.resets),run_id=f'{self.id}-{self.resets}',
                                           pid=self.id*100+self.resets,epoch=1,nonce=self.nonce),
                                observation={'clock':self.clock},done=self.result_value is not None,receipts=[{'accepted':True}])
                def step(self,action):
                    if action['token']!=self.observe()['token']:raise ValueError('stale')
                    if self.dead:
                        self.result_value=dict(cleanup_confirmed=cleanup,termination=dict(classification='process_exit',reward=None))
                        return self.observe()
                    self.clock+=1;self.nonce+=1;time.sleep(.005);return self.observe()
                def result(self):return self.result_value
                def close(self):
                    if self.result_value is None:self.result_value=dict(cleanup_confirmed=True,termination=dict(classification='user_abort',reward=None))
                    return self.result_value
            def inject(i,c,b,publish):
                instances[i].dead=True
                return dict(exit_confirmed=True,requested_at=time.time(),exited_at=time.time())
            with patch.object(probe,'ROOT',root),patch.object(probe,'RuleEnvironment',Env),patch.object(probe,'inject_game_exit',side_effect=inject) as kill:
                threads=[threading.Thread(target=probe.worker,args=(i,'test',root,time.time()+8)) for i in (81,82)]
                for thread in threads:thread.start()
                for thread in threads:thread.join(10)
                self.assertFalse(any(t.is_alive() for t in threads))
            return [json.loads((root/f'{i}.json').read_text()) for i in (81,82)],instances,kill.call_count

    def test_one_fault_one_reset_peer_keeps_running_and_stale_token_rejected(self):
        rows,envs,kills=self.run_workers()
        self.assertEqual(probe.assess(rows),[],rows)
        self.assertEqual((envs[81].resets,envs[82].resets,kills),(2,1,1))
        bad=copy.deepcopy(rows);bad[1]['restart_seen']['accepted']=bad[1]['fault_observed']['accepted']
        self.assertIn('peer_no_progress_during_recovery',probe.assess(bad))
        bad=copy.deepcopy(rows);bad[1]['fault_observed']['at']=bad[0]['fault']['exited_at']-1
        self.assertIn('fault_baseline_before_exit',probe.assess(bad))
        bad=copy.deepcopy(rows);bad[0]['episodes'][1]['binding']['pid']=bad[0]['episodes'][0]['binding']['pid']
        self.assertIn('reused_binding',probe.assess(bad))
        bad=copy.deepcopy(rows);bad[0]['episodes'][0]['result']['termination']['reward']=1
        self.assertIn('incorrect_fault_result',probe.assess(bad))

    def test_uncertain_cleanup_never_resets_fault_instance(self):
        rows,envs,kills=self.run_workers(cleanup=False)
        self.assertEqual(envs[81].resets,1)
        self.assertEqual(rows[0]['status'],'failed')
        self.assertEqual(kills,1)

    def test_failed_reset_preserves_the_first_episode_failure_evidence(self):
        rows,envs,kills=self.run_workers(reset_failure=True)
        self.assertEqual(rows[0]['status'],'failed')
        self.assertEqual(len(rows[0]['episodes']),1)
        self.assertEqual(rows[0]['episodes'][0]['result']['termination']['classification'],'process_exit')
        self.assertEqual(rows[0]['pending_reset_result']['termination']['classification'],'runtime_failure')
        self.assertEqual((envs[81].resets,kills),(2,1))

    def test_fault_injection_only_terminates_validated_owned_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'artifacts'/'instances'/'81';base.mkdir(parents=True)
            worker=dict(pid=1,created=2,name='python.exe');game=dict(pid=10,created=3,name='War3-81.exe')
            launcher=dict(pid=9,created=4,name='war3_launch.exe')
            owner=dict(instance_id=81,cohort='mine',closed=False,worker=worker)
            (base/'session.json').write_text(json.dumps(dict(processes=[launcher,game])))
            current=N(pid=1,create_time=lambda:2,name=lambda:'python.exe')
            target=N(create_time=lambda:4,name=lambda:'war3_launch.exe',ppid=lambda:1,kill=Mock(),wait=Mock())
            game_process=N(create_time=lambda:3,name=lambda:'War3-81.exe',ppid=lambda:9)
            with patch.object(probe,'ROOT',root),patch.object(probe.psutil,'Process',side_effect=lambda pid=None:current if pid is None else game_process if pid==10 else target):
                for mutate in ({'cohort':'other'},{'worker':{**worker,'created':0}},{'closed':True}):
                    (base/'owner.json').write_text(json.dumps({**owner,**mutate}))
                    with self.assertRaises(RuntimeError):probe.inject_game_exit(81,'mine',{'pid':10})
                    target.kill.assert_not_called()
                (base/'owner.json').write_text(json.dumps(owner))
                with patch.object(probe.Session,'matches',return_value=True):
                    for rows in ([game],[game,{**launcher,'name':'another.exe'}],[game,launcher,launcher]):
                        (base/'session.json').write_text(json.dumps(dict(processes=rows)))
                        with self.assertRaises(RuntimeError):probe.inject_game_exit(81,'mine',{'pid':10})
                    target.kill.assert_not_called()
                (base/'session.json').write_text(json.dumps(dict(processes=[launcher,game])))
                for process in (target,game_process):
                    with patch.object(probe.Session,'matches',return_value=True),patch.object(process,'ppid',return_value=999):
                        with self.assertRaisesRegex(RuntimeError,'parent chain'):probe.inject_game_exit(81,'mine',{'pid':10})
                        target.kill.assert_not_called()
                evidence=[]
                with patch.object(probe.Session,'matches',side_effect=[True,True,False]):
                    result=probe.inject_game_exit(81,'mine',{'pid':10},evidence.append)
                self.assertTrue(result['exit_confirmed']);self.assertEqual(result['game'],game)
                self.assertEqual(evidence[1]['stage'],'terminate_launcher')
                target.kill.assert_called_once()
                target.kill.reset_mock();evidence=[]
                with patch.object(probe.Session,'matches',return_value=True),patch.object(probe.time,'monotonic',side_effect=[0,6]):
                    with self.assertRaisesRegex(RuntimeError,'unconfirmed'):
                        probe.inject_game_exit(81,'mine',{'pid':10},evidence.append)
                self.assertFalse(evidence[-1]['exit_confirmed']);self.assertEqual(evidence[-1]['stage'],'wait_game')
                self.assertIn('error',evidence[-1])

    def test_stop_before_launch_preserves_game_and_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();(root/'artifacts'/'STOP').touch()
            with patch.object(probe,'ROOT',root),patch.object(probe,'active_processes',return_value=[]),patch.object(probe,'cleanup_owned',return_value=[]),\
                 patch.object(probe.subprocess,'Popen') as launch,patch.object(probe,'configure_video') as video:
                result=probe.run_probe(root/'probe.json')
            self.assertEqual(result['status'],'failed');launch.assert_not_called();video.assert_not_called()


if __name__=='__main__':unittest.main()
