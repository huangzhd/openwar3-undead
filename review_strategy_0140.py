"""Offline counterfactual from archived fair samples; never opens a game."""
import json
from types import SimpleNamespace as N
from bootstrap import ROOT
from undead.controller import Controller
from undead.policy import Situation
from math import hypot

def dist(a,b):
    a=(a.x,a.y) if hasattr(a,'x') else a
    b=(b.x,b.y) if hasattr(b,'x') else b
    return hypot(a[0]-b[0],a[1]-b[1])

def run():
    source=ROOT/'artifacts/20261010-124756'
    events=[json.loads(s) for s in (source/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    frames=[json.loads(s) for s in (source/'fair-witness.jsonl').read_text(encoding='utf-8').splitlines()]
    home_row=next(u for u in frames[0]['own'] if u['type']=='unpl')
    home=N(**home_row)
    def unit(row):
        d=dict(row);d['handle']=tuple(d['handle']);d['is_hero']=d['type'][0].isupper()
        return N(**d)
    cases=[]
    for old in [e for e in events if e['event']=='teleport_attempt' and e['accepted']]:
        frame=min(frames,key=lambda r:abs(r['clock']-old['clock']))
        own=[unit(u) for u in frame['own'] if u['alive']]
        enemies=[unit(e) for e in frame['visible_units'] if e['owner']==1 and e['alive']]
        army=[u for u in own if u.type in {'Udea','Ulic','Nngs','Nbrn','ucry','uobs','uske','uskm'}]
        seen=[];commands=[]
        g=N(dist=dist,enemies=lambda:enemies,current_target=lambda u:None,
            inventory=lambda u:u.inventory,use_item=lambda *a,**kw:commands.append(kw) or True)
        b=Controller(g,lambda e,**kw:seen.append(dict(event=e,**kw)));b.home=home
        b.situation=Situation(frame['clock'],local_enemy_hp=sum(e.hp for e in enemies),
                              army_health=sum(u.hp for u in army)/max(1,sum(u.hp_max for u in army)))
        triggered=b.emergency_portal(army,frame['clock'])
        cases.append(dict(old_clock=old['clock'],sample_clock=frame['clock'],delta=round(frame['clock']-old['clock'],3),
                          new_portal_request=triggered,events=seen,
                          wounded=[dict(type=u.type,hp=u.hp,hp_max=u.hp_max) for u in army if u.hp/u.hp_max<.3]))
    old_purchase=next(e for e in events if e['event']=='portal_purchase' and 640<e['clock']<650)
    summary=max((e for e in events if e['event']=='summary' and e['clock']<old_purchase['clock']),key=lambda r:r['clock'])
    heroes=[N(type=h['type'],handle=(i,0)) for i,h in enumerate(summary['heroes'])]
    bags={h.handle:row['inventory'] for h,row in zip(heroes,summary['heroes'])}
    orders=[];g=N(my_heroes=lambda:heroes,inventory=lambda h:bags[h.handle],buy=lambda *a:orders.append(a))
    b=Controller(g,lambda *a,**kw:None)
    ready=b.prepare_attack(heroes,summary['clock'])
    report=dict(version='0.1.40-dev',rules_version='0.1.40',source_run='20261010-124756',offline_only=True,
        portal_samples=cases,duplicate_purchase=dict(old_purchase=old_purchase,preceding_summary_clock=summary['clock'],
        bags=summary['heroes'],new_departure_ready=ready,new_purchase_orders=orders),
        limits=['Counterfactual on nearest historical samples; does not simulate a changed match.',
                'Witness visible_units omits attack targets, so threat reconstruction uses weapon reach only.',
                'No new engine session; natural survival, opening reliability, NC and search remain unverified.'])
    path=ROOT/'artifacts/p1-offline-review-0.1.40.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(portal_samples=[{k:r[k] for k in ('old_clock','sample_clock','new_portal_request')} for r in cases],
                         duplicate_purchase_prevented=ready and not orders),ensure_ascii=False,indent=2))

if __name__=='__main__':run()
