import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as N
import unittest

import bootstrap
import w3fast
from learning.actions import SCHEMA
from learning.dataset import DatasetError,canonical,digest,load_episode
from learning.outcome import classify_outcome
from learning.teacher import POLICY,ACTION,TRAJECTORY
from learning.teacher_dataset import audit_episode
from learning.trajectory import TrajectoryRecorder
from test_learning_trajectory import fixture


class TeacherTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)
        g,raw=fixture()
        g.map=lambda:N(bounds=[-1000,1000,-1000,1000])
        own,seen,hidden=raw.units
        own.has_detail=True;own.abilities=[N(code=c,level=1,cooldown=0) for c in ('Amov','Aatk')]
        own.items=[None]*6
        lane=g.lane.commands
        self.rec=TrajectoryRecorder(g,self.path/'trajectory.jsonl',policy=POLICY)
        point=w3fast.command('point',own,851986,x=22,y=44)
        queued=w3fast.command('point',own,851986,x=22,y=44,extra=1)
        target=w3fast.command('target',own,851971,target=seen)
        hidden_target=w3fast.command('target',own,851971,target=hidden)
        g.lane.commands([point])
        with self.rec.teacher_tick():
            raw.clock+=1
            g.lane.commands([point,queued,target,hidden_target])
        self.assertEqual(lane.call_args.args[0],[point,queued,target,hidden_target])
        with self.rec.teacher_tick():pass
        self.rec.finish('aborted','environment_close')
        self.rows=[json.loads(l) for l in (self.path/'trajectory.jsonl').read_text().splitlines()]
        self.path.joinpath('source').mkdir()
        self.path.joinpath('source','a.py').write_bytes(b'teacher')
        manifest={'a.py':digest(b'teacher')}
        self.put('source-manifest.json',manifest)
        self.put('interface-contract.json',dict(schema='dayuan-interface-contract-v1',policy=POLICY,
            action_version=ACTION,candidate_schema=SCHEMA,observation_version='strict-p1-observation-v5',
            trajectory_schema=TRAJECTORY,binding=dict(pid=101,epoch=1),dependency_errors=[],dependencies={'sdk':digest(b'sdk')},
            slots=dict(observer_player=0,controlled_player=1,opponent_player=2),map_sha256=digest(b'map'),
            source_manifest_sha256=digest(canonical(manifest))))
        self.put('source-audit.json',dict(session_closed=True,source_unchanged=True,active_processes=[],
            errors=[],mismatches=[],frozen_mismatches=[],dependency_mismatches=[]))
        self.put('result.json',dict(id=self.path.name,policy=POLICY,result='aborted',reason='environment_close',
            termination=classify_outcome('aborted','environment_close')))

    def put(self,path,data):
        (self.path/path).write_text(json.dumps(data),encoding='utf8')

    def save_rows(self):
        (self.path/'trajectory.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows),encoding='utf8')

    def test_joint_batch_keeps_order_empty_tick_and_omission_evidence(self):
        report,groups=audit_episode(self.path)
        self.assertEqual(report['operations'],{'move':1,'attack':1})
        self.assertEqual(report['monitored_requests'],5)
        self.assertEqual(report['empty_monitored_ticks'],1)
        self.assertEqual(len(groups),1)
        self.assertEqual([l['ordinal'] for l in groups[0]['labels']],[0,2])
        self.assertEqual(groups[0]['omitted_requests'],2)
        hidden=next(r for r in self.rows if r['event']=='action_request' and r['id']==5)
        self.assertIsNone(hidden['candidate']);self.assertIsNone(hidden['action'])
        self.assertNotIn('arguments',hidden)
        with self.assertRaisesRegex(DatasetError,'legacy_rule_native'):load_episode(self.path)

    def test_queue_bits_and_batch_order_cannot_be_erased_or_reordered(self):
        req=next(r for r in self.rows if r['event']=='action_request' and r['id']==2)
        req['arguments']['extra']=1;self.save_rows()
        with self.assertRaisesRegex(DatasetError,'nonreplacement_order'):audit_episode(self.path)
        req['arguments']['extra']=0
        req['batch_index']=2;self.save_rows()
        with self.assertRaisesRegex(DatasetError,'batch_order'):audit_episode(self.path)

    def test_rejected_unknown_and_incomplete_tick_do_not_make_model_labels(self):
        receipts=[r for r in self.rows if r['event']=='action_receipt']
        receipts[1].update(status=1,accepted=False);receipts[3].update(status=99,accepted=None)
        self.save_rows()
        report,groups=audit_episode(self.path)
        self.assertEqual(groups,[]);self.assertEqual(report['excluded']['receipt_unknown'],1)
        self.assertEqual(report['excluded']['receipt_rejected'],1)
        receipts[1].update(status=0,accepted=True)
        next(r for r in self.rows if r['event']=='tick_end')['complete']=False;self.save_rows()
        self.assertEqual(audit_episode(self.path)[1],[])
