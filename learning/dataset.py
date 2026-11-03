"""Read-only primitive episode validation and explicit diagnostic export.

Never opens events, referee traces or diagnostic sidecars. Historical rule-native
v1 labels are incomplete and are refused, not reconstructed from private logs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from learning.actions import validate as validate_action, checked_bounds, OPS, SCHEMA, SHOP_SCHEMA, RESEARCH_SCHEMA, HALL_SCHEMA, SPELL_SCHEMA, LEARN_SCHEMA, LEGACY_SCHEMA, SCHEMA_OPS
from learning.effects import transition_facts
from learning.evidence import safe_path
from learning.observation_schema import validate as validate_observation, ObservationError
from learning.outcome import classify_outcome

SCHEMA_DATASET='dayuan-diagnostic-transitions-v1'
FILES=('interface-contract.json','source-manifest.json','source-audit.json','result.json',
       'trajectory.jsonl','primitive-actions.jsonl')
HASH=re.compile(r'^[0-9a-f]{64}$')


class DatasetError(ValueError):
    pass


def require(condition,reason):
    if not condition:raise DatasetError(reason)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(value):return hashlib.sha256(value).hexdigest()


def parse(text):
    def pairs(values):
        result={}
        for key,value in values:
            require(key not in result,'duplicate_json_key');result[key]=value
        return result
    def constant(_):raise DatasetError('nonfinite_json')
    try:return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except (UnicodeError,json.JSONDecodeError) as exc:raise DatasetError('invalid_json') from exc


def load_bytes(folder,name):
    try:
        path=safe_path(folder,name)
        require(path.is_file() and path.stat().st_size<=256*1024*1024,'missing_or_oversized_evidence')
        return path.read_bytes()
    except (OSError,ValueError) as exc:
        if isinstance(exc,DatasetError):raise
        raise DatasetError('evidence_unavailable') from exc


def rows(data):
    require(bool(data),'empty_log')
    return [parse(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]


def indexed(items,event):
    selected=[r for r in items if r.get('event')==event]
    result={}
    for row in selected:
        key=row.get('id')
        require(type(key) is int and key>0 and key not in result,'duplicate_or_invalid_record_id')
        result[key]=row
    return result


def check_record_order(trajectory,actions):
    observations=set();requests=set();replies=set()
    for row in trajectory:
        event=row['event']
        if event=='observation':observations.add(row['id'])
        elif event=='action_request':
            require(row.get('observation_id') in observations,'native_references_future_observation')
            requests.add(row['id'])
        elif event=='action_receipt':
            require(row['id'] in requests,'native_receipt_before_request');replies.add(row['id'])
    requests=set();gates=set();replies=set()
    for row in actions:
        event=row['event']
        if event=='header':continue
        ident=row['id']
        if event=='request':requests.add(ident)
        elif event=='preflight':
            require(ident in requests and ident not in replies,'preflight_order_invalid');gates.add(ident)
        elif event=='receipt':
            require(ident in requests and (ident in gates or row.get('status')=='interrupted_or_error'),
                    'primitive_receipt_before_request_or_preflight');replies.add(ident)
        elif event=='next_observation':require(ident in replies,'next_observation_before_receipt')


def native_payload(action):
    op=action['op']
    mapping={'move':('point',851986),'attack_move':('point',851983),'attack':('target',851971),
             'stop':('immediate',851972),'hold':('immediate',851993),
             'gather_gold':('target',852018),'gather_lumber':('target',852018)}
    if op in ('use_item_now','use_item_point'):
        return dict(op='use_item',unit=action['unit'],target=None,code=0,x=action.get('x',0.),y=action.get('y',0.),
                    slot=action['slot'],mode=int(op=='use_item_point'),item_at_issue=action['item'])
    if op=='buy_item':
        return dict(op='buy',code=int.from_bytes(action['item'].encode('ascii'),'big'),unit=action['unit'],target=None)
    if op == 'cast_unit':
        from learning.unit_spells import SPELLS
        native,code='target',SPELLS[action['skill']][2]
    elif op == 'learn_skill':
        native,code='learn',int.from_bytes(action['skill'].encode('ascii'),'big')
    elif op in ('build','train','train_hero','upgrade_hall','research'):
        native,code=('build' if op=='build' else 'immediate'),int.from_bytes(action['code'].encode('ascii'),'big')
    else:native,code=mapping[op]
    payload=dict(op=native,code=code,unit=action['unit'],target=action.get('target'))
    if op in ('move','attack_move','build'):payload.update(x=action['x'],y=action['y'])
    if op=='gather_lumber':payload['target_kind']='tree'
    return payload


def verify_frozen_run(folder,contract,manifest,audit,result):
    require(type(manifest) is dict and bool(manifest),'missing_source_manifest')
    require(digest(canonical(manifest))==contract.get('source_manifest_sha256'),'manifest_digest_mismatch')
    for name,expected in manifest.items():
        require(type(expected) is str and HASH.fullmatch(expected),'invalid_source_digest')
        require(digest(load_bytes(folder,'source/'+name))==expected,'frozen_source_mismatch')
    deps=contract.get('dependencies')
    require(type(deps) is dict and bool(deps) and contract.get('dependency_errors')==[],'dependency_evidence_incomplete')
    for name,h in deps.items():
        try:safe_path(folder,name)
        except ValueError as exc:raise DatasetError('invalid_dependency_path') from exc
        require(type(h) is str and HASH.fullmatch(h),'invalid_dependency_digest')
    require(audit.get('source_unchanged') is True and audit.get('session_closed') is True
            and audit.get('active_processes')==[] and audit.get('errors')==[], 'source_or_cleanup_audit_failed')
    require(all(audit.get(key)==[] for key in ('mismatches','frozen_mismatches','dependency_mismatches')),
            'source_or_dependency_mismatch')
    require(result.get('policy')==contract.get('policy'),'result_policy_mismatch')
    require(not any(result.get(k) for k in ('cleanup_error','evidence_error','trajectory_cleanup_error',
            'primitive_cleanup_error','environment_frame_cleanup_error','command_trace_error')), 'runtime_evidence_error')
    require(result.get('id')==folder.name,'episode_directory_mismatch')
    binding=contract.get('binding',{})
    require(all(type(binding.get(k)) is int and binding[k]>0 for k in ('pid','epoch')),'invalid_episode_binding')
    require(contract.get('slots')==dict(observer_player=0,controlled_player=1,opponent_player=2),'invalid_player_slots')
    return binding


def load_episode(folder, *, include_wait=False):
    folder=Path(folder).resolve()
    blobs={name:load_bytes(folder,name) for name in FILES[:4]}
    contract=parse(blobs['interface-contract.json']);manifest=parse(blobs['source-manifest.json'])
    audit=parse(blobs['source-audit.json']);result=parse(blobs['result.json'])
    require(contract.get('policy')=='external_primitives','legacy_rule_native_labels_not_replayable')
    require(contract.get('schema')=='dayuan-interface-contract-v1','unsupported_contract')
    require(contract.get('action_version') in SCHEMA_OPS,'unsupported_action_version')
    versions=(contract.get('observation_version'),contract.get('trajectory_schema'))
    require(versions in (('strict-p1-observation-v1','dayuan-trajectory-v1'),
                        ('strict-p1-observation-v2','dayuan-trajectory-v2'),
                        ('strict-p1-observation-v3','dayuan-trajectory-v3'),
                        ('strict-p1-observation-v4','dayuan-trajectory-v4'),
                        ('strict-p1-observation-v5','dayuan-trajectory-v5'),
                        ('strict-p1-observation-v5','dayuan-trajectory-v6')),'unsupported_observation_trajectory_pair')
    if contract['action_version']==LEARN_SCHEMA:
        require(versions[0]=='strict-p1-observation-v3','skill_observation_required')
    if contract['action_version'] in (SPELL_SCHEMA,HALL_SCHEMA):
        require(versions[0]=='strict-p1-observation-v4','spell_observation_required')
    if contract['action_version'] in (RESEARCH_SCHEMA,SHOP_SCHEMA):
        require(versions==('strict-p1-observation-v5','dayuan-trajectory-v5'),'research_observation_required')
    if contract['action_version']==SCHEMA:
        require(versions==('strict-p1-observation-v5','dayuan-trajectory-v6'),'slot_trajectory_required')
    elif versions[1]=='dayuan-trajectory-v6':
        raise DatasetError('slot_trajectory_action_version_mismatch')
    binding=verify_frozen_run(folder,contract,manifest,audit,result)
    for name in FILES[4:]:blobs[name]=load_bytes(folder,name)
    trajectory=rows(blobs['trajectory.jsonl']);actions=rows(blobs['primitive-actions.jsonl'])
    for records,version in ((trajectory,contract['trajectory_schema']),(actions,contract['action_version'])):
        require(bool(records) and all(type(r) is dict for r in records),'invalid_log_record')
        header=records[0]
        require(header.get('event')=='header' and header.get('schema')==version
                and header.get('policy')=='external_primitives' and header.get('player')==1
                and header.get('epoch')==binding['epoch'],'header_binding_mismatch')
        require(sum(r.get('event')=='header' for r in records)==1,'duplicate_header')
    require(all(r.get('event') in ('header','observation','point_visibility','action_request','action_receipt','terminal')
                for r in trajectory),'unsupported_trajectory_event')
    require(all(r.get('event') in ('header','request','preflight','receipt','next_observation') for r in actions),
            'unsupported_primitive_event')
    observations=indexed(trajectory,'observation')
    require(list(observations)==list(range(1,len(observations)+1)) and bool(observations),'observation_sequence_gap')
    previous=-1
    for row in observations.values():
        try:validate_observation(row['observation'],contract['observation_version'])
        except (ObservationError,KeyError,TypeError) as exc:raise DatasetError('observation_schema_violation') from exc
        clock=row['observation']['clock'];require(clock>previous,'observation_clock_not_increasing');previous=clock
    terminals=[r for r in trajectory if r['event']=='terminal']
    require(len(terminals)==1 and trajectory[-1] is terminals[0],'missing_or_misplaced_terminal')
    terminal=terminals[0];outcome=result.get('termination')
    require(type(outcome) is dict,'missing_outcome')
    expected=classify_outcome(result.get('result'),result.get('reason'),
                             natural_confirmed=outcome.get('classification')=='natural_terminal')
    require(outcome==expected and all(terminal.get(k)==v for k,v in outcome.items()),'outcome_semantics_mismatch')
    require(terminal.get('last_observation_id')==len(observations),'terminal_observation_mismatch')
    req=indexed(actions,'request');pre=indexed(actions,'preflight');rec=indexed(actions,'receipt');later=indexed(actions,'next_observation')
    native=indexed(trajectory,'action_request');native_rec=indexed(trajectory,'action_receipt')
    require(list(req)==list(range(1,len(req)+1)),'primitive_sequence_gap')
    require(req.keys()==rec.keys()==later.keys() and pre.keys()<=req.keys(),'unpaired_primitive_records')
    require(list(native)==list(range(1,len(native)+1)) and native.keys()==native_rec.keys(),'unpaired_native_records')
    check_record_order(trajectory,actions)
    linked=[];samples=[];excluded=Counter();previous_decision=0
    supported=actions[0].get('supported_operations')
    require(supported is None or type(supported) is list and len(supported)==len(set(supported))
            and all(type(op) is str and op in SCHEMA_OPS[contract['action_version']] for op in supported),'invalid_supported_operations')
    try:bounds=checked_bounds(actions[0].get('bounds'))
    except ValueError as exc:raise DatasetError('invalid_public_bounds') from exc
    for ident,request in req.items():
        try:action=validate_action(request['action'])
        except (ValueError,TypeError,KeyError) as exc:raise DatasetError('invalid_action_payload') from exc
        require(action==request['action'],'unnormalized_action_payload')
        require(set(SCHEMA_OPS[action['schema']]) <= set(SCHEMA_OPS[contract['action_version']]),'action_schema_mismatch')
        if supported is not None:require(action['op'] in supported,'undeclared_action_operation')
        decision=request.get('observation_id')
        require(type(decision) is int and decision in observations and decision>previous_decision,'invalid_decision_link')
        previous_decision=decision
        receipt=rec[ident];link=later[ident];gate=pre.get(ident)
        require(receipt.get('effect')==link.get('effect')=='unverified','fabricated_effect_label')
        ids=receipt.get('native_request_ids')
        require(type(ids) is list and len(ids)<=1 and all(type(i) is int and i in native for i in ids),'invalid_native_links')
        linked+=ids
        if gate is None:require(receipt.get('status')=='interrupted_or_error','missing_preflight')
        else:
            oid=gate.get('observation_id')
            require(type(oid) is int and oid in observations and oid>=decision,'invalid_preflight_link')
            require(type(gate.get('clock')) in (int,float) and gate['clock']>=observations[oid]['observation']['clock'],
                    'invalid_preflight_clock')
            require(type(gate.get('allowed')) is bool,'invalid_preflight_verdict')
        if ids:
            n=native[ids[0]];nr=native_rec[ids[0]]
            require(n.get('observation_id') in observations and n['observation_id']>=decision,'invalid_native_observation')
            require(action['op'] not in ('wait','inspect_trees','inspect_research'),'query_sent_native_command')
            if n.get('eligible') is True:
                payload=n.get('action')
                require(payload==native_payload(action),'native_payload_mismatch')
                if action['op'] in ('use_item_now','use_item_point'):
                    require(type(payload['slot']) is int and type(payload['mode']) is int,'invalid_native_item_arguments')
            else:require(n.get('action') is None,'ineligible_native_payload')
            require(nr.get('effect')=='unverified','fabricated_native_effect')
            if receipt.get('status')=='returned':
                require(type(receipt.get('accepted')) is bool and receipt['accepted'] is nr.get('accepted')
                        and receipt.get('native_status')==nr.get('status'),'returned_receipt_mismatch')
            if receipt.get('accepted') is True:
                require(n.get('eligible') is True and nr.get('accepted') is True
                        and type(nr.get('status')) is int and nr['status']==0,'accepted_receipt_mismatch')
        if receipt.get('accepted') is True:
            require(len(ids)==1 and gate is not None and gate['allowed'] is True
                    and receipt.get('status')=='returned' and receipt.get('native_status')==0,'accepted_without_command')
            if action['op'] in ('use_item_now','use_item_point'):
                from learning.items import use_reason
                frame=observations[decision]['observation']
                hero=next((u for u in frame['units'] if u['handle']==action['unit']),None)
                require(hero is not None and use_reason(action,frame,hero)=='allowed','item_slot_evidence_mismatch')
            if action['op']=='buy_item':
                from learning.items import recipient_reason
                frame=observations[decision]['observation']
                units={tuple(u['handle']):u for u in frame['units']}
                shop=units.get(tuple(action['unit']));hero=units.get(tuple(action['target']))
                require(shop is not None and recipient_reason(shop,hero,frame)=='allowed','shop_recipient_evidence_mismatch')
            if action['op']=='research':
                # The engine order encodes only the technology, not its desired
                # rank. The label must also agree with the P1 decision evidence.
                from learning.research import MAX_AGE, PRODUCERS
                frame=observations[decision]['observation']
                prior=frame['research_levels'].get(action['code'])
                require(prior is not None and prior['level']==action['level']-1
                        and 0<=frame['clock']-prior['clock']<=MAX_AGE,'research_rank_evidence_mismatch')
                require(any(u['handle']==action['unit'] and u['owner']==1 and u['alive']
                            and u['type']==PRODUCERS[action['code']] for u in frame['units']),
                        'research_producer_evidence_mismatch')
        status=receipt.get('status')
        if status=='preflight_rejected':
            require(receipt.get('accepted') is False and not ids and gate is not None and gate['allowed'] is False,
                    'invalid_preflight_rejection')
        if action['op'] in ('wait','inspect_trees','inspect_research') and gate is not None and gate['allowed']:
            require(receipt.get('accepted') is None and not ids and status==('no_command' if action['op']=='wait' else 'observation_only'),
                    'invalid_observation_only_receipt')
        nxt=link.get('observation_id')
        if nxt is not None:
            floor=max([decision]+([gate['observation_id']] if gate else [])+[native[i]['observation_id'] for i in ids])
            require(type(nxt) is int and nxt in observations and nxt>floor,'invalid_next_observation')
            require(link.get('clock')==observations[nxt]['observation']['clock']
                    and (gate is None or link['clock']>gate['clock']),'next_observation_not_later')
        else:require(link.get('clock') is None,'missing_next_clock_not_null')
        reason=None
        if outcome['classification'] not in ('natural_terminal','user_abort','time_limit'):reason='failed_episode'
        elif status=='preflight_rejected':reason='preflight_rejected'
        elif receipt.get('accepted') is False:reason='native_rejected'
        elif status not in ('returned','no_command','observation_only') or status=='returned' and receipt.get('accepted') is not True:reason='unknown_receipt'
        elif nxt is None:reason='no_later_observation'
        elif action['op']=='wait' and not include_wait:reason='wait_filtered'
        if reason:excluded[reason]+=1;continue
        before=observations[decision]['observation'];after=observations[nxt]['observation']
        last=ident==len(req) and nxt==terminal['last_observation_id']
        samples.append(dict(step_id=ident,observation_id=decision,next_observation_id=nxt,
                            input=before,action=action,next_observation=after,
                            receipt=dict(accepted=receipt['accepted'],status=status),
                            evidence=transition_facts(action,before,after),
                            terminated=last and outcome['terminated'],truncated=last and outcome['truncated'],
                            terminal_reward=outcome['reward'] if last else None))
    require(len(linked)==len(set(linked)) and sorted(linked)==sorted(native),'unlinked_or_reused_native_request')
    for i,sample in enumerate(samples):
        following=samples[i+1] if i+1<len(samples) else None
        sample['next_sample_contiguous']=bool(following and following['step_id']==sample['step_id']+1
                                              and following['observation_id']==sample['next_observation_id'])
    sequence=dict(all_requests_retained=len(samples)==len(req),
                  adjacent_samples_contiguous=all(s['next_sample_contiguous'] for s in samples[:-1]),
                  terminal_transition_retained=any(s['terminated'] or s['truncated'] for s in samples),
                  episode_last_observation_id=terminal['last_observation_id'])
    provenance={k:contract[k] for k in ('source_manifest_sha256','dependencies','observation_version','trajectory_schema',
                'action_version','map_sha256','policy','rules_version','speed','opponent','opponent_fairness','slots')}
    provenance['supported_operations']=supported
    provenance['public_bounds']=bounds
    group=digest(canonical(provenance))
    return dict(schema=SCHEMA_DATASET,episode=folder.name,provenance_group=group,provenance=provenance,
                input_hashes={name:digest(data) for name,data in blobs.items()},observations=len(observations),
                requests=len(req),samples=samples,excluded=dict(excluded),outcome=outcome,sequence=sequence,
                action_context=dict(schema=contract['action_version'],bounds=bounds,supported_operations=supported),
                training_actor_approved=False,dataset_use='diagnostic_only')


def export_episodes(folders,out,*,include_wait=False,model_tensors=False):
    out=Path(out).resolve();require(not out.exists(),'output_already_exists')
    episodes=[load_episode(folder,include_wait=include_wait) for folder in folders]
    require(bool(episodes),'no_episodes')
    require(len({e['episode'] for e in episodes})==len(episodes),'duplicate_episode')
    if model_tensors:
        from learning.model_codec import encode_sample
        for episode in episodes:
            episode['samples']=[encode_sample(s,episode['action_context'],episode['provenance']['observation_version'])
                                for s in episode['samples']]
    out.mkdir(parents=True)
    summaries=[]
    for episode in episodes:
        group=out/episode['provenance_group'];group.mkdir(exist_ok=True)
        destination=group/(episode['episode']+'.jsonl')
        with destination.open('x',encoding='utf-8') as stream:
            for sample in episode['samples']:
                stream.write(canonical(dict(schema=SCHEMA_DATASET,episode=episode['episode'],**sample)).decode()+'\n')
        summaries.append({k:v for k,v in episode.items() if k!='samples'}|dict(
            transitions=len(episode['samples']),path=destination.relative_to(out).as_posix(),sha256=digest(destination.read_bytes())))
    index=dict(schema=SCHEMA_DATASET,dataset_use='diagnostic_only',training_actor_approved=False,
               include_wait=include_wait,model_tensors=model_tensors,episodes=summaries,
               provenance_groups=len({e['provenance_group'] for e in episodes}))
    if model_tensors:
        from learning.model_codec import model_contract
        index['model_contract']=model_contract()
    with (out/'index.json').open('x',encoding='utf-8') as stream:json.dump(index,stream,ensure_ascii=False,indent=2)
    return index


def verify_export_integrity(folder):
    """Verify an exported bundle's declared hashes/counts, not source authenticity."""
    folder=Path(folder).resolve();index=parse(load_bytes(folder,'index.json'))
    require(index.get('schema')==SCHEMA_DATASET and index.get('dataset_use')=='diagnostic_only'
            and index.get('training_actor_approved') is False,'invalid_export_contract')
    episodes=index.get('episodes');require(type(episodes) is list and bool(episodes),'missing_export_episodes')
    require(type(index.get('model_tensors')) is bool,'unknown_export_encoding')
    if index['model_tensors']:
        from learning.model_codec import model_contract,INPUT_SCHEMA,DECISION_SCHEMA
        require(index.get('model_contract')==model_contract(),'export_model_contract_mismatch')
    seen=set();groups=set();count=0
    for episode in episodes:
        require(episode.get('training_actor_approved') is False and episode.get('dataset_use')=='diagnostic_only',
                'invalid_export_episode_contract')
        ident=episode.get('episode');group=episode.get('provenance_group')
        require(type(ident) is str and ident and ident not in seen,'duplicate_or_invalid_export_episode')
        require(type(group) is str and HASH.fullmatch(group),'invalid_export_group')
        require(digest(canonical(episode.get('provenance')))==group,'export_provenance_mismatch')
        require(episode.get('path')==group+'/'+ident+'.jsonl','unexpected_export_path')
        blob=load_bytes(folder,episode['path'])
        require(digest(blob)==episode.get('sha256'),'export_file_digest_mismatch')
        samples=rows(blob) if blob else []
        require(type(episode.get('transitions')) is int and len(samples)==episode['transitions'],'export_count_mismatch')
        steps=[]
        for sample in samples:
            require(type(sample) is dict and sample.get('schema')==SCHEMA_DATASET and sample.get('episode')==ident,
                    'export_sample_binding_mismatch')
            step=sample.get('step_id');require(type(step) is int and step>0,'invalid_export_step');steps.append(step)
            if index['model_tensors']:
                require(sample.get('input',{}).get('schema')==sample.get('next_input',{}).get('schema')==INPUT_SCHEMA
                        and sample.get('label',{}).get('schema')==DECISION_SCHEMA
                        and sample['label'].get('contract_sha256')==index['model_contract']['sha256'],
                        'export_sample_model_contract_mismatch')
            else:
                try:
                    validate_observation(sample['input'],episode['provenance']['observation_version'])
                    validate_observation(sample['next_observation'],episode['provenance']['observation_version'])
                    validate_action(sample['action'])
                except (ValueError,TypeError,KeyError) as exc:raise DatasetError('export_sample_schema_violation') from exc
        require(steps==sorted(set(steps)),'export_step_sequence_invalid')
        seen.add(ident);groups.add(group);count+=len(samples)
    require(index.get('provenance_groups')==len(groups),'export_group_count_mismatch')
    return dict(status='export_integrity_verified',episodes=len(episodes),transitions=count,
                provenance_groups=len(groups),model_tensors=index['model_tensors'],
                source_authenticity_verified=False,training_actor_approved=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('audit','export','verify'));parser.add_argument('episodes',nargs='+',type=Path)
    parser.add_argument('--out',type=Path);parser.add_argument('--include-wait',action='store_true')
    parser.add_argument('--model-tensors',action='store_true')
    args=parser.parse_args()
    if args.operation=='export':
        if args.out is None:parser.error('export requires --out pointing to a new directory')
        result=export_episodes(args.episodes,args.out,include_wait=args.include_wait,model_tensors=args.model_tensors)
    else:
        result=[]
        for folder in args.episodes:
            try:
                if args.operation=='verify':
                    result.append(dict(folder=folder.name,**verify_export_integrity(folder)));continue
                episode=load_episode(folder,include_wait=args.include_wait)
                result.append({k:v for k,v in episode.items() if k not in ('samples','provenance')}|dict(transitions=len(episode['samples']),status='validated_diagnostic_only'))
            except (DatasetError,KeyError,TypeError) as exc:
                result.append(dict(episode=folder.name,status='rejected',reason=str(exc) if isinstance(exc,DatasetError) else 'malformed_evidence',training_actor_approved=False))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if args.operation in ('audit','verify') and any(r['status']=='rejected' for r in result) else 0


if __name__=='__main__':raise SystemExit(main())
