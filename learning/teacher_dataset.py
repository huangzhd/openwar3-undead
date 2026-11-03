"""Audit a rule-teacher episode and export diagnostic, grouped imitation labels."""
import argparse
from collections import Counter
import json
from pathlib import Path

from learning.actions import SCHEMA,MAX_AGE,checked_bounds,preflight,validate
from learning.dataset import canonical,digest,load_bytes,native_payload,parse,require,rows,verify_frozen_run
from learning.model_codec import encode_action,decode_decision,encode_observation,model_contract
from learning.observation_schema import validate as validate_observation
from learning.outcome import classify_outcome
from learning.teacher import POLICY,ACTION,TRAJECTORY


def audit_episode(folder, *, order_review=False):
    folder=Path(folder).resolve()
    names=('interface-contract.json','source-manifest.json','source-audit.json','result.json','trajectory.jsonl')
    blobs={name:load_bytes(folder,name) for name in names}
    contract,manifest,audit,result=(parse(blobs[name]) for name in names[:4])
    require(contract.get('policy')==POLICY and contract.get('schema')=='dayuan-interface-contract-v1'
            and contract.get('candidate_schema')==SCHEMA and contract.get('action_version')==ACTION
            and contract.get('trajectory_schema')==TRAJECTORY and contract.get('observation_version')=='strict-p1-observation-v5',
            'teacher_contract_required')
    binding=verify_frozen_run(folder,contract,manifest,audit,result)
    records=rows(blobs[names[-1]])
    head=records[0]
    require(head.get('event')=='header' and head.get('schema')==TRAJECTORY and head.get('policy')==POLICY
            and head.get('player')==1 and head.get('epoch')==binding['epoch']
            and head.get('training_actor_approved') is False,'invalid_teacher_header')
    context=dict(schema=SCHEMA,bounds=checked_bounds(head['bounds']))
    observations={};groups=[];requests={};receipts={};batches={}
    current=None
    end=records[-1]
    term=result['termination']
    expected=classify_outcome(result['result'],result['reason'],natural_confirmed=term['classification']=='natural_terminal')
    require(end.get('event')=='terminal' and term==expected and all(end.get(k)==v for k,v in expected.items()),'teacher_terminal_mismatch')
    for row in records[1:-1]:
        event=row['event']
        if event=='observation':
            ident=row['id'];obs=row['observation']
            require(type(ident) is int and ident==len(observations)+1,'teacher_observation_gap')
            validate_observation(obs,contract['observation_version'])
            require(ident==1 or observations[ident-1]['clock']<obs['clock'],'teacher_clock_not_increasing')
            observations[ident]=obs
        elif event=='tick_begin':
            require(current is None and type(row['tick']) is int and row['tick']==len(groups)+1
                    and len(observations)>0 and row['observation_id']==len(observations),'invalid_teacher_tick_start')
            current=dict(tick=row['tick'],observation_id=row['observation_id'],requests=[])
            groups.append(current)
        elif event=='tick_end':
            require(current is not None and row['tick']==current['tick'] and type(row['complete']) is bool
                    and all(i in receipts for i in current['requests']),'invalid_teacher_tick_end')
            current['complete']=row['complete']
            current=None
        elif event=='action_request':
            ident=row['id'];oid=row['observation_id']
            require(type(ident) is int and ident==len(requests)+1 and oid==len(observations) and oid>0
                    and row['clock']==observations[oid]['clock'],'invalid_teacher_request_link')
            require(row['tick']==(current['tick'] if current else None),'teacher_tick_mismatch')
            batch=row['batch'];idx=row['batch_index'];size=row['batch_count']
            require(all(type(v) is int for v in (batch,idx,size)) and 0<=idx<size,'invalid_teacher_batch')
            if idx==0:
                require(batch==len(batches)+1 and (batch==1 or batches[batch-1]['seen']==batches[batch-1]['size']),
                        'teacher_batch_gap')
                batches[batch]=dict(seen=0,size=size,tick=row['tick'],oid=oid)
            require(batch==len(batches) and batch in batches and batches[batch]==dict(seen=idx,size=size,tick=row['tick'],oid=oid),
                    'teacher_batch_order')
            batches[batch]['seen']+=1
            if current:current['requests'].append(ident)
            if row['eligible'] is True:
                require(current is not None and row['eligibility']=='candidate','teacher_label_outside_tick')
                action=validate(row['candidate'])
                require(action['schema']==SCHEMA and canonical(native_payload(action))==canonical(row['action']),
                        'teacher_native_label_mismatch')
                args=dict(extra=action.get('slot',0),mode=int(action['op']=='use_item_point'))
                require(canonical(args)==canonical(row['arguments']),'teacher_nonreplacement_order')
                tick=observations[current['observation_id']];issue=observations[oid]
                require(0<=issue['clock']-tick['clock']<=MAX_AGE and
                        all(preflight(action,o,context['bounds'])=='allowed' for o in (tick,issue)),'teacher_label_not_observable')
            else:
                require(row['eligible'] is False and row['action'] is None and row['candidate'] is None
                        and 'arguments' not in row and isinstance(row['eligibility'],str),'teacher_omission_leak')
            requests[ident]=row
        elif event=='action_receipt':
            ident=row['id']
            require(ident in requests and ident not in receipts and row.get('effect')=='unverified','unpaired_teacher_receipt')
            status=row['status'];accepted=row['accepted']
            require(accepted is (None if status==99 or not isinstance(status,int) else status==0),'teacher_receipt_status_mismatch')
            receipts[ident]=row
        else:require(event=='point_visibility','unexpected_teacher_log_event')
    require(current is None and requests.keys()==receipts.keys() and end.get('last_observation_id')==len(observations)
            and all(b['seen']==b['size'] for b in batches.values()),'incomplete_teacher_episode')
    excludes=Counter();operations=Counter();examples=[];partial=0
    usable=term['classification'] in ('natural_terminal','time_limit','user_abort')
    for group in groups:
        obs=observations[group['observation_id']]
        candidates=[]
        for i in group['requests']:
            req=requests[i];rec=receipts[i]
            reason=(req['eligibility'] if not req['eligible'] else 'failed_episode' if not usable else
                    'incomplete_tick' if not group['complete'] else 'receipt_unknown' if rec['accepted'] is None else
                    'receipt_rejected' if not rec['accepted'] else None)
            if reason:excludes[reason]+=1
            else:candidates.append(req)
        if not candidates:continue
        encoded=encode_observation(obs,context,contract['observation_version'])
        labels=[]
        for req in candidates:
            a=req['candidate'];label=encode_action(encoded,a)
            require(decode_decision(encoded,label)==a,'teacher_codec_roundtrip_failed')
            operations[a['op']]+=1
            labels.append(dict(request=req['id'],issue_observation_id=req['observation_id'],batch=req['batch'],
                               ordinal=req['batch_index'],batch_count=req['batch_count'],decision=label))
        missing=len(group['requests'])-len(labels)
        partial+=int(missing>0)
        examples.append(dict(tick=group['tick'],observation_id=group['observation_id'],input=encoded.features,
                             labels=labels,omitted_requests=missing))
    outside=sum(r['tick'] is None for r in requests.values())
    if outside:excludes['outside_teacher_tick']=outside
    require(sum(operations.values())+sum(excludes.values())==len(requests),'teacher_coverage_mismatch')
    report=dict(schema='dayuan-teacher-groups-v1',episode=folder.name,dataset_use='diagnostic_only',
                training_actor_approved=False,source_manifest_sha256=contract['source_manifest_sha256'],
                map_sha256=contract['map_sha256'],input_hashes={n:digest(b) for n,b in blobs.items()},
                dependencies_sha256=digest(canonical(contract['dependencies'])),model_contract=model_contract(),
                termination=term,observations=len(observations),ticks=len(groups),monitored_requests=len(requests),
                batches=len(batches),ticks_with_labels=len(examples),partially_labeled_ticks=partial,
                empty_monitored_ticks=sum(not g['requests'] for g in groups),labels=sum(operations.values()),
                operations=dict(operations),excluded=dict(excludes))
    if order_review:
        from learning.teacher_order_review import review_requests
        retained={label['request'] for group in examples for label in group['labels']}
        report['order_review']=review_requests(requests.values(),retained)
    return report,examples


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('episode',type=Path);p.add_argument('--out',type=Path)
    p.add_argument('--order-review',action='store_true',help='include per-unit reissue diagnostics')
    args=p.parse_args()
    report,examples=audit_episode(args.episode,order_review=args.order_review)
    if args.out:
        args.out.mkdir(exist_ok=False,parents=True)
        output=args.out/'groups.jsonl'
        with output.open('xb') as stream:
            for row in examples:stream.write(canonical(row)+b'\n')
        report['groups_sha256']=digest(output.read_bytes())
        with (args.out/'index.json').open('xb') as stream:stream.write(canonical(report)+b'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('input_hashes','model_contract')},ensure_ascii=False))


if __name__=='__main__':main()
