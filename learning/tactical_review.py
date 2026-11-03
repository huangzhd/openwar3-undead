"""Read-only review of tactical choices, rule execution and unresolved outcomes."""
import argparse
import json
from pathlib import Path

from learning.dataset import canonical, digest, load_bytes, parse, require, rows, verify_frozen_run


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
    by_id={c['id']:c for c in report['cases']}
    staged={}
    for note in notes:
        require(type(note) is dict and set(note)=={'id','judgment','explanation'},'invalid_note_fields')
        key=note['id']
        require(isinstance(key,str) and key in by_id and key not in staged,'unmatched_or_duplicate_case')
        require(note['judgment'] in ('decision','execution','both','information','reasonable','undetermined')
                and isinstance(note['explanation'],str) and 0<len(note['explanation'].strip())<=1500,'invalid_judgment')
        staged[key]=dict(source='human_review',**fields(note,('judgment','explanation')))
    for key,value in staged.items():by_id[key]['human_review']=value


def review(folder):
    folder=Path(folder).resolve()
    contract,manifest,audit,result=(parse(load_bytes(folder,name)) for name in
        ('interface-contract.json','source-manifest.json','source-audit.json','result.json'))
    require(contract.get('policy') in ('rule','rule_teacher'),'rule_episode_required')
    binding=verify_frozen_run(folder,contract,manifest,audit,result)
    blob=load_bytes(folder,'events.jsonl')
    fingerprint=digest(blob)
    return dict(schema='dayuan-tactical-review-v1',episode=folder.name,binding=binding,
                events_sha256=fingerprint,policy=contract['policy'],outcome=result['termination'],
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
                          needs_review=sum(c['needs_review'] for c in report['cases']))))


if __name__=='__main__':main()
