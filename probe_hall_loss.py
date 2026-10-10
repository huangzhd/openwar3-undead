"""Isolated real-engine hall-loss regression, excluded from match statistics."""
import json,time,traceback,hashlib
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.economy import HALLS

session=Session(400);dev=None
report={'version':'0.1.15-dev','fixture':True,'counts_as_match':False,'passed':False,'events':[]}
run_id=time.strftime('%Y%m%d-%H%M%S')
path=ROOT/'artifacts'/('p1-hall-loss-fixture-'+run_id+'.json')
report['controller_sha256']=hashlib.sha256((ROOT/'undead/controller.py').read_bytes()).hexdigest()
def log(event,**data):report['events'].append({'event':event,**data})
try:
    g=session.start();dev=Game(pid=g.pid,fair=False)
    original=g.my_buildings(HALLS)[0];x,y=original.x,original.y
    for code,dx,dy in [('unp2',650,0),('uzig',0,-650),('Udea',-300,-400),('Ulic',-100,-400),('Nbrn',100,-400)]+[(c,-400+(i%4)*160,-650-(i//4)*160) for i,c in enumerate(['ucry']*6+['uobs']*2)]:
        if not dev.spawn(code,x+dx,y+dy):raise RuntimeError('Fixture spawn failed: '+code)
    dev.jass.KillUnit(original)
    time.sleep(.3);g.snapshot(max_age=0)
    for hero in g.my_heroes():
        for code in (['stwp','rnec'] if hero.type=='Udea' else ['ocor'] if hero.type=='Ulic' else []):
            dev.jass.UnitAddItemById(hero,int.from_bytes(code.encode(),'big'))
    player=dev.jass.Player(g.me())
    dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(1),0)
    dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(2),0)
    time.sleep(.3);g.snapshot(max_age=0)
    bot=Controller(g,log);bot.tick()
    report['before']={'clock':g.clock(),'attack_committed':bot.attack_committed,'tier':bot.situation.tier}
    if not bot.attack_committed:raise RuntimeError('Actual tier-three orb phase was not established')
    for hall in g.my_buildings(HALLS):dev.jass.KillUnit(hall)
    time.sleep(.3);snap=g.snapshot(max_age=0)
    initial={u.handle:(u.x,u.y) for u in g.units('me',{'Udea','Ulic','Nbrn','ucry','uobs'})}
    start=snap.clock;deadline=time.monotonic()+45;samples=[]
    while time.monotonic()<deadline:
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('Stop requested')
        snap=g.snapshot(max_age=0);bot.tick()
        army=g.units('me',{'Udea','Ulic','Nbrn','ucry','uobs'})
        moved=[u for u in army if u.handle in initial and g.dist(u,initial[u.handle])>200]
        samples.append({'clock':snap.clock,'situation_clock':bot.situation.now,'tier':bot.situation.tier,'halls':len(g.my_buildings(HALLS)),'action':bot.action.name,'moved_over_200':len(moved),'rally_type':bot.home.type})
        if snap.clock-start>20 and len(moved)>=5 and bot.situation.tier==0 and not g.my_buildings(HALLS):
            report['passed']=True;break
        time.sleep(.2)
    report['samples']=samples
    report['after']=samples[-1] if samples else None
    if not report['passed']:report['error']='No confirmed continuing movement after hall loss before fixture timeout'
except Exception as exc:
    report['error']=repr(exc);traceback.print_exc()
finally:
    if dev:dev.close()
    session.stop();report['owned_processes_closed']=not session.owned
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'report':str(path),**{k:v for k,v in report.items() if k not in {'events','samples'}}},ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
