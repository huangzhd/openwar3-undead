"""Offline source/config, expansion, aggro and survival evidence for explicit runs."""
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def review(run_id):
    folder=ROOT/'artifacts'/run_id
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    rows=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    manifest=json.loads((folder/'source-manifest.json').read_text())
    goals=[r for r in rows if r['event']=='attack_goal']
    sightings=[r for r in rows if r['event']=='skeleton_scout_structure_seen']
    chains=[]
    for sighting in sightings:
        goal=next((r for r in goals if r.get('handle')==sighting['handle'] and r['clock']>=sighting['clock']),None)
        if not goal:continue
        samples=[dict(clock=r['clock'],hp=u['hp']) for r in rows if r['event']=='combat_state' and r['clock']>=goal['clock'] for u in r['enemies'] if u['handle']==sighting['handle']]
        chains.append(dict(sighting=sighting,attack_goal=goal,hp_samples=samples,hp_decrease_observed=bool(samples and min(s['hp'] for s in samples)<samples[0]['hp'])))
    combat=json.loads((folder/'combat-review.json').read_text(encoding='utf-8'))
    absence_evidence=[]
    for absence in combat['hero_absences']:
        at=absence['clock'];code=absence['unit'];timeline=[]
        for r in rows:
            if r['event']!='combat_state' or not at-18<=r['clock']<=at+3:continue
            hero=next((u for u in r['army'] if u['type']==code),None)
            dk=next((u for u in r['army'] if u['type']=='Udea'),None)
            gap=math.hypot(hero['x']-dk['x'],hero['y']-dk['y']) if hero and dk else None
            timeline.append(dict(clock=r['clock'],hero=hero,dk=dk,dk_gap=round(gap,2) if gap is not None else None))
        orders=[r for r in rows if at-18<=r.get('clock',-1)<=at+3 and r['event'] in {'coil_heal_attempt','coil_heal_observed','unit_pullback','teleport_attempt','teleport_confirmed'}]
        return_sample=next((r for r in rows if r['event']=='decision' and r['clock']>at and any(h[0]==code for h in r['heroes'])),None)
        absence_evidence.append(dict(absence=absence,timeline=timeline,orders=orders,return_sample=return_sample))
    report=dict(run=run_id,result=result,source_matches_current=all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in manifest.items()),scout_to_attack=chains,goals=goals,aggro_counts=dict(Counter(r['event'] for r in rows if r['event'].startswith('creep_aggro'))),search_events=dict(Counter(r['event'] for r in rows if r['event'].startswith('attack_search'))),hero_absence_counts=combat['hero_absence_counts'],disappearance_counts=combat['disappearance_counts'],hero_absence_evidence=absence_evidence,terminal_confirmed=any(r['event']=='terminal_confirmed' and r['result']==result['result'] for r in rows),limitations=['Sampled disappearance is not continuous death telemetry.','Hero treatment priority applies to eligible targets within 750; sampled distance is not exact cast-time evidence.','Orders and HP changes do not prove per-attack damage attribution.','Visible-point checks do not establish complete region coverage.'])
    (folder/'stability-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k in {'run','source_matches_current','aggro_counts','search_events','hero_absence_counts','disappearance_counts','terminal_confirmed'}},ensure_ascii=False))
    return report

if __name__=='__main__':
    for run_id in sys.argv[1:]:review(run_id)
