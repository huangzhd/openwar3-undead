import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning import reset_probe


class ProbeTests(unittest.TestCase):
    def probe(self, *, failure=False, stop=False, no_progress=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);(root/'artifacts').mkdir()
        actions=[];resets=[];closed=[]
        class Env:
            token=None
            def reset(self,**kwargs):
                if resets:actions.append('reset_after_result:'+str(self.result()['cleanup_confirmed']))
                resets.append(kwargs);self.token={'run_id':str(len(resets)),'nonce':0};self.steps=0
                return self.observe()
            def observe(self):return dict(token=dict(self.token),observation={'clock':1},done=False,receipts=[])
            def step(self,action):
                if action['token']!=self.token:actions.append('old_token_rejected');raise ValueError('old token')
                actions.append('tick:'+self.token['run_id'])
                if stop:(root/'artifacts'/'STOP').write_text('stop')
                self.steps+=1;self.token['nonce']+=1
                if self.steps==1 and not no_progress:
                    return dict(token=dict(self.token),observation={'clock':2},done=False,receipts=[{'accepted':True}])
                return dict(token=None,observation={'clock':1 if no_progress else 60},done=True,receipts=[])
            def result(self):
                return dict(run_id=self.token['run_id'],cleanup_confirmed=True,
                            termination=dict(classification='runtime_failure' if failure else 'time_limit',reason='game_time_limit'))
            def close(self):closed.append(True);return self.result() if self.token else None
        path=root/'report.json'
        with patch.object(reset_probe,'ROOT',root),patch.object(reset_probe,'RuleEnvironment',Env):
            report=reset_probe.run_probe(2,output=path)
        self.assertEqual(json.loads(path.read_text()),report)
        return report,actions,resets,closed

    def test_exact_episode_count_with_stale_request_rejected_between_resets(self):
        report,actions,resets,closed=self.probe()
        self.assertEqual(report['status'],'passed')
        self.assertEqual(actions,['tick:1','tick:1','reset_after_result:True','old_token_rejected','tick:2','tick:2'])
        self.assertTrue(report['episodes'][1]['old_token_rejected'])
        self.assertEqual([e['accepted'] for e in report['episodes']],[1,1])
        self.assertEqual(len(resets),2)
        self.assertEqual(resets[0]['until'],resets[1]['until'])
        self.assertTrue(closed)

    def test_runtime_failure_never_automatically_restarts(self):
        report,actions,resets,_=self.probe(failure=True)
        self.assertEqual(report['status'],'stopped')
        self.assertEqual(actions,['tick:1','tick:1'])
        self.assertEqual(len(resets),1)

    def test_user_stop_between_episodes_blocks_second_launch(self):
        report,_,resets,_=self.probe(stop=True)
        self.assertEqual(report['reason'],'user_stop')
        self.assertEqual(len(resets),1)

    def test_loading_past_cutoff_without_a_rule_step_cannot_pass(self):
        report,actions,resets,_=self.probe(no_progress=True)
        self.assertEqual(report['status'],'stopped')
        self.assertEqual(report['reason'],'episode_made_no_progress')
        self.assertFalse(report['episodes'][0]['progress_observed'])
        self.assertEqual(actions,['tick:1'])
        self.assertEqual(len(resets),1)

    def test_invalid_or_unbounded_configuration_never_constructs_environment(self):
        with patch.object(reset_probe,'RuleEnvironment') as env:
            for count in (0,11,True):
                with self.assertRaises(ValueError):reset_probe.run_probe(count)
            for limit in (0,float('inf'),float('nan'),True):
                with self.assertRaises(ValueError):reset_probe.run_probe(2,total_wall_seconds=limit)
        env.assert_not_called()


if __name__=='__main__':unittest.main()
