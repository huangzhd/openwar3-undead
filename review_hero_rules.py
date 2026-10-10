"""Review own hero skills, fair spell effects and sampled march positions offline."""
import json
import sys
from collections import Counter
from math import hypot
from pathlib import Path


def review(run):
    rows=[json.loads(l) for l in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    learned=[r for r in rows if r['event']=='hero_skill_learn_attempt']
    skills=[]
    for row in rows:
        if row['event']!='summary':continue
        for hero in row['heroes']:
            if hero['type'] in {'Ulic','Nngs'}:
                skills.append(dict(clock=row['clock'],hero=hero['type'],level=hero['level'],
                                   abilities={a['code']:a['level'] for a in hero.get('abilities',[]) if a['level']>0}))
    marches=[]
    for row in rows:
        if row['event']!='march_state':continue
        army=[u for u in row['army'] if u['type'] in {'Udea','Ulic','Nbrn','Nngs','ucry','uobs'}]
        dk=next((u for u in army if u['type']=='Udea'),None)
        companions=[u for u in army if u is not dk]
        if not dk or not companions:continue
        dist=lambda a,b:hypot(a['x']-b['x'],a['y']-b['y'])
        main=min(companions,key=lambda u:sum(dist(u,v) for v in companions))
        marches.append(dict(clock=row['clock'],gap=round(dist(dk,main)),catching_up=dk['catching_up'],
                            dk=[dk['x'],dk['y']],main=[main['x'],main['y']],stage=row['stage']))
    armor=[r for r in rows if r['event']=='frost_armor_attempt']
    armor_effects=[r for r in rows if r['event']=='frost_armor_observed']
    auto=[r for r in rows if r['event']=='hero_autocast_order']
    arrow=[r for r in rows if r['event']=='frost_arrow_effect_observed']
    lich_four=next((s for s in skills if s['hero']=='Ulic' and s['level']>=4 and
                    s['abilities'].get('AUfn',0)>=2 and s['abilities'].get('AUfu',0)>=1 and
                    s['abilities'].get('AUdr',0)>=1),None)
    report=dict(run=run.name,version=result['version'],opponent=result['opponent'],result=result['result'],
                expected_third='Nngs' if result['opponent']['race']==4 else 'Nbrn',
                hires=[r for r in rows if r['event']=='hire'],skill_attempts=learned,skill_samples=skills,
                lich_level_four_skills_observed=lich_four,
                armor_attempts=len(armor),armor_accepted=sum(r['accepted'] for r in armor),
                armor_observed=len(armor_effects),armor_unconfirmed=sum(r['event']=='frost_armor_unconfirmed' for r in rows),
                armor_targets=dict(Counter(r['hero'] for r in armor_effects)),armor_evidence=armor+armor_effects,
                autocast_orders=dict(Counter(r['order'] for r in auto)),
                rejected_autocast=[r for r in auto if not r['accepted']],
                cold_arrow_effects=arrow,forked_lightning_attempts=[r for r in rows if r['event']=='forked_lightning_attempt'],
                march_samples=len(marches),worst_march_dk=max(marches,key=lambda s:s['gap'],default=None),
                march_over_1500=[s for s in marches if s['gap']>1500],
                limitations=['Skill attempts and autocast receipts are separate from observed skill levels and buffs.',
                             'Cold arrow BHca is observed on Naga current target; exact damage attribution is not logged.',
                             'March positions are sampled; pulling/protected units can be absent from march_state.',
                             'A normal victory is not proof of complete search coverage or all hero survival branches.'])
    (run/'hero-rules-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k in {'run','result','expected_third','lich_level_four_skills_observed',
          'armor_attempts','armor_accepted','armor_observed','armor_unconfirmed','armor_targets','autocast_orders',
          'rejected_autocast','march_samples','worst_march_dk'}},ensure_ascii=False,indent=2))
    print(json.dumps(dict(cold_arrow_effects=len(arrow),march_over_1500=len(report['march_over_1500']))))
    return report


if __name__=='__main__':
    for name in sys.argv[1:]:review(Path('artifacts')/name)
