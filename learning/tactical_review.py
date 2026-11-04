"""Read-only review of tactical choices, rule execution and unresolved outcomes."""
import argparse
import json
from pathlib import Path

from learning.dataset import canonical, digest, load_bytes, parse, require, rows, verify_frozen_run
from learning.observation_schema import validate as validate_observation
from learning.effects import transition_facts


def execution_chains(trajectory, episode, fingerprint, observation_version):
    """Join recorded request IDs only; never infer a selection or missing native args."""
    observations = {}; requests = {}; receipts = {}; ordered = []
    selections = {r['id']:r for r in trajectory if r.get('event')=='selection'}
    last_clock = -1
    for line, row in enumerate(trajectory, 1):
        event = row.get('event')
        if event == 'observation':
            ident = row['id']; obs = row['observation']
            require(ident not in observations, 'duplicate_observation')
            validate_observation(obs, observation_version)
            require(obs['clock'] >= last_clock, 'observation_clock_regressed')
            last_clock = obs['clock']
            observations[ident] = (line, obs)
            ordered.append((line, ident, obs))
        elif event == 'action_request':
            ident = row['id']
            require(ident not in requests, 'duplicate_request')
            require(row.get('observation_id') in observations, 'missing_or_future_request_observation')
            require(row['clock'] == observations[row['observation_id']][1]['clock'], 'request_clock_mismatch')
            requests[ident] = (line, row)
        elif event == 'action_receipt':
            ident = row['id']
            require(ident in requests and ident not in receipts, 'unmatched_or_duplicate_receipt')
            require(row.get('accepted') is None or type(row.get('accepted')) is bool, 'invalid_acceptance')
            receipts[ident] = (line, row)
    chains = []
    for ident, (line, req) in requests.items():
        before_line, before = observations[req['observation_id']]
        receipt_line, receipt = receipts.get(ident, (None, {}))
        state = ('unknown' if receipt.get('status') == 99 or receipt.get('accepted') is None
                 else 'accepted' if receipt['accepted'] else 'rejected')
        later = next(((ln, oid, obs) for ln, oid, obs in ordered
                      if receipt_line is not None and ln > receipt_line and obs['clock'] > req['clock']), None)
        # A bounded observation comparison is evidence, not a spell-effect detector.
        if later and later[2]['clock'] - req['clock'] > 2:
            later = None
        action = req.get('action')
        facts = None
        if later and action:
            after = later[2]
            minimal = dict(op='observed_native', unit=action.get('unit', []))
            if action.get('target') is not None: minimal['target'] = action['target']
            facts = transition_facts(minimal, before, after)
            old = {tuple(u['handle']):u for u in before['units']}
            new = {tuple(u['handle']):u for u in after['units']}
            facts['newly_observed_own_units'] = [fields(u, ('handle','type','alive'))
                for h,u in new.items() if h not in old and u['owner'] == 1]
            h = tuple(action.get('unit', []))
            for side, units in (('before', old), ('after', new)):
                u = units.get(h)
                facts['source_'+side] = (fields(u, ('inventory','abilities'))
                                         if u and u['owner'] == 1 else None)
        chains.append(dict(id=digest(canonical([episode,fingerprint,ident])), request_id=ident,
            clock=req['clock'], request_line=line, observation_id=req['observation_id'],
            observation_line=before_line, action=action, eligibility=req.get('eligibility'),
            selection_link=req.get('selection_id'),
            selection=selections.get(req.get('selection_id')),
            selection_status=('recorded' if req.get('selection_id') is not None else
                              'independent_scope' if 'execution_scope' in req else 'not_recorded_per_request'),
            execution_scope=req.get('execution_scope'),execution_action=req.get('execution_action'),
            execution_source='rule', receipt_line=receipt_line, receipt=receipt or None,
            receipt_state=state, after_observation_id=later[1] if later else None,
            after_line=later[0] if later else None, after_clock=later[2]['clock'] if later else None,
            intervening_request_ids=[i for i,(ln,_) in requests.items()
                                     if later and line < ln < later[0]],
            observable_changes=facts, effect='unverified', attribution='undetermined',
            needs_review=state!='accepted' or facts is None, whole_game_cause='not_established'))
    return chains


