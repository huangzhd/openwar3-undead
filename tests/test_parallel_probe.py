import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from learning import parallel_probe as probe


class ParallelProbeTests(unittest.TestCase):
    def test_two_workers_continue_after_peer_cleanup_and_reject_cross_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir()
            instances={}
            class Env:
                def __init__(self,instance_id,cohort):
                    self.id=instance_id;self.clock=1;self.nonce=0;self.closed=False
                    self.rejected=[];instances[self.id]=self
                def reset(self,**kw):return self.observe()
                def observe(self):
                    return dict(token=dict(pid=self.id,run_id=str(self.id),nonce=self.nonce),
                                observation={'clock':self.clock},done=self.closed,receipts=[{'accepted':True}])
                def step(self,action):
                    if action['token']!=self.observe()['token']:
                        self.rejected.append(action['token']);raise ValueError('foreign')
                    self.clock+=1;self.nonce+=1;time.sleep(.005)
                    return self.observe()
                def close(self):
                    self.closed=True
                    return dict(cleanup_confirmed=True,termination={'reason':'environment_close'})
            with patch.object(probe,'ROOT',root),patch.object(probe,'RuleEnvironment',Env):
                threads=[threading.Thread(target=probe.worker,args=(i,'test',root,time.time()+10)) for i in (81,82)]
                for t in threads:t.start()
                for t in threads:t.join(12)
                self.assertFalse(any(t.is_alive() for t in threads))
            rows=[json.loads((root/f'{i}.json').read_text()) for i in (81,82)]
            self.assertEqual(probe.assess(rows),[],rows)
            self.assertEqual(instances[82].rejected[0]['pid'],81)
            self.assertTrue(all(env.closed for env in instances.values()))
            self.assertGreaterEqual(rows[1]['last_clock']-rows[1]['after_peer_clock'],5)
            broken=copy.deepcopy(rows);broken[1]['last_clock']=broken[1]['after_peer_clock']
            self.assertIn('no_progress_after_peer_close',probe.assess(broken))
            broken=copy.deepcopy(rows);broken[1]['ready_at']=broken[0]['closed_at']+1
            self.assertIn('no_overlap',probe.assess(broken))
            broken=copy.deepcopy(rows);broken[1]['accepted']=broken[1]['after_peer_accepted']
            self.assertIn('no_accepted_action_after_peer_close',probe.assess(broken))
            broken=copy.deepcopy(rows);broken[0]['peer_clock_before_close']=broken[1]['overlap_clock']
            self.assertIn('peer_did_not_progress_before_close',probe.assess(broken))

    def test_worker_failure_closes_environment_and_never_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();calls=[]
            class Env:
                def __init__(self,**kw):pass
                def reset(self,**kw):calls.append('reset');raise RuntimeError('load failed')
                def close(self):calls.append('close');return {'cleanup_confirmed':True}
            with patch.object(probe,'ROOT',root),patch.object(probe,'RuleEnvironment',Env):
                self.assertEqual(probe.worker(81,'test',root,time.time()+5),1)
            self.assertEqual(calls,['reset','close'])
            self.assertEqual(json.loads((root/'81.json').read_text())['status'],'failed')

    def test_emergency_cleanup_never_kills_another_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'artifacts'/'instances'/'81';base.mkdir(parents=True)
            (base/'owner.json').write_text(json.dumps({'cohort':'other','worker':{'pid':1}}))
            (base/'session.json').write_text(json.dumps({'processes':[{'pid':10}]}))
            with patch.object(probe,'ROOT',root),patch.object(probe.psutil,'Process') as process:
                self.assertEqual(probe.cleanup_owned('mine',[]),[])
                process.assert_not_called()

    def test_stop_before_probe_does_not_start_worker_or_change_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'artifacts').mkdir();(root/'artifacts'/'STOP').touch()
            with patch.object(probe,'ROOT',root),patch.object(probe,'active_processes',return_value=[]),\
                    patch.object(probe.subprocess,'Popen') as popen,patch.object(probe,'configure_video') as video:
                result=probe.run_probe(root/'probe.json')
                self.assertEqual(result['status'],'failed');popen.assert_not_called();video.assert_not_called()

    def test_four_instance_cleanup_recognizes_owned_venv_child_and_preserves_foreign_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);live={1,2,3,4,5};killed=[]
            identities={i:dict(pid=i,created=i*10,name='python.exe' if i<3 else
                                'war3_launch.exe' if i==3 else f'War3-{i+80}.exe') for i in live}
            def kill(pid):
                killed.append(pid);live.discard(pid)
                if pid==3:live.discard(4)  # Launcher Job releases its game.
            def process(pid):
                row=identities[pid]
                return N(pid=pid,create_time=lambda:row['created'],name=lambda:row['name'],
                         children=lambda **kw:[process(i) for i in (2,3,4)],
                         kill=lambda:kill(pid),wait=lambda **kw:None)
            for ident,cohort,worker,rows in ((84,'mine',identities[2],[identities[3],identities[4]]),
                                              (83,'other',identities[1],[identities[5]])):
                base=root/'artifacts'/'instances'/str(ident);base.mkdir(parents=True)
                (base/'owner.json').write_text(json.dumps(dict(cohort=cohort,worker=worker)))
                (base/'session.json').write_text(json.dumps(dict(processes=rows)))
            parent=N(poll=lambda:None if 1 in live else 0,wait=lambda **kw:None)
            evidence={}
            exit_races=[]
            def matches(row):
                if row['pid']==4 and 3 not in live and not exit_races:
                    exit_races.append(4);raise probe.psutil.AccessDenied(4)
                return row['pid'] in live
            with patch.object(probe,'ROOT',root),patch.object(probe.Session,'matches',side_effect=matches),\
                 patch.object(probe.psutil,'Process',side_effect=process),patch.object(probe.time,'sleep'):
                errors=probe.cleanup_owned('mine',[(parent,identities[1])],evidence,instance_ids=(81,82,83,84))
            self.assertEqual(errors,[])
            self.assertEqual(killed,[3,1,2])
            self.assertEqual(live,{5})
            self.assertEqual(evidence['remaining'],[])
            self.assertIn(identities[3],evidence['checked'])
            self.assertTrue(evidence['transient_identity_errors'])

    def test_unconfirmed_game_exit_remains_failure_without_direct_game_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'artifacts'/'instances'/'84';base.mkdir(parents=True)
            worker=dict(pid=1,created=10,name='python.exe')
            game=dict(pid=4,created=40,name='War3-84.exe')
            (base/'owner.json').write_text(json.dumps(dict(cohort='mine',worker=worker)))
            (base/'session.json').write_text(json.dumps(dict(processes=[game])))
            def matches(row):
                if row==game:raise probe.psutil.AccessDenied(4)
                return False
            evidence={}
            with patch.object(probe,'ROOT',root),patch.object(probe.Session,'matches',side_effect=matches),\
                 patch.object(probe.psutil,'Process') as process,patch.object(probe.time,'monotonic',side_effect=[0,9]):
                errors=probe.cleanup_owned('mine',[(N(poll=lambda:0),worker)],evidence,instance_ids=(84,))
            self.assertIn('Owned process cleanup not confirmed',errors)
            self.assertEqual(evidence['remaining'],[game])
            process.assert_not_called()

    def test_invalid_cleanup_scope_is_rejected_before_touching_processes(self):
        with patch.object(probe.psutil,'Process') as process:
            for ids in ((81,85),(81,81),('../',),()):
                with self.assertRaises(ValueError):probe.cleanup_owned('mine',[],instance_ids=ids)
            process.assert_not_called()


if __name__=='__main__':unittest.main()
