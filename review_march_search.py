"""Offline evidence only: recorded own positions and fair search/goal events."""
import json
import sys
from collections import Counter
from math import hypot
from pathlib import Path


def review(run):
    rows=[json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    starts=[r for r in rows if r['event']=='attack_search_round']
    start=starts[0]['clock'] if starts else None
    end=result['game_seconds']
    samples=[]
    for r in rows:
        if r['event']!='combat_state' or start is None or r['clock']<start:continue
        dk=next((u for u in r['army'] if u['type']=='Udea'),None)
        others=[u for u in r['army'] if u['type'] in {'Ulic','Nbrn','Nngs','ucry','uobs'} and not u['pulling']]
        if not dk or not others or dk['pulling']:continue
        dist=lambda a,b:hypot(a['x']-b['x'],a['y']-b['y'])
        main=min(others,key=lambda u:sum(dist(u,v) for v in others))
        samples.append(dict(clock=r['clock'],gap=round(dist(dk,main)),
                            dk=[dk['x'],dk['y']],main=[main['x'],main['y']],hp=dk['hp']))
    intervals=[];goal=None
    for r in rows:
        if r['event']=='attack_search_goal':goal=r
        elif r['event'] in {'attack_search_checked','attack_search_deferred'} and goal and r['point']==goal['point']:
            intervals.append(dict(start=goal['clock'],end=r['clock'],elapsed=round(r['clock']-goal['clock'],3),
                                  point=r['point'],kind=r['kind'],outcome=r['event']))
            goal=None
    if goal:intervals.append(dict(start=goal['clock'],end=end,elapsed=round(end-goal['clock'],3),
                                  point=goal['point'],kind=goal['kind'],outcome='unfinished'))
    goals=[r for r in rows if r['event']=='attack_goal' and start is not None and r['clock']>=start]
    durations=Counter()
    for i,r in enumerate(goals):
        durations[r['reason']]+=(goals[i+1]['clock'] if i+1<len(goals) else end)-r['clock']
    report=dict(run=run.name,version=result['version'],result=result['result'],first_search_clock=start,
                remaining_game_seconds=round(end-start,3) if start is not None else None,
                search_events=dict(Counter(r['event'] for r in rows if r['event'].startswith('attack_search'))),
                attack_goal_seconds_after_search={k:round(v,3) for k,v in durations.items()},
                slowest_search_intervals=sorted(intervals,key=lambda x:x['elapsed'],reverse=True)[:5],
                nonpull_dk_samples_over_1500=[s for s in samples if s['gap']>1500],
                worst_nonpull_dk_sample=max(samples,key=lambda s:s['gap'],default=None),
                limitations=[
                    'Only combat_state has historical positions; quiet travel is not continuously recorded.',
                    'Goal intervals include combat, shopping and other overrides; they are not pure walking time.',
                    'Old logs contain no per-unit march orders or DK attack target at the worst sample.',
                    'checked records one visible candidate point, not visibility of its whole region.',
                    'No hidden enemy locations were read or inferred; remaining building location is unknown.'])
    (run/'march-search-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'nonpull_dk_samples_over_1500','limitations'}},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    for name in sys.argv[1:]:review(Path('artifacts')/name)
