"""Summarize actual match evidence; does not start or control a game."""
import argparse,json,statistics
from pathlib import Path
from bootstrap import ROOT

def audit(path):
    rows=[json.loads(line) for line in (path/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    result=json.loads((path/'result.json').read_text(encoding='utf-8')) if (path/'result.json').exists() else {'result':'running'}
    formation=[r for r in rows if r['event']=='formation' and r['stage']=='advance' and r['members']>=3]
    verified=[r for r in rows if r['event']=='pullback_verified']
    loot=[r for r in rows if r['event'] in {'loot_confirmed','powerup_confirmed','powerup_collected'}]
    shaped=[r for r in rows if r['event']=='summary' and all(r['units'].get(c,0)>=n for c,n in {'unp2':1,'Udea':1,'Ulic':1,'Nbrn':1,'ucry':6,'uobs':2}.items()) and r['situation']['orb']]
    decisions=[r['clock'] for r in rows if r['event']=='decision']
    return dict(run=path.name,result=result,tech_composition_observed=bool(shaped),
        first_full_composition_clock=shaped[0]['clock'] if shaped else None,
        formation_samples=len(formation),
        max_march_ground_spread=max((r['ground_spread'] for r in formation),default=None),
        median_march_ground_spread=statistics.median(r['ground_spread'] for r in formation) if formation else None,
        max_march_hero_spread=max((r['hero_spread'] for r in formation),default=None),
        verified_pullbacks=verified,verified_loot=loot,
        decision_gap_max=max((b-a for a,b in zip(decisions,decisions[1:])),default=None))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',nargs='?');args=p.parse_args()
    runs=sorted(d for d in (ROOT/'artifacts').iterdir() if d.is_dir() and (d/'events.jsonl').exists())
    target=ROOT/'artifacts'/args.run if args.run else runs[-1]
    print(json.dumps(audit(target),ensure_ascii=False,indent=2))
