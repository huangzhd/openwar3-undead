"""Bounded read-only fair vision audit of an already running OpenWar3AI session."""
import hashlib,json,time
from types import SimpleNamespace
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.attack_search import AttackSearch

def run():
    report=dict(version='0.1.28-dev',read_only=True,queries=[],events=[],witness=None,max_queries=60,attempts=0)
    report['policy_hash']=hashlib.sha256((ROOT/'undead/attack_search.py').read_bytes()).hexdigest()
    records=json.loads((ROOT/'artifacts/session.json').read_text())['processes']
    row=next(r for r in records if r['name'].lower()=='war3-71.exe' and Session.matches(r))
    report['session_pid']=row['pid'];g=Game(pid=row['pid'],fair=True);end=time.monotonic()+30
    def visible(p):
        if len(report['queries'])>=60 or time.monotonic()>=end:return None
        value=g.visible(*p);report['queries'].append(dict(point=p,visible=value,clock=g.clock()));return value
    try:
        mp=g.map();home=g.my_buildings({'unpl','unp1','unp2'})[0];base=(home.x,home.y)
        main=min((p for p in mp.starts if p!=(0,0) and g.dist(p,base)>1500),key=lambda p:g.dist(p,base))
        camps=json.loads((ROOT/'data/echo_isles_camps.json').read_text())['camps'];sites=[(c['x'],c['y']) for c in camps if c['kind']=='expansion']
        search=AttackSearch(lambda ev,**kw:report['events'].append(dict(event=ev,**kw)))
        candidates=search.candidates(g,base,main,sites)
        for attempt in range(3):
            report['attempts']+=1
            heroes=g.my_heroes();center=(heroes[0].x,heroes[0].y) if heroes else base
            near=sorted((c for c in candidates if c['kind']=='area' and g.dist(c['point'],center)<1400),key=lambda c:g.dist(c['point'],center))[:5]
            for candidate in near:
                p=candidate['point']
                if visible(p) is not True:continue
                for dx,dy in [(384,384),(-384,384),(384,-384),(-384,-384),(448,0),(-448,0),(0,448),(0,-448)]:
                    neighbor=(p[0]+dx,p[1]+dy)
                    if not mp.buildable(*neighbor) or not mp.walkable(*neighbor):continue
                    if visible(neighbor) is not False:continue
                    # The real checker is run as a separate observer: no controller
                    # state is touched and no movement/combat command is issued.
                    search.pending=[dict(candidate)];search.rounds=1
                    before=len(report['events']);search.observe_pending(SimpleNamespace(dist=g.dist,visible=lambda x,y:visible((x,y))),center,g.clock())
                    checked=any(e['event']=='attack_search_checked' for e in report['events'][before:])
                    if checked and visible(neighbor) is False:
                        report['witness']=dict(candidate=candidate,neighbor=neighbor,center=center,clock=g.clock(),neighbor_buildable_terrain=True,candidate_checked=True,neighbor_visible=False)
                        break
                if report['witness']:break
            if report['witness'] or len(report['queries'])>=60 or time.monotonic()+10>=end:break
            time.sleep(10)
        report['point_is_not_region_evidence']=report['witness'] is not None
        report['limitations']=['This is an actual fair visibility counterexample to equating checked with whole-region coverage.','The neighboring terrain point is not an observed enemy building; no hidden enemy units or resources were read.','The running normal controller was not altered; this separate observer never issued movement or combat orders.','It does not show that a later search route would never expose the neighboring point.','No full-map search pass or normal match outcome is claimed.']
    finally:
        g.close()
        (ROOT/'artifacts/p1-search-visibility-audit-0.1.28.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'queries','events','limitations'}},indent=2))
if __name__=='__main__':run()
