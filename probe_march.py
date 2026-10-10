"""Replay observed own-army positions; isolated march fixture, never a P1 match."""
import json,time,traceback,sys
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
label=sys.argv[1]
session=Session(400);dev=None
report={'fixture':True,'counts_as_match':False,'label':label,'passed':False,'events':[],'samples':[]}
positions=[('ucry',-5782,-2634),('ucry',-5999,-2804),('uobs',-5776,-3042),('Ulic',-6000,-2686),('ucry',-5680,-3011),('Udea',-5775,-2952),('ucry',-5701,-3308),('ucry',-5677,-3511),('ucry',-5776,-2843),('uobs',-5725,-3155)]
target=(-5696.,-64.)
try:
 g=session.start();dev=Game(pid=g.pid,fair=False)
 spawned=[dev.spawn(code,x,y) for code,x,y in positions]
 if not all(spawned):raise RuntimeError('Spawn failed')
 handles={u.handle for u in spawned};bot=Controller(g,lambda event,**kw:report['events'].append(dict(event=event,**kw)))
 grid=g.grid();report['grid']={k:getattr(grid,k) for k in ('cols','rows','cell','min_x','min_y')};report['grid']['blocked']=list(grid.blocked)
 deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  s=g.snapshot(max_age=0);army=[u for u in g.my_units() if u.handle in handles]
  bot.go(army,target,s.clock)
  sample={'clock':s.clock,'passed_exit':sum(u.y>-1500 for u in army),'positions':[(u.type,round(u.x),round(u.y)) for u in army],'stage':bot.formation.stage}
  report['samples'].append(sample)
  if sample['passed_exit']==len(positions):report['passed']=True;break
  time.sleep(.2)
 report['after']=report['samples'][-1]
except Exception as e:report['error']=repr(e);traceback.print_exc()
finally:
 if dev:dev.close()
 session.stop();report['owned_processes_closed']=not session.owned
 path=ROOT/'artifacts'/('p1-march-fixture-'+label+'.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('grid','events','samples')},ensure_ascii=False,indent=2))
