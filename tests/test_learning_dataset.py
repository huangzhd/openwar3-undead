import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from learning.dataset import load_episode,export_episodes,verify_export_integrity,DatasetError,canonical,digest,parse
from learning.outcome import classify_outcome
import test_learning_actions as helpers
from test_learning_actions import action


class DatasetTests(unittest.TestCase):
    def setUp(self):
        helpers.PrimitiveTests.setUp(self)
        self.executor.execute(action('stop',unit=[11,7]),self.decision,1)
        self.raw.clock+=1;self.raw.publish_count+=1;self.rec.observe();self.executor.observe()
        self.executor.execute(action('wait'),self.rec.last_observation,2)
        self.raw.clock+=1;self.raw.publish_count+=1;self.rec.observe();self.executor.observe()
        self.executor.close();self.rec.finish('aborted','environment_close')
        (self.path/'actions.jsonl').rename(self.path/'primitive-actions.jsonl')
        (self.path/'source').mkdir();(self.path/'source/policy.py').write_bytes(b'policy-v1')
        manifest={'policy.py':digest(b'policy-v1')}
        self.write('source-manifest.json',manifest)
        self.write('interface-contract.json',dict(schema='dayuan-interface-contract-v1',policy='external_primitives',
            action_version='dayuan-primitive-action-v2',observation_version='strict-p1-observation-v2',
            trajectory_schema='dayuan-trajectory-v2',source_manifest_sha256=digest(canonical(manifest)),
            dependencies={'vendor/sdk.py':digest(b'sdk')},dependency_errors=[],binding=dict(pid=101,epoch=1),
            slots=dict(observer_player=0,controlled_player=1,opponent_player=2),map_sha256=digest(b'map'),
            rules_version='rules-v1',speed=400,opponent='kfai-human',opponent_fairness='native_KFAI_unverified'))
        self.write('source-audit.json',dict(source_unchanged=True,session_closed=True,active_processes=[],errors=[],
            mismatches=[],frozen_mismatches=[],dependency_mismatches=[]))
        self.write('result.json',dict(id=self.path.name,policy='external_primitives',result='aborted',reason='environment_close',
                                     termination=classify_outcome('aborted','environment_close')))

    def read(self,name):return json.loads((self.path/name).read_text())
    def write(self,name,value):(self.path/name).write_text(json.dumps(value),encoding='utf-8')
    def logs(self,name):return [json.loads(s) for s in (self.path/name).read_text().splitlines()]
    def write_logs(self,name,rows):(self.path/name).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    def mutate(self,name,fn):
        rows=self.logs(name);fn(rows);self.write_logs(name,rows)
    def rejected(self,pattern):
        with self.assertRaisesRegex(DatasetError,pattern):load_episode(self.path)

    def test_valid_pairs_are_diagnostic_only_and_wait_filter_is_explicit(self):
        result=load_episode(self.path)
        self.assertEqual(len(result['samples']),1);self.assertEqual(result['excluded'],{'wait_filtered':1})
        self.assertFalse(result['training_actor_approved']);self.assertEqual(result['dataset_use'],'diagnostic_only')
        sample=result['samples'][0]
        self.assertEqual((sample['input']['clock'],sample['next_observation']['clock']),(10.,11.))
        self.assertFalse(sample['evidence']['causally_attributed']);self.assertIsNone(sample['terminal_reward'])
        all_steps=load_episode(self.path,include_wait=True)['samples']
        self.assertEqual(len(all_steps),2);self.assertTrue(all_steps[-1]['truncated'])
        self.assertFalse(all_steps[-1]['terminated']);self.assertIsNone(all_steps[-1]['terminal_reward'])

    def test_sparse_export_does_not_forge_terminal_or_contiguous_episode(self):
        sparse=load_episode(self.path);full=load_episode(self.path,include_wait=True)
        self.assertFalse(sparse['sequence']['all_requests_retained'])
        self.assertFalse(sparse['sequence']['terminal_transition_retained'])
        self.assertTrue(full['sequence']['all_requests_retained'])
        self.assertTrue(full['sequence']['terminal_transition_retained'])
        self.assertTrue(full['samples'][0]['next_sample_contiguous'])
        self.assertFalse(full['samples'][-1]['next_sample_contiguous'])

    def test_natural_reward_only_attaches_to_actual_terminal_transition(self):
        result=self.read('result.json')
        result.update(result='win',reason='all_enemy_buildings_destroyed',
                      termination=classify_outcome('win','all_enemy_buildings_destroyed',natural_confirmed=True))
        self.write('result.json',result)
        self.mutate('trajectory.jsonl',lambda rows:rows[-1].update(result['termination']))
        samples=load_episode(self.path,include_wait=True)['samples']
        self.assertIsNone(samples[0]['terminal_reward']);self.assertFalse(samples[0]['terminated'])
        self.assertEqual(samples[-1]['terminal_reward'],1);self.assertTrue(samples[-1]['terminated'])
        self.assertFalse(samples[-1]['truncated'])

    def test_audit_cli_returns_failure_for_rejected_evidence(self):
        (self.path/'source/policy.py').write_bytes(b'changed')
        result=subprocess.run([sys.executable,'-X','utf8','-B','-m','learning.dataset','audit',str(self.path)],
                              cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)[0]['reason'],'frozen_source_mismatch')

    def test_native_rejection_and_timeout_never_become_imitated_labels(self):
        original_a=self.logs('primitive-actions.jsonl');original_t=self.logs('trajectory.jsonl')
        for status,accepted,primitive_status,reason in ((7,False,'returned','native_rejected'),(99,None,'timeout_unknown','unknown_receipt')):
            a=copy.deepcopy(original_a);t=copy.deepcopy(original_t)
            next(r for r in a if r['event']=='receipt' and r['id']==1).update(accepted=accepted,native_status=status,status=primitive_status)
            next(r for r in t if r['event']=='action_receipt').update(accepted=accepted,status=status)
            self.write_logs('primitive-actions.jsonl',a);self.write_logs('trajectory.jsonl',t)
            result=load_episode(self.path)
            self.assertEqual(result['samples'],[]);self.assertEqual(result['excluded'][reason],1)

    def test_failed_episode_is_preserved_but_has_no_training_transitions(self):
        result=self.read('result.json');result.update(result='error',reason='private internal details',termination=classify_outcome('error','private internal details'))
        self.write('result.json',result)
        self.mutate('trajectory.jsonl',lambda rows:rows[-1].update(result['termination']))
        episode=load_episode(self.path,include_wait=True)
        self.assertEqual(episode['samples'],[]);self.assertEqual(episode['excluded'],{'failed_episode':2})
        self.assertNotIn('private internal details',json.dumps(episode))

    def test_private_fields_at_each_observation_level_fail_closed(self):
        original=self.logs('trajectory.jsonl')
        for inject in (lambda o:o.update(opponent_gold=999999),
                       lambda o:o['resources'].update(enemy_lumber=999999),
                       lambda o:o['units'][1].update(abilities=[]),
                       lambda o:o['units'][0].update(order_target=[99,7]),
                       lambda o:o['last_seen'][0]['unit'].update(addr=123456)):
            rows=copy.deepcopy(original);inject(next(r['observation'] for r in rows if r['event']=='observation'))
            self.write_logs('trajectory.jsonl',rows);self.rejected('observation_schema_violation')

    def test_future_tree_or_enemy_memory_and_unowned_production_are_rejected(self):
        original=self.logs('trajectory.jsonl')
        for inject in (lambda o:o['last_seen'][0].update(last_seen_clock=10000),
                       lambda o:o['production'][0].update(building=[22,7]),
                       lambda o:o.update(tree_sightings=[dict(handle=[88,7],type='LTlt',x=0,y=0,seen_clock=10000)])):
            rows=copy.deepcopy(original);inject(next(r['observation'] for r in rows if r['event']=='observation'))
            self.write_logs('trajectory.jsonl',rows);self.rejected('observation_schema_violation')

    def test_nan_and_duplicate_json_keys_are_not_silently_accepted(self):
        for value in ('{"a":NaN}','{"a":1,"a":2}'):
            with self.assertRaises(DatasetError):parse(value)
        self.mutate('trajectory.jsonl',lambda rows:next(r['observation'] for r in rows if r['event']=='observation').update(clock=float('inf')))
        self.rejected('nonfinite_json')

    def test_frozen_source_and_manifest_digest_tampering_are_detected(self):
        (self.path/'source/policy.py').write_bytes(b'changed');self.rejected('frozen_source_mismatch')
        (self.path/'source/policy.py').write_bytes(b'policy-v1')
        c=self.read('interface-contract.json');c['source_manifest_sha256']='0'*64;self.write('interface-contract.json',c)
        self.rejected('manifest_digest_mismatch')

    def test_source_path_escape_cannot_read_outside_frozen_directory(self):
        manifest={'../private.py':digest(b'policy-v1')};self.write('source-manifest.json',manifest)
        c=self.read('interface-contract.json');c['source_manifest_sha256']=digest(canonical(manifest));self.write('interface-contract.json',c)
        self.rejected('evidence_unavailable')

    def test_incomplete_dependency_or_cleanup_evidence_is_rejected(self):
        original=self.read('source-audit.json')
        for updates in (dict(session_closed=False),dict(active_processes=[{'pid':1}]),dict(errors=['unknown']),dict(dependency_mismatches=['sdk'])):
            self.write('source-audit.json',original|updates);self.rejected('audit_failed|dependency_mismatch')
        self.write('source-audit.json',original)
        c=self.read('interface-contract.json');c['dependency_errors']=['missing'];self.write('interface-contract.json',c)
        self.rejected('dependency_evidence_incomplete')

    def test_binding_or_policy_mismatch_is_rejected(self):
        self.mutate('primitive-actions.jsonl',lambda rows:rows[0].update(epoch=2));self.rejected('header_binding_mismatch')

    def test_old_rule_native_labels_are_explicitly_refused(self):
        c=self.read('interface-contract.json');c.update(policy='rule',action_version='rule-native-v1');self.write('interface-contract.json',c)
        self.rejected('legacy_rule_native_labels_not_replayable')

    def test_duplicate_missing_and_out_of_order_observations_are_rejected(self):
        original=self.logs('trajectory.jsonl')
        for mutation in (lambda r:r.append(copy.deepcopy(r[1])),
                         lambda r:next(v for v in r if v['event']=='observation' and v['id']==2).update(id=10),
                         lambda r:next(v['observation'] for v in r if v['event']=='observation' and v['id']==2).update(clock=9)):
            rows=copy.deepcopy(original);mutation(rows);self.write_logs('trajectory.jsonl',rows)
            self.rejected('record_id|sequence_gap|clock_not_increasing|observation_schema_violation')

    def test_native_command_arguments_must_match_complete_external_action(self):
        self.mutate('trajectory.jsonl',lambda rows:next(r['action'] for r in rows if r['event']=='action_request').update(code=851993))
        self.rejected('native_payload_mismatch')

    def test_receipts_cannot_be_reordered_before_requests(self):
        a=self.logs('primitive-actions.jsonl')
        index=next(i for i,r in enumerate(a) if r['event']=='receipt')
        a.insert(1,a.pop(index));self.write_logs('primitive-actions.jsonl',a)
        self.rejected('primitive_receipt_before_request')

    def test_native_request_cannot_reference_future_observation(self):
        self.mutate('trajectory.jsonl',lambda rows:next(r for r in rows if r['event']=='action_request').update(observation_id=3))
        self.rejected('native_references_future_observation')

    def test_orphan_or_reused_native_commands_cannot_be_hidden(self):
        self.mutate('primitive-actions.jsonl',lambda rows:next(r for r in rows if r['event']=='receipt' and r['id']==2).update(native_request_ids=[1]))
        self.rejected('invalid_native_observation|query_sent_native_command|reused_native_request')

    def test_claimed_acceptance_requires_real_native_success(self):
        self.mutate('trajectory.jsonl',lambda rows:next(r for r in rows if r['event']=='action_receipt').update(accepted=False,status=1))
        self.rejected('accepted_receipt_mismatch|returned_receipt_mismatch')

    def test_rejection_cannot_contradict_native_acceptance(self):
        self.mutate('primitive-actions.jsonl',lambda rows:next(r for r in rows if r['event']=='receipt' and r['id']==1).update(accepted=False,native_status=1))
        self.rejected('returned_receipt_mismatch')

    def test_next_observation_cannot_point_backwards(self):
        self.mutate('primitive-actions.jsonl',lambda rows:next(r for r in rows if r['event']=='next_observation').update(observation_id=1,clock=10))
        self.rejected('invalid_next_observation')

    def test_cutoff_cannot_acquire_win_reward_even_if_both_summaries_are_edited(self):
        result=self.read('result.json');result['termination']['reward']=1;self.write('result.json',result)
        self.mutate('trajectory.jsonl',lambda rows:rows[-1].update(reward=1));self.rejected('outcome_semantics_mismatch')

    def test_missing_later_frame_is_retained_as_exclusion(self):
        self.mutate('primitive-actions.jsonl',lambda rows:next(r for r in rows if r['event']=='next_observation').update(observation_id=None,clock=None))
        result=load_episode(self.path);self.assertEqual(result['excluded']['no_later_observation'],1)

    def test_diagnostics_are_never_read_or_copied_to_sample(self):
        for name in ('events.jsonl','primitive-diagnostics.jsonl','referee.json'):
            (self.path/name).write_text('SECRET_DIAGNOSTIC_9999')
        result=load_episode(self.path)
        self.assertNotIn('SECRET_DIAGNOSTIC',json.dumps(result));self.assertNotIn('events.jsonl',result['input_hashes'])

    def clone(self,name):
        destination=self.path.parent/(self.path.name+'-'+name)
        shutil.copytree(self.path,destination);self.addCleanup(shutil.rmtree,destination)
        result=json.loads((destination/'result.json').read_text());result['id']=destination.name
        (destination/'result.json').write_text(json.dumps(result));return destination

    def test_provenance_groups_do_not_mix_changed_source_or_map(self):
        other=self.clone('other');c=json.loads((other/'interface-contract.json').read_text());c['map_sha256']=digest(b'other-map')
        (other/'interface-contract.json').write_text(json.dumps(c))
        self.assertNotEqual(load_episode(self.path)['provenance_group'],load_episode(other)['provenance_group'])

    def test_export_preserves_inputs_and_refuses_overwrite(self):
        other=self.clone('other');out=self.path/'export'
        before={p.name:digest(p.read_bytes()) for p in self.path.iterdir() if p.is_file()}
        index=export_episodes([self.path,other],out)
        self.assertEqual(index['provenance_groups'],1);self.assertFalse(index['training_actor_approved'])
        self.assertEqual([e['transitions'] for e in index['episodes']],[1,1])
        self.assertEqual(before,{p.name:digest(p.read_bytes()) for p in self.path.iterdir() if p.is_file()})
        saved=(out/'index.json').read_bytes()
        with self.assertRaisesRegex(DatasetError,'already_exists'):export_episodes([self.path],out)
        self.assertEqual((out/'index.json').read_bytes(),saved)

    def test_export_validates_all_episodes_before_creating_output(self):
        other=self.clone('bad');(other/'source/policy.py').write_bytes(b'bad')
        out=self.path/'invalid-export'
        with self.assertRaises(DatasetError):export_episodes([self.path,other],out)
        self.assertFalse(out.exists())

    def test_model_export_has_pointer_labels_and_separate_next_input(self):
        out=self.path/'model-export';index=export_episodes([self.path],out,model_tensors=True)
        self.assertTrue(index['model_tensors']);self.assertFalse(index['training_actor_approved'])
        sample=json.loads((out/index['episodes'][0]['path']).read_text())
        self.assertEqual(sample['label']['unit'],0)
        self.assertNotIn('handle',json.dumps(sample['input']))
        self.assertIn('next_input',sample);self.assertNotIn('next_input',sample['input'])

    def test_export_integrity_verifier_detects_changed_output_bytes(self):
        out=self.path/'verify-export';index=export_episodes([self.path],out,model_tensors=True)
        verified=verify_export_integrity(out)
        self.assertEqual(verified['transitions'],1);self.assertFalse(verified['training_actor_approved'])
        self.assertFalse(verified['source_authenticity_verified'])
        (out/index['episodes'][0]['path']).write_text('{}\n')
        with self.assertRaisesRegex(DatasetError,'export_file_digest_mismatch'):verify_export_integrity(out)

    def test_export_integrity_rejects_path_escape_and_wrong_counts(self):
        out=self.path/'verify-export';index=export_episodes([self.path],out)
        self.assertEqual(verify_export_integrity(out)['transitions'],1)
        original=copy.deepcopy(index)
        for edit,reason in ((dict(path='../private.json'),'unexpected_export_path'),
                            (dict(transitions=99),'export_count_mismatch')):
            changed=copy.deepcopy(original);changed['episodes'][0].update(edit)
            (out/'index.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(DatasetError,reason):verify_export_integrity(out)


if __name__=='__main__':unittest.main()
