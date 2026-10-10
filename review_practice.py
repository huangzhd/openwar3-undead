"""Offline opening, emergency portal and survival evidence for explicit games."""
import json,sys,hashlib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parent

def review(run_id):
    folder=ROOT/'artifacts'/run_id
    rows=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    purchases=[r for r in rows if r['event']=='purchase' and (r.get('accepted') or r.get('spot'))]
    stages=[r for r in rows if r['event']=='opening_observed'];by_stage={r['stage']:r['clock'] for r in stages}
    def first(code):return next((r.get('clock') for r in purchases if r['code']==code and r['kind']=='train'),None)
    gh=[r for r in purchases if r['code']=='ugho' and r['kind']=='train']
    zigs=[];spots=set()
    for r in purchases:
        if r['code']=='uzig' and r['kind']=='build' and tuple(r['spot']) not in spots:
            spots.add(tuple(r['spot']));zigs.append(r)
    # Repeated accepted orders at one footprint do not establish a second building.
    times=[by_stage.get('crypt_complete'),*(r.get('clock') for r in gh[:2]),
           by_stage.get('three_ghouls_alive'),by_stage.get('dk_rod_in_inventory'),first('unp1'),first('ucry'),
           zigs[1].get('clock') if len(zigs)>1 else None]
    opening_passed=len(times)==8 and all(t is not None for t in times) and times==sorted(times)
    summaries=[r for r in rows if r['event']=='summary']
    effects={code:next((r['clock'] for r in summaries if r['units'].get(code,0)>=count),None)
             for code,count in [('ugho',3),('unp1',1),('ucry',1),('uzig',2),('unp2',1)]}
    portal=[r for r in rows if r['event'].startswith('teleport')]
    chains=[]
    for attempt in [r for r in portal if r['event']=='teleport_attempt']:
        confirmed=next((r for r in portal if r['event']=='teleport_confirmed' and attempt['clock']<=r['clock']<=attempt['clock']+7),None)
        after=next((r for r in summaries if confirmed and confirmed['clock']<=r['clock']),None)
        chains.append(dict(attempt=attempt,confirmed=confirmed,after_summary=after))
    combat=json.loads((folder/'combat-review.json').read_text(encoding='utf-8'))
    p1=json.loads((folder/'p1-review.json').read_text(encoding='utf-8'))
    manifest=json.loads((folder/'source-manifest.json').read_text())
    report=dict(run=run_id,result=result,opening_sequence_passed=opening_passed if stages else None,
        opening_times=times,opening_stages=stages,opening_orders=[r for r in purchases if r.get('clock',9999)<400],
        actual_unit_summary_times=effects,portal_chains=chains,
        risky_camps_deferred=[r for r in rows if r['event']=='creep_target_deferred' and r['reason']=='enemy_main_route'],
        creep_goals=[r for r in rows if r['event']=='creep_goal'],
        consumables=[r for r in rows if r['event'].startswith(('consumable','healing_scroll'))],
        search_counts=dict(Counter(r['event'] for r in rows if r['event'].startswith('attack_search'))),
        hero_absences=combat['hero_absences'],disappearance_counts=combat['disappearance_counts'],
        coil_attempts=p1['coil_attempts'],forbidden_coils=p1['forbidden_coil_attempts'],
        source_matches_current=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in manifest.items()),
        limitations=['Sampled absences are not exact death times.','Purchase receipts alone are not unit or item effects.',
                      'Visible search points do not prove complete area coverage.','Few games do not establish a stable win rate.'])
    (folder/'practice-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(run=run_id,result=result['result'],opening_sequence_passed=report['opening_sequence_passed'],
        opening_times=times,hero_absences=report['hero_absences'],disappearance_counts=report['disappearance_counts'],
        portal_counts=dict(Counter(r['event'] for r in portal)),risky_camps_deferred=len(report['risky_camps_deferred']),
        consumable_counts=dict(Counter(r['event'] for r in report['consumables'])),search_counts=report['search_counts'],
        source_matches_current=report['source_matches_current']),ensure_ascii=False))
    return report

if __name__=='__main__':
    for run_id in sys.argv[1:]:review(run_id)
