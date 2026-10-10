"""Offline DK separation review using observed army positions, not command receipts."""
import json
import sys
from math import hypot
from pathlib import Path


def review(run):
    rows=[json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    samples=[]
    for row in rows:
        if row['event']!='combat_state':continue
        dk=next((u for u in row['army'] if u['type']=='Udea'),None)
        companions=[u for u in row['army'] if u['type'] in {'Ulic','Nbrn','Nngs','ucry','uobs'} and not u['pulling']]
        if dk is None or not companions:continue
        main=min(companions,key=lambda u:sum(hypot(u['x']-v['x'],u['y']-v['y']) for v in companions))
        samples.append(dict(clock=row['clock'],gap=round(hypot(dk['x']-main['x'],dk['y']-main['y'])),
                            hp=dk['hp'],handle=dk['handle'],pulling=dk['pulling'],
                            dk=[dk['x'],dk['y']],main=[main['x'],main['y']]))
    requests=[r for r in rows if r['event']=='dk_support']
    recoveries=[]
    for row in requests:
        before=next((s for s in reversed(samples) if s['clock']<=row['clock'] and row['clock']-s['clock']<=3),None)
        after=next((s for s in samples if row['clock']<s['clock']<=row['clock']+30 and s['handle']==row['handle'] and s['gap']<=550),None)
        if before and before['gap']>550 and (before['gap']>750 or (row.get('gap') or 0)>750) and after:
            recoveries.append(dict(request_clock=row['clock'],request_ground_gap=row.get('gap'),before=before,after=after))
    pulling=[s for s in samples if s['pulling']]
    result=dict(run=run.name,samples=len(samples),pulling_samples=len(pulling),
                max_gap=max((s['gap'] for s in samples),default=None),
                max_pulling_gap=max((s['gap'] for s in pulling),default=None),
                pulling_over_1500=[s for s in pulling if s['gap']>1500],
                support_requests=len(requests),position_verified_recoveries=recoveries,
                worst_samples=sorted(samples,key=lambda s:s['gap'],reverse=True)[:5],
                limitations=['Positions are sampled during nearby main-army combat only; not continuous death/aura telemetry',
                             'Gap is Euclidean for offline comparison; live policy uses ground path distance',
                             'Multiple requests may refer to the same recovery; do not count as independent rescues'])
    (run/'dk-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'position_verified_recoveries','pulling_over_1500','limitations','worst_samples'}},ensure_ascii=False))
    print(json.dumps(dict(over_1500=len(result['pulling_over_1500']),recovery_samples=len(recoveries),worst=result['worst_samples'][:1])))
    return result


if __name__=='__main__':
    for name in sys.argv[1:]:review(Path('artifacts')/name)
