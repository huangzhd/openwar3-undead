import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning.environment import RuleEnvironment
from learning.outcome import classify_outcome
from run_guard import RunInterrupted


class RuleEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.environments=[];self.started=[];self.sent=[];self.closed=[]
        self.cleanup_ok=True;self.next_id=0
        self.terminal_override=None
        self.patches=[patch('learning.environment.ROOT',self.root),
                      patch('learning.environment.active_processes',return_value=[]),
                      patch('run_match._match_steps',side_effect=self.worker,create=True)]
        for p in self.patches:p.start()

    def tearDown(self):
        for env in self.environments:
            try:env.close()
            finally:env._release()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def env(self):
        env=RuleEnvironment();self.environments.append(env);return env

    def worker(self, **kwargs):
        self.next_id+=1;run_id='run-'+str(self.next_id)
        self.started.append((run_id,kwargs))
        folder=self.root/'artifacts'/run_id;folder.mkdir()
        source=self.root/'policy.py';dependency=self.root/'runtime.dll'
        if not source.exists():source.write_bytes(b'policy')
        if not dependency.exists():dependency.write_bytes(b'runtime')
        manifest={'policy.py':hashlib.sha256(source.read_bytes()).hexdigest()}
        (folder/'source-manifest.json').write_text(json.dumps(manifest))
        (folder/'interface-contract.json').write_text(json.dumps(dict(
            source_manifest_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            dependencies={'runtime.dll':hashlib.sha256(dependency.read_bytes()).hexdigest()},dependency_errors=[])))
        frame=dict(event='ready',run_id=run_id,pid=123,epoch=1,player=1,observation_id=1,
                   observation=dict(player=1,clock=2,resources=dict(gold=500)),receipts=[])
        if kwargs.get('control') == 'primitives':
            from learning.actions import SCHEMA
            frame.update(action_context=dict(schema=SCHEMA,bounds=[-1000,1000,-1000,1000]),action_receipts=[])
        outcome,reason='win','all_enemy_buildings_destroyed'
        if self.terminal_override:outcome,reason=self.terminal_override
        try:
            command=yield frame
            self.sent.append((run_id,command))
            frame={**frame,'event':'step','observation_id':2,
                   'observation':dict(player=1,clock=3,resources=dict(gold=400)),
                   'receipts':[dict(id=1,accepted=True,effect='unverified')]}
            command=yield frame
            self.sent.append((run_id,command))
        except RunInterrupted as exc:
            outcome,reason='aborted',exc.reason
        finally:
            self.closed.append(run_id)
        result=dict(id=run_id,termination=classify_outcome(outcome,reason,natural_confirmed=outcome=='win'),
                    environment_final_frame={**frame,'event':'finished',
                        'receipts':[dict(id=2,accepted=None,effect='unverified')]},
                    launch_settings=dict(secret='must not appear in observation'))
        if not self.cleanup_ok:result['cleanup_error']='failed'
        (folder/'result.json').write_text(json.dumps(result))
        audit=dict(source_unchanged=True,session_closed=self.cleanup_ok,
                   active_processes=[] if self.cleanup_ok else [123],errors=[])
        if kwargs.get('instance_context'):
            ctx=kwargs['instance_context']
            audit.update(process_scope='owned_instance',instance_id=ctx.instance_id,cohort=ctx.cohort)
        (folder/'source-audit.json').write_text(json.dumps(audit))
        return result

    def test_steps_use_cached_whitelist_and_terminal_preserves_last_receipts(self):
        env=self.env();ready=env.reset()
        ready['observation']['resources']['gold']=0
        self.assertEqual(env.observe()['observation']['resources']['gold'],500)
        self.assertTrue(ready['cached'])
        frame=env.step(dict(kind='rule_tick',token=ready['token']))
        self.assertEqual(frame['observation']['resources']['gold'],400)
        self.assertEqual(frame['receipts'][0]['accepted'],True)
        final=env.step(dict(kind='rule_tick',token=frame['token']))
        self.assertTrue(final['done']);self.assertIsNone(final['token'])
        self.assertEqual(final['termination']['reward'],1)
        self.assertIsNone(final['receipts'][0]['accepted'])
        self.assertNotIn('launch_settings',env.result())
        self.assertTrue(env.result()['cleanup_confirmed'])

    def test_explicit_primitive_mode_validates_schema_and_rejects_stale_tokens_before_dispatch(self):
        from learning.actions import SCHEMA
        env=RuleEnvironment(control='primitives');self.environments.append(env)
        ready=env.reset()
        self.assertEqual(self.started[-1][1]['control'],'primitives')
        self.assertEqual(env.preflight([dict(schema=SCHEMA,op='wait'),dict(op='set_speed')]),
                         [dict(allowed=True,reason='allowed',cached=True),
                          dict(allowed=False,reason='invalid_schema',cached=True)])
        for request in (dict(kind='rule_tick',token=ready['token']),
                        dict(kind='primitive',token=ready['token'],action=dict(schema=SCHEMA,op='set_speed'))):
            with self.assertRaises(ValueError):env.step(request)
        self.assertEqual(env.observe()['token'],ready['token']);self.assertEqual(self.sent,[])
        payload=dict(schema=SCHEMA,op='wait')
        step=env.step(dict(kind='primitive',token=ready['token'],action=payload))
        self.assertEqual(self.sent,[('run-1',payload)])
        with self.assertRaises(ValueError):env.step(dict(kind='primitive',token=ready['token'],action=payload))
        self.assertEqual(env.observe()['token'],step['token'])
        env.close();next_frame=env.reset()
        with self.assertRaises(ValueError):env.step(dict(kind='primitive',token=step['token'],action=payload))
        self.assertNotEqual(next_frame['token']['episode'],step['token']['episode'])

    def test_rule_environment_does_not_accept_primitives(self):
        env=self.env();frame=env.reset()
        with self.assertRaises(ValueError):env.step(dict(kind='primitive',token=frame['token'],action=dict(op='wait')))
        with self.assertRaises(ValueError):env.preflight([])
        self.assertEqual(self.sent,[])

    def test_old_and_modified_tokens_never_reach_generator(self):
        env=self.env();first=env.reset()
        second=env.step(dict(kind='rule_tick',token=first['token']))
        for action in (dict(kind='rule_tick',token=first['token']),
                       dict(kind='move',token=second['token']),
                       dict(kind='rule_tick',token={**second['token'],'pid':999})):
            with self.assertRaises(ValueError):env.step(action)
        self.assertEqual(self.sent,[('run-1','rule_tick')])

    def test_reset_closes_previous_then_rejects_same_pid_epoch_old_token(self):
        env=self.env();first=env.reset();second=env.reset()
        self.assertEqual(self.closed,['run-1'])
        self.assertEqual(first['token']['pid'],second['token']['pid'])
        self.assertEqual(first['token']['epoch'],second['token']['epoch'])
        with self.assertRaises(ValueError):env.step(dict(kind='rule_tick',token=first['token']))
        self.assertEqual(self.sent,[])
        self.assertNotEqual(first['token']['episode'],second['token']['episode'])

    def test_close_is_idempotent_and_releases_single_instance_lock(self):
        first=self.env();second=self.env();ready=first.reset()
        with self.assertRaises(RuntimeError):second.reset()
        result=first.close()
        self.assertEqual(first.close(),result)
        self.assertEqual(self.closed,['run-1'])
        self.assertEqual(result['termination']['classification'],'user_abort')
        second.reset()
        with self.assertRaises(ValueError):second.step(dict(kind='rule_tick',token=ready['token']))

    def test_cleanup_failure_blocks_next_reset(self):
        env=self.env();env.reset();self.cleanup_ok=False
        self.assertFalse(env.close()['cleanup_confirmed'])
        with self.assertRaises(RuntimeError):env.reset()
        self.assertEqual(len(self.started),1)

    def test_changed_or_missing_audit_and_saved_cleanup_error_block_reset(self):
        for mutation in ('missing','saved_error'):
            env=self.env();env.reset();env.close()
            folder=self.root/'artifacts'/env.result()['run_id']
            if mutation=='missing':(folder/'source-audit.json').unlink()
            else:(folder/'result.json').write_text(json.dumps(dict(evidence_error='failed')))
            count=len(self.started)
            with self.assertRaises(RuntimeError):env.reset()
            self.assertEqual(len(self.started),count)

    def test_stop_activity_and_unsupported_configuration_prevent_launch(self):
        env=self.env()
        for kwargs in (dict(seed=1),dict(map_alias='TM'),dict(policy_version='old'),
                       dict(game_seconds=float('inf')),dict(wall_seconds=0)):
            with self.assertRaises(ValueError):env.reset(**kwargs)
        with patch('learning.environment.active_processes',return_value=[123]):
            with self.assertRaises(RuntimeError):env.reset()
        stop=self.root/'artifacts'/'STOP';stop.write_text('user stop')
        with self.assertRaises(RuntimeError):env.reset()
        self.assertEqual(stop.read_text(),'user stop');self.assertEqual(self.started,[])

    def test_post_close_source_or_dependency_changes_block_next_launch(self):
        for name in ('policy.py','runtime.dll'):
            with self.subTest(name=name):
                env=self.env();env.reset();env.close()
                path=self.root/name;before=path.read_bytes()
                path.write_bytes(before+b'changed after cleanup')
                count=len(self.started)
                with self.assertRaisesRegex(RuntimeError,'source or dependencies'):env.reset()
                self.assertEqual(len(self.started),count)
                path.write_bytes(before)

    def test_missing_invalid_or_incomplete_dependency_evidence_blocks_launch(self):
        for mutation in ('missing','invalid_path','missing_errors','errors','missing_manifest','wrong_manifest_hash'):
            with self.subTest(mutation=mutation):
                env=self.env();env.reset();env.close()
                folder=self.root/'artifacts'/env.result()['run_id']
                path=folder/'interface-contract.json';contract=json.loads(path.read_text())
                if mutation=='missing':path.unlink()
                elif mutation=='missing_manifest':(folder/'source-manifest.json').unlink()
                else:
                    if mutation=='invalid_path':contract['dependencies']={'../escape':'bad'}
                    elif mutation=='missing_errors':del contract['dependency_errors']
                    elif mutation=='errors':contract['dependency_errors']=['incomplete']
                    else:contract['source_manifest_sha256']='bad'
                    path.write_text(json.dumps(contract))
                count=len(self.started)
                with self.assertRaisesRegex(RuntimeError,'source or dependencies'):env.reset()
                self.assertEqual(len(self.started),count)

    def test_context_manager_closes_on_caller_error_without_replacing_it(self):
        env=self.env()
        with self.assertRaisesRegex(ValueError,'caller'):
            with env:
                env.reset();raise ValueError('caller')
        self.assertTrue(env.result()['cleanup_confirmed'])
        self.assertEqual(self.closed,['run-1'])

    def test_isolated_cleanup_allows_other_instance_but_rejects_wrong_audit_binding(self):
        env=RuleEnvironment(instance_id=81,cohort='a'*32);self.environments.append(env)
        ready=env.reset()
        ctx=self.started[0][1]['instance_context']
        self.assertEqual(ctx.record,self.root/'artifacts'/'instances'/'81'/'session.json')
        with patch('learning.environment.active_processes',return_value=[dict(pid=999,name='War3-82.exe')]):
            self.assertTrue(env.close()['cleanup_confirmed'])
        self.assertTrue(json.loads(ctx.owner.read_text())['closed'])
        ctx.record.write_text(json.dumps(dict(closed=False,processes=[])))
        with self.assertRaisesRegex(RuntimeError,'audit changed'):env.reset()
        ctx.record.write_text(json.dumps(dict(closed=True,processes=[])))
        audit_path=self.root/'artifacts'/env.result()['run_id']/'source-audit.json'
        audit=json.loads(audit_path.read_text());audit['instance_id']=82
        audit_path.write_text(json.dumps(audit))
        with self.assertRaisesRegex(RuntimeError,'audit changed'):env.reset()
        self.assertEqual(len(self.started),1)

    def test_process_exit_requires_explicit_reset_and_old_token_never_reaches_new_episode(self):
        env=RuleEnvironment(instance_id=81,cohort='a'*32);self.environments.append(env)
        self.terminal_override=('aborted','human_game_closed')
        frame=env.reset();old=frame['token']
        frame=env.step(dict(kind='rule_tick',token=frame['token']))
        frame=env.step(dict(kind='rule_tick',token=frame['token']))
        self.assertTrue(frame['done'])
        self.assertEqual(frame['termination']['classification'],'process_exit')
        self.assertIsNone(frame['termination']['reward'])
        self.assertTrue(env.result()['cleanup_confirmed'])
        self.assertEqual(len(self.started),1)
        frame=env.reset()
        before=list(self.sent)
        with self.assertRaises(ValueError):env.step(dict(kind='rule_tick',token=old))
        self.assertEqual(env.observe()['token'],frame['token'])
        self.assertEqual(self.sent,before)
        frame=env.step(dict(kind='rule_tick',token=frame['token']))
        self.assertGreater(frame['observation']['clock'],2)
        self.assertEqual(len(self.started),2)


if __name__=='__main__':unittest.main()
