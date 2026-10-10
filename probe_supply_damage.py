"""Bounded isolated supply regression, not a normal match or training sample."""
import hashlib,json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.economy import Economy

def run():
    session=Session(800);dev=None;deadline=time.monotonic()+120
    report=dict(version='0.1.33-dev',fixture=True,counts_as_match=False,passed=False,events=[])
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'undead').glob('*.py'))}
    def log(event,**kw):report['events'].append(dict(event=event,**kw))
    try:
        g=session.start();report['processes']=list(session.owned)
        dev=Game(pid=g.pid,fair=False);home=g.my_buildings({'unpl'})[0]
        x,y=home.x,home.y;p=dev.jass.Player(g.me())
        for state in (1,2):dev.jass.SetPlayerState(p,dev.jass.ConvertPlayerState(state),10000)
        specs=[('uaod',500,600),('usep',500,-650),('utom',850,-300),('ugrv',850,200),
               ('Udea',200,300),('Ulic',300,300)]
        specs += [(code,150+(i%5)*90,-150-(i//5)*100) for i,code in enumerate(['uaco']*2+['ugho']*2+['ucry']*5+['uobs'])]
        for code,dx,dy in specs:
            if not dev.spawn(code,x+dx,y+dy):raise RuntimeError('Spawn failed: '+code)
        zigs=[]
        for dy in (-300,0,300):
            z=dev.spawn('uzig',x-450,y+dy)
            if not z:raise RuntimeError('Ziggurat fixture failed')
            zigs.append(z);dev.jass.SetUnitState(z.jass_handle,dev.jass.ConvertUnitState(0),275)
        time.sleep(.3);g.snapshot(max_age=0)
        report['initial_resources']=g.resources()
        report['initial_zigs']=[dict(handle=b.handle,hp=b.hp,hp_max=b.hp_max,production_kind=g.production(b).kind if g.production(b) else None) for b in g.my_buildings({'uzig'})]
        if g.resources()['food_used']!=39 or g.resources()['food_cap']!=40:raise RuntimeError('Unexpected fixture population')
        if len(report['initial_zigs'])!=3 or any(b['production_kind'] is not None or b['hp']>=b['hp_max'] for b in report['initial_zigs']):raise RuntimeError('Fixture must start with three damaged completed towers')
        e=Economy(log);e.opening_started=True;e.opening_complete=True;e.opening_rod_allowed=True
        e.scout=(-1,0) # Match has already assigned/lost its sixth scouting acolyte.
        report['samples']=[];last=-100
        while time.monotonic()<deadline:
            g.snapshot(max_age=0);now=g.clock()
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
            e.tick(g,now)
            if now-last>=3:
                last=now;res=g.resources();buildings=g.my_buildings({'uzig'})
                report['samples'].append(dict(clock=now,food_used=res['food_used'],food_cap=res['food_cap'],zigs=len(buildings),construction=sum(bool(g.production(b) and g.production(b).kind=='construction') for b in buildings)))
                if len(buildings)>=4 and res['food_cap']>=50:
                    report.update(passed=True,final_resources=res,final_clock=now);break
            time.sleep(.12)
        if not report['passed']:report['error']='120-second wall deadline without actual population increase'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        try:session.stop()
        except Exception as exc:report['cleanup_error']=repr(exc);report['passed']=False
        report['owned_processes_closed']=not any(Session.matches(p) for p in report.get('processes',[]))
        (ROOT/'artifacts/p1-supply-damage-fixture-0.1.33.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'events','samples','source_hashes'}},ensure_ascii=False,indent=2),flush=True)
    return report['passed']

if __name__=='__main__':raise SystemExit(0 if run() else 1)
