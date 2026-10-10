"""Offline combat evidence review; does not connect to or command the game."""
import json
import sys
from collections import Counter
from pathlib import Path


def review(run):
    rows=[json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    states=[r for r in rows if r['event']=='combat_state']
    losses=[];previous={};previous_clock=None;missing_moves=[]
    for state in states:
        current={tuple(u['handle']):u for u in state['army'] if u['type'] not in {'uske','uskm'}}
        for handle in previous.keys()-current.keys():
            losses.append(dict(from_clock=previous_clock,to_clock=state['clock'],last_seen=previous[handle]))
        for u in current.values():
            if u['pulling'] and u['pull'] is None:
                missing_moves.append(dict(clock=state['clock'],unit=u))
        previous=current;previous_clock=state['clock']
    retreats=[]
    for r in rows:
        if r['event']=='decision' and r['actual']=='RETREAT':
            state=next((s for s in reversed(states) if s['clock']<=r['clock']),None)
            retreats.append(dict(clock=r['clock'],fiends=r['fiends'],local_state=None if not state else
                {k:state[k] for k in ['clock','army_hp','enemy_hp','army_health','recent_losses']}))
    selected={'unit_pullback','pullback_verified','skeleton_tank_started','skeleton_tank_observed',
              'black_arrow_autocast_attempt','black_arrow_effect_observed','teleport_attempt','teleport_confirmed'}
    details=[r for r in rows if r['event'] in selected]
    hero_absences=[];previous_heroes=set()
    for row in rows:
        if row['event']!='decision':continue
        heroes={h[0] for h in row['heroes']}
        hero_absences.extend(dict(clock=row['clock'],unit=code) for code in previous_heroes-heroes)
        previous_heroes=heroes
    result=dict(run=run.name,combat_samples=len(states),
        pullbacks_by_type=dict(Counter(r['unit'] for r in details if r['event']=='unit_pullback')),
        movement_verified_by_type=dict(Counter(r['unit'] for r in details if r['event']=='pullback_verified')),
        disappearance_counts=dict(Counter(r['last_seen']['type'] for r in losses)),
        hero_absence_counts=dict(Counter(r['unit'] for r in hero_absences)),hero_absences=hero_absences,
        disappearances=losses,missing_pull_moves=missing_moves,retreats=retreats,details=details,
        limitations=['Disappearance is bracketed between samples; exact death time is not recorded',
                     'Movement alone is not proof of survival or improved win rate',
                     'Weapon escape distances use public base ranges, not hidden enemy upgrades'])
    (run/'combat-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'disappearances','details','retreats','missing_pull_moves'}},ensure_ascii=False))
    print(json.dumps(dict(missing_pull_moves=len(missing_moves),retreats=len(retreats),
        events=dict(Counter(r['event'] for r in details))),ensure_ascii=False))


if __name__=='__main__':
    for name in sys.argv[1:]:review(Path('artifacts')/name)
