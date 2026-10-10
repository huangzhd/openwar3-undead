"""Finite API-only fixtures; not a normal match or a historical replay."""
import hashlib,json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.structures import is_structure
from undead.policy import Action

def run():
    report=dict(version='0.1.28-dev',fixture=True,counts_as_match=False,passed=False,events=[],aggro_samples=[],attack_samples=[])
    report['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'undead').glob('*.py'))}
    session=Session(400);dev=None;created=[]
    def log(ev,**kw):report['events'].append(dict(event=ev,**kw))
    def spawn(code,x,y,player=None):
        u=dev.spawn(code,x,y,player=player)
        if u is None:raise RuntimeError('Fixture spawn failed: '+code)
        created.append(u);return u
    def check_stop():
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False);home=g.my_buildings({'unpl'})[0]
        bot=Controller(g,log);mp=g.map()
        camp=min((c for c in bot.creeping.catalog if c['kind']=='gnoll'),key=lambda c:g.dist((c['x'],c['y']),home))
        report['camp']=camp['id']
        dk=spawn('Udea',camp['x']+230,camp['y']);g.hold(dk)
        start=g.clock();deadline=time.monotonic()+25;sks=[];started=False
        while time.monotonic()<deadline and g.clock()-start<45:
            check_stop();snap=g.snapshot(max_age=0);now=snap.clock;victim=g.unit(dk.handle)
            if not victim or not victim.alive:break
            creeps=[e for e in g.creeps() if g.dist(e,(camp['x'],camp['y']))<1000]
            targeting=[e for e in creeps if (t:=g.current_target(e)) and t.handle==dk.handle]
            if not started and targeting:
                sks=[spawn('uske',victim.x+60,victim.y+offset) for offset in [-70,70]]
                started=True
                report['aggro_initial']=dict(clock=now,victim=dk.handle,hp=victim.hp,targets=[dict(creep=e.handle,target=g.current_target(e).handle) for e in targeting])
            elif not started and creeps:g.attack(victim,min(creeps,key=lambda e:g.dist(e,victim)))
            army=[u for h in [dk.handle,*[s.handle for s in sks]] if (u:=g.unit(h)) and u.alive]
            if started:
                bot.creep_aggro.step(g,army,creeps,now,True)
                bot.fight(army,creeps,now)
                report['aggro_samples'].append(dict(clock=now,army=[dict(handle=u.handle,type=u.type,hp=u.hp,target=(t.handle if (t:=g.current_target(u)) else None)) for u in army],
                    creeps=[dict(handle=e.handle,hp=e.hp,target=(t.handle if (t:=g.current_target(e)) else None)) for e in creeps]))
                if any(e['event']=='creep_aggro_confirmed' for e in report['events']):break
            time.sleep(.1)
        report['aggro_passed']=any(e['event']=='creep_aggro_confirmed' for e in report['events'])
        print(json.dumps(dict(phase='aggro',passed=report['aggro_passed'],events=[e for e in report['events'] if e['event'].startswith('creep_aggro')]),ensure_ascii=False),flush=True)
        for u in created:dev.jass.RemoveUnit(u.jass_handle)
        created.clear()

        # Synthetic enemy tree is placed in a walkable area near our own base.
        # Only fair snapshots drive the controller after this explicit preparation.
        candidates=[(home.x+dx,home.y+dy) for dx,dy in [(1300,-1200),(1600,0),(0,-1700),(-1300,-1200)]]
        point=next(p for p in candidates if all(mp.walkable(p[0]+dx,p[1]+dy) for dx,dy in [(0,0),(250,0),(-250,0),(0,250),(0,-250)]) and g.path_distance((home.x,home.y+500),p) is not None)
        tree=spawn('etol',*point,player=1)
        scout=spawn('uske',point[0]+300,point[1]+100)
        bot=Controller(g,log);bot.action=Action.ATTACK;bot.attack_committed=True;bot.home=home
        bot.enemy_main=(4672,2944);bot.main_searched=True
        snap=g.snapshot(max_age=0);bot.memory.update(snap.units,snap.clock,g.me(),is_structure)
        if tree.handle not in bot.memory.units:raise RuntimeError('Fixture tree was not observed fairly')
        first=snap.clock;report['tree_first_seen']=first
        g.move(scout,home.x,home.y+600)
        deadline=time.monotonic()+42
        while time.monotonic()<deadline and g.clock()-first<130:
            check_stop();snap=g.snapshot(max_age=0);bot.memory.update(snap.units,snap.clock,g.me(),is_structure);time.sleep(.2)
        report['tree_age']=g.clock()-first
        report['tree_retained']=tree.handle in bot.memory.units
        report['tree_visible_before_march']=g.unit(tree.handle) is not None
        army=[spawn('ucry',home.x+80*i,home.y+500) for i in range(5)]
        handles={u.handle for u in army};deadline=time.monotonic()+40;start=g.clock();initial_hp=tree.hp;initial_distance=None
        while time.monotonic()<deadline and g.clock()-start<110:
            check_stop();snap=g.snapshot(max_age=0);now=snap.clock
            army=[u for u in g.my_units() if u.handle in handles and u.alive]
            if not army:break
            anchor=min(army,key=lambda u:sum(g.dist(u,v) for v in army));center=(anchor.x,anchor.y)
            if initial_distance is None:initial_distance=g.dist(center,point)
            bot.memory.update(snap.units,now,g.me(),is_structure)
            foes=g.enemies();bot.battle_enemies=[e for e in foes+g.creeps() if g.dist(e,center)<600]
            bot.advance_attack(army,foes,center,now)
            visible=g.unit(tree.handle)
            report['attack_samples'].append(dict(clock=now,distance=g.dist(center,point),goal=bot.attack_goal,
                target=bot.attack_target,tree_hp=visible.hp if visible else None,
                army=[dict(handle=u.handle,x=u.x,y=u.y,target=(t.handle if (t:=g.current_target(u)) else None)) for u in army]))
            if visible and visible.hp<initial_hp-100:
                report['attack_passed']=report['tree_retained'] and report['tree_age']>120 and initial_distance-g.dist(center,point)>800
                break
            time.sleep(.2)
        report['passed']=report['aggro_passed'] and report.get('attack_passed',False)
        report['limitations']=['Synthetic own army and enemy tree; no normal economy or result verification.','Public-map natural creeps were used for aggro; no hidden enemy state enters policy.','Main-area-cleared state is fixture setup, not evidence of a normally destroyed main base.']
    except Exception as exc:report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-expansion-aggro-fixture-0.1.28.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'events','aggro_samples','attack_samples','source_hashes'}},ensure_ascii=False),flush=True)
    return report['passed']

if __name__=='__main__':raise SystemExit(0 if run() else 1)