def fields(row, keys):
    return {k:row[k] for k in keys if k in row}


def cases_from_events(events, episode, fingerprint):
    cases=[]; pending={}; context=None; scout=None
    receipts={row['batch_id']:{r['index']:r for r in row['receipts']} for row in events
              if row['event']=='practice_commands_completed'}

    def finish(channel, row, index, status):
        case=pending.pop(channel,None)
        if case is None:return
        case['end']=dict(clock=row['clock'],event_index=index,event=row['event'],status=status,
                         **(fields(row,('reason','ground_distance')) if status!='superseded' else {}))
        if status=='interrupted' or status=='stalled':
            case['needs_review']=True

    def start(channel, tactic, row, index, selected, candidates, scope, source):
        finish(channel,row,index,'superseded')
        key=digest(canonical([episode,fingerprint,index,channel]))
        case=dict(id=key,channel=channel,tactic=tactic,clock=row['clock'],event_index=index,
                  event=row['event'],selection_source=source,selected=selected,candidates=candidates,
                  candidate_scope=scope,decision_context=context,end=None,needs_review=False,
                  attribution='undetermined',whole_game_cause='not_established')
        if channel in ('camp','harass'):
            parent=pending.get('army_decision')
            case['army_decision_id']=parent['id'] if parent else None
        if channel=='scout':
            case['assigned_scout']=scout
            case['movement_receipts']=dict(accepted=0,rejected=0,unknown=0)
            case['waypoint_examples']=[]
        cases.append(case);pending[channel]=case

    for index,row in enumerate(events,1):
        event=row['event']
        if 'clock' not in row:continue
        if event=='decision':
            context=fields(row,('clock','heroes','army_hp','local_enemy_hp','base_enemy_hp','tier',
                                'fiends','expansion','exposed_worker','scouted_attack_target',
                                'creep_targets_available','safety_interrupt','retreat_active'))
            source=row.get('selection_source','unrecorded')
            start('army_decision','choose_tactic',row,index,fields(row,('requested','actual')),
                  row.get('pre_attack_army_options'),'pre_attack_army_modules',source)
            if row.get('actual')!='CREEP':finish('camp',row,index,'interrupted')
            if row.get('actual')!='HARASS':finish('harass',row,index,'interrupted')
        elif event=='scout_assigned':scout=row['handle']
        elif event in ('creep_goal','scout_search_started','scout_reference_approach','scout_enemy_dispatch','harass_dispatch'):
            channel,tactic={'creep_goal':('camp','creep'),'scout_search_started':('scout','search_critter'),
                            'scout_reference_approach':('scout','reference_approach'),
                            'scout_enemy_dispatch':('scout','scout_enemy'),'harass_dispatch':('harass','harass')}[event]
            start(channel,tactic,row,index,fields(row,('point','camp','target','scout','squad','search_kind','ground_distance')),
                  row.get('candidates'),row.get('candidate_scope'),'rule_executor')
        elif event=='scout_neutral_detour' and 'scout' in pending:
            case=pending['scout']
            if case['selected']['point']==row['goal'] and len(case['waypoint_examples'])<8:
                case['waypoint_examples'].append(fields(row,('clock','origin','point','blocked')))
        elif event=='practice_commands_submitted' and 'scout' in pending:
            case=pending['scout']
            for cmd in row['commands']:
                args=cmd['args']
                if cmd['op']=='point' and args[1:3]==case['assigned_scout'] and args[3]==851986:
                    receipt=receipts.get(row['batch_id'],{}).get(cmd['index'],{})
                    state=receipt.get('ok')
                    case['movement_receipts']['unknown' if state is None or receipt.get('faulted')
                                              or receipt.get('status')==99 or receipt.get('reason') in ('timeout','unknown')
                                              else 'accepted' if state else 'rejected']+=1
        elif event=='scout_reference_deferred':
            job=pending.get('scout')
            if job and job['tactic']=='reference_approach' and job['selected']['point']==row['point']:
                finish('scout',row,index,'stalled' if row.get('reason')=='no_progress' else 'interrupted')
        elif event=='scout_search_finished':
            job=pending.get('scout')
            if job and job['tactic']=='search_critter' and job['selected']['point']==row['point']:
                reason=row.get('reason')
                status=('observed_point' if reason in ('visible_point','arrived') else
                        'stalled' if reason=='no_progress_or_budget' else 'unknown')
                finish('scout',row,index,status)
        elif event in ('creep_area_cleared','creep_target_deferred','creep_paused'):
            job=pending.get('camp')
            if job and job['selected']['camp']==row['camp']:
                finish('camp',row,index,'area_observed_clear' if event=='creep_area_cleared' else 'interrupted')
        elif event=='harass_aborted':finish('harass',row,index,'interrupted')
        elif event=='scout_lost':
            finish('scout',row,index,'interrupted');scout=None
    return cases


