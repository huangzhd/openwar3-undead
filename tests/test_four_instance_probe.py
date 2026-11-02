import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from learning import four_instance_probe as probe


class FourProbeTests(unittest.TestCase):
    def run_workers(self,cleanup=True,fail_step=False,reset_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();envs={}
            class Env:
                def __init__(self,instance_id,cohort):
                    self.id=instance_id;self.resets=0;self.result_value=None;envs[self.id]=self
                def reset(self,**kw):
                    self.resets+=1;self.clock=1;self.nonce=1;self.result_value=None
                    if self.resets>1:
                        time.sleep(.08)
                        if reset_failure:self.result_value=dict(cleanup_confirmed=True,termination={'classification':'runtime_failure'})
                    return self.observe()
                def observe(self):
                    return dict(token=dict(instance=str(self.id),episode=str(self.resets),run_id=f'{self.id}-{self.resets}',
                                           pid=self.id*100+self.resets,epoch=1,nonce=self.nonce),
                                observation={'clock':self.clock},done=self.result_value is not None,receipts=[{'accepted':True}])
                def step(self,action):
                    if action['token']!=self.observe()['token']:raise ValueError('foreign')
                    if fail_step and self.id==83:raise RuntimeError('worker fault')
                    self.clock+=1;self.nonce+=1;time.sleep(.004);return self.observe()
                def result(self):return self.result_value
                def close(self):
                    if self.result_value is None:
                        self.result_value=dict(cleanup_confirmed=cleanup or self.id!=81,termination={'classification':'user_abort'})
                    return self.result_value
            with patch.object(probe,'ROOT',root),patch.object(probe,'RuleEnvironment',Env):
                threads=[threading.Thread(target=probe.worker,args=(i,'test',root,time.time()+8)) for i in probe.INSTANCES]
                for t in threads:t.start()
                for t in threads:t.join(10)
                self.assertFalse(any(t.is_alive() for t in threads))
            return [json.loads((root/f'{i}.json').read_text()) for i in probe.INSTANCES],envs

    def test_four_workers_share_real_progress_interval_then_one_resets(self):
        rows,envs=self.run_workers()
        self.assertEqual(probe.assess(rows),[],rows)
        self.assertEqual([e.resets for e in envs.values()].count(2),1)
        self.assertEqual([rows[i]['resets'] for i in range(4)],[2,1,1,1])
        for i in range(4):
            bad=copy.deepcopy(rows)
            bad[i]['common_start']['at']=max(r['episodes'][0]['ready_at'] for r in rows)-1
            self.assertIn('no_common_progress:'+str(81+i),probe.assess(bad))
            bad=copy.deepcopy(rows);bad[i]['common_done']['accepted']=bad[i]['common_start']['accepted']
            self.assertIn('no_common_progress:'+str(81+i),probe.assess(bad))
        bad=copy.deepcopy(rows);bad[2]['restart_seen']['clock']=bad[2]['reset_running_seen']['clock']
        self.assertIn('peer_no_reset_progress:83',probe.assess(bad))
        bad=copy.deepcopy(rows);bad[3]['episodes'][0]['accepted']=bad[3]['restart_seen']['accepted']
        self.assertIn('peer_no_post_reset_progress:84',probe.assess(bad))

    def test_unknown_cleanup_and_peer_failure_never_reset(self):
        for options in (dict(cleanup=False),dict(fail_step=True)):
            rows,envs=self.run_workers(**options)
            self.assertTrue(all(e.resets==1 for e in envs.values()))
            self.assertTrue(probe.assess(rows))

    def test_failed_reset_keeps_first_episode_result(self):
        rows,envs=self.run_workers(reset_failure=True)
        self.assertEqual(rows[0]['status'],'failed')
        self.assertEqual(len(rows[0]['episodes']),1)
        self.assertEqual(rows[0]['episodes'][0]['result']['termination']['classification'],'user_abort')
        self.assertEqual(rows[0]['pending_reset_result']['termination']['classification'],'runtime_failure')
        self.assertEqual(envs[81].resets,2)

    def test_stop_prevents_launch_and_cleanup_uses_explicit_four_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();(root/'artifacts'/'STOP').touch()
            with patch.object(probe,'ROOT',root),patch.object(probe,'active_processes',return_value=[]), \
                 patch.object(probe,'cleanup_owned',return_value=[]) as clean, \
                 patch.object(probe.subprocess,'Popen') as launch,patch.object(probe,'configure_video') as video:
                report=probe.run_probe(root/'probe.json')
            self.assertEqual(report['status'],'failed');launch.assert_not_called();video.assert_not_called()
            self.assertEqual(clean.call_args.kwargs['instance_ids'],(81,82,83,84))

    def test_initial_reset_failure_publishes_attempt_and_preserves_diagnostic_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();seen=[]
            result=dict(run_id='failed-before-ready',cleanup_confirmed=True)
            class Env:
                def __init__(self,**kw):pass
                def reset(self,**kw):
                    seen.append(json.loads((root/'83.json').read_text()))
                    raise PermissionError(13,'denied','owner.json')
                def close(self):return result
            with patch.object(probe,'ROOT',root),patch.object(probe,'RuleEnvironment',Env):
                self.assertEqual(probe.worker(83,'test',root,time.time()+5),1)
            saved=json.loads((root/'83.json').read_text())
            self.assertEqual(seen[0]['resets'],1)
            self.assertEqual(seen[0]['status'],'starting')
            self.assertEqual(saved['pending_reset_result'],result)
            self.assertEqual(saved['episodes'],[])
            self.assertIn('owner.json',saved['error_text'])
            self.assertIn('PermissionError',saved['traceback'])
            self.assertIn('in reset',saved['traceback'])


if __name__=='__main__':unittest.main()
