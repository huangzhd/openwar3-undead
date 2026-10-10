"""Isolated real-engine home-defense regression, never a normal result."""
import hashlib,json,time,traceback
from pathlib import Path
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from openwar3.screenshot import png_bytes
from undead.controller import Controller
from undead.debug_console import DebugConsole


def run():
    start=time.monotonic();session=Session(400,2,4);dev=None;console=None
    report=dict(version='0.1.37-dev',rules_version='0.1.37',fixture=True,normal_match=False,passed=False,events=[],samples=[])
    files=[ROOT/'session.py',ROOT/'run_match.py',ROOT/'bot.py',ROOT/'probe_home_defense.py',*sorted((ROOT/'undead').glob('*.py'))]
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    def log(event,**kw):report['events'].append(dict(event=event,**kw))
    try:
        g=session.start();report['owned_processes']=list(session.owned);report['verified_opponent']=session.settings['verified_opponent']
        dev=Game(pid=g.pid,fair=False);home=g.my_buildings({'unpl'})[0];home_handle=dev.jass.handle_of(home)
        x,y=home.x,home.y;direction=1 if x<0 else -1
        dev.jass.PauseCompAI(dev.jass.Player(1-g.me()),True)
        dev.jass.SetFloatGameState(dev.jass.ConvertFGameState(2),12.0)
        dev.jass.SetTimeOfDayScale(0.0)
        for i in range(2):
            if not dev.spawn('ugho',x+direction*(300+i*70),y-200):raise RuntimeError('Ghoul spawn failed')
        time.sleep(.2);g.snapshot(max_age=0)
        team=g.units('me',{'ugho'});report['team']=[u.handle for u in team]
        if len(team)!=3:raise RuntimeError('Need exactly three ghouls')
        for i,u in enumerate(team):dev.jass.SetUnitPosition(dev.jass.handle_of(u),x+direction*(300+i*65),y-100)
        tree=g.trees(x,y)[0]
        for u in team:g.gather(u,tree)
        bot=Controller(g,log,2);console=DebugConsole(g,log)
        def tick():
            if time.monotonic()-start>120:raise TimeoutError('120 second fixture limit')
            s=g.snapshot(max_age=0);g.events();bot.tick();console.observe(s,bot)
            now=g.clock();current=g.units('me',{'ugho'});base=g.unit(home.handle)
            sample=dict(clock=now,home_hp=base.hp if base else None,lumber_gathered=g.resources()['lumber_gathered'],
                        ghouls=[dict(handle=u.handle,x=u.x,y=u.y,hp=u.hp,home_distance=g.dist(u,home),order=g.order_of(u)) for u in current],
                        active=sorted(bot.home_defense.active),returning=sorted(bot.home_defense.returning))
            report['samples'].append(sample);time.sleep(.15);return sample
        def enemy():
            e=dev.spawn('ocat',x+direction*1000,y-100,player=1-g.me())
            if not e:raise RuntimeError('Demolisher spawn failed')
            order=dev.jass.OrderId('attack')
            accepted=dev.jass.IssueTargetOrderById(e.jass_handle,order,home_handle)
            report.setdefault('setup_attack_orders',[]).append(dict(order=order,accepted=accepted))
            if not accepted:raise RuntimeError('Fixture enemy attack order rejected')
            return e
        e=enemy();initial_hp=e.hp;base_hp=home.hp;damage_deadline=time.monotonic()+10
        # Establish that the fixture siege unit actually threatens the base before defense starts.
        while time.monotonic()<damage_deadline:
            g.snapshot(max_age=0);base=g.unit(home.handle)
            if base and base.hp<base_hp-10:break
            time.sleep(.15)
        report['base_under_actual_siege']=bool(base and base.hp<base_hp-10)
        if not report['base_under_actual_siege']:raise RuntimeError('No actual siege damage on base')
        report['demolisher_damage_samples']=[];deadline=time.monotonic()+25;killed=False;shot=False
        while time.monotonic()<deadline:
            tick();unit=g.unit(e.handle)
            if unit:report['demolisher_damage_samples'].append(dict(clock=g.clock(),hp=unit.hp))
            if not shot:
                console.toggle();time.sleep(.15)
                data=png_bytes(g.pid,scale=1)
                if data:
                    path=ROOT/'artifacts/p1-home-defense-0.1.37-console.png';path.write_bytes(data);report['screenshot']=str(path)
                shot=True
            if unit is None or unit.hp<=0:killed=True;break
        report['demolisher_killed']=killed
        report['demolisher_hp_decreased']=any(s['hp']<initial_hp-10 for s in report['demolisher_damage_samples'])
        if not killed:raise RuntimeError('Demolisher not eliminated within fixture deadline')
        lumber=g.resources()['lumber_gathered'];deadline=time.monotonic()+18
        while time.monotonic()<deadline:
            tick()
            if not bot.home_defense.reserved and g.resources()['lumber_gathered']>lumber:break
        report['harvest_after_kill']=not bot.home_defense.reserved and g.resources()['lumber_gathered']>lumber
        # Spawn another live siege threat, then move it outside the leash with the dev setup client.
        e2=enemy();deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            tick()
            if len(bot.home_defense.active)==3:break
        if len(bot.home_defense.active)!=3:raise RuntimeError('Second harassment not engaged')
        for _ in range(3):tick()
        dev.jass.SetUnitPosition(e2.jass_handle,x+direction*2800,y-100)
        dev.jass.IssuePointOrderById(e2.jass_handle,dev.jass.OrderId('move'),x+direction*3000,y-100)
        report['retreat_injected_at']=g.clock();lumber=g.resources()['lumber_gathered'];deadline=time.monotonic()+22
        while time.monotonic()<deadline:
            tick()
            if not bot.home_defense.reserved and g.resources()['lumber_gathered']>lumber:break
        report['harvest_after_retreat']=not bot.home_defense.reserved and g.resources()['lumber_gathered']>lumber
        after=[s for s in report['samples'] if s['clock']>=report['retreat_injected_at']]
        report['max_ghoul_distance_after_retreat']=max(u['home_distance'] for s in after for u in s['ghouls'])
        report['base_survived']=bool(g.unit(home.handle) and g.unit(home.handle).hp>0)
        report['all_three_survived']=len(g.units('me',{'ugho'}))==3
        report['passed']=all(report[k] for k in ['base_under_actual_siege','demolisher_killed','demolisher_hp_decreased','harvest_after_kill','harvest_after_retreat','base_survived','all_three_survived']) and report['max_ghoul_distance_after_retreat']<=1650
        report['limitations']=['Isolated dev setup; enemy AI paused; daylight fixed; second enemy moved outside leash, not natural retreat.','Only policy uses fair game observations; dev does not supply hidden targets.','Actual lumber_gathered increase confirms harvesting; command receipts alone do not.','No full normal match on this version.']
    except Exception as exc:report['error']=repr(exc);traceback.print_exc()
    finally:
        if console:console.close()
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not any(Session.matches(r) for r in report.get('owned_processes',[]))
        report['wall_seconds']=round(time.monotonic()-start,2)
        (ROOT/'artifacts/p1-home-defense-fixture-0.1.37.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('events','samples','source_hashes')},ensure_ascii=False,indent=2))
    return report['passed'] and report['owned_processes_closed']

if __name__=='__main__':raise SystemExit(0 if run() else 1)