def annotate(report, notes):
    require(type(notes) is list,'invalid_notes')
    by_id={c['id']:c for c in report['cases'] + report.get('execution_chains', [])}
    staged={}
    for note in notes:
        require(type(note) is dict and set(note)=={'id','judgment','explanation'},'invalid_note_fields')
        key=note['id']
        require(isinstance(key,str) and key in by_id and key not in staged,'unmatched_or_duplicate_case')
        require(note['judgment'] in ('decision','execution','both','environment','information','reasonable','undetermined')
                and isinstance(note['explanation'],str) and 0<len(note['explanation'].strip())<=1500,'invalid_judgment')
        staged[key]=dict(source='human_review',**fields(note,('judgment','explanation')))
    for key,value in staged.items():by_id[key]['human_review']=value


def review(folder):
    folder=Path(folder).resolve()
    contract,manifest,audit,result=(parse(load_bytes(folder,name)) for name in
        ('interface-contract.json','source-manifest.json','source-audit.json','result.json'))
    require(contract.get('policy') in ('rule','rule_teacher'),'rule_episode_required')
    binding=verify_frozen_run(folder,contract,manifest,audit,result)
    if contract['policy']=='rule_teacher':
        from learning.teacher_dataset import audit_episode
        audit_episode(folder) # validate explicit links before exposing them in review
    blob=load_bytes(folder,'events.jsonl')
    fingerprint=digest(blob)
    trajectory_blob=load_bytes(folder,'trajectory.jsonl')
    require(all(line.strip() for line in trajectory_blob.decode('utf-8-sig').splitlines()),
            'blank_trajectory_line')
    trajectory=rows(trajectory_blob)
    require(trajectory[0].get('event')=='header' and trajectory[0].get('player')==1
            and trajectory[0].get('epoch')==binding['epoch']
            and trajectory[0].get('policy')==contract['policy']
            and trajectory[0].get('schema')==contract['trajectory_schema'], 'trajectory_binding_mismatch')
    return dict(schema='dayuan-tactical-review-v2',episode=folder.name,binding=binding,
                events_sha256=fingerprint,policy=contract['policy'],outcome=result['termination'],
                trajectory_sha256=digest(trajectory_blob),
                source_hashes={name:digest(load_bytes(folder,name)) for name in
                    ('interface-contract.json','source-manifest.json','source-audit.json','result.json')},
                baseline_context=fields(contract, ('source_manifest_sha256','map_sha256','speed','dependencies')),
                execution_chains=execution_chains(trajectory,folder.name,digest(trajectory_blob),
                                                  contract['observation_version']),
                use='retrospective_diagnostic_only',training_labels=0,
                cases=cases_from_events(rows(blob),folder.name,fingerprint))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--notes',type=Path)
    args=parser.parse_args()
    report=review(args.episode)
    if args.notes:annotate(report,parse(args.notes.read_bytes()))
    with args.out.open('x',encoding='utf8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(dict(episode=report['episode'],cases=len(report['cases']),
                          execution_chains=len(report['execution_chains']),
                          needs_review=sum(c['needs_review'] for c in report['cases'] + report['execution_chains']))))


if __name__=='__main__':main()
