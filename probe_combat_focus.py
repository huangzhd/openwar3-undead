"""Bounded real-engine combat targeting fixture; strategy uses only fair API."""
import hashlib,json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.targeting import unit_stats

def run():
    start=time.monotonic();session=Session(400,4,4);dev=None
    report=dict(version='0.1.40-dev',rules_version='0.1.40',fixture=True,normal_match=False,passed=False,cases=[],events=[])
    files=[ROOT/'probe_combat_focus.py',ROOT/'session.py',ROOT/'run_match.py',*sorted((ROOT/'undead').glob('*.py'))]
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        for code in ('ucry','ebal','Ekee','ogru'):unit_stats(code)
        g=session.start();report['owned_processes']=list(session.owned);report['verified_opponent']=session.settings['verified_opponent']
        dev=Game(pid=g.pid,fair=False);dev.jass.PauseCompAI(dev.jass.Player(1-g.me()),True)
        home=g.my_buildings({'unpl'})[0];x=home.x+(800 if home.x<0 else -800);y=home.y
        army=[dev.spawn('ucry',x,y),dev.spawn('ucry',x,y+60)]
        if not all(army):raise RuntimeError('Own fixture spawn failed')
        def enemy(code,dx,dy=0):
            u=dev.spawn(code,x+dx,y+dy,player=1-g.me())
            if not u:raise RuntimeError('Enemy fixture spawn failed')
            dev.jass.PauseUnit(u.jass_handle,True)
            return u
        siege=enemy('ebal',300,0);hero=enemy('Ekee',350,100);foot=enemy('ogru',400,-100)
        def bot():
            b=Controller(g,lambda e,**kw:report['events'].append(dict(event=e,**kw)),4);b.home=home
            return b
        b=bot()
        def state():
            g.snapshot(max_age=0)
            a=[g.unit(u.handle) for u in army];a=[u for u in a if u and u.alive]
            foes=[u for u in g.enemies() if u.handle in {hero.handle,siege.handle,foot.handle}]
            return a,foes
        def sample():
            a,foes=state()
            return dict(clock=g.clock(),own=[dict(handle=u.handle,x=u.x,y=u.y,target=g.current_target(u).handle if g.current_target(u) else None) for u in a],
                        enemies=[dict(handle=u.handle,type=u.type,hp=u.hp) for u in foes])
        def tick_for(seconds):
            rows=[];beg=g.clock()
            while g.clock()-beg<seconds:
                if time.monotonic()-start>85:raise TimeoutError('85 wall second fixture budget')
                if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
                a,foes=state();b.fight(a,foes,g.clock());rows.append(sample());time.sleep(.15)
            return rows
        def life(u):return dev.jass.GetWidgetLife(u.jass_handle)
        def targeting(rows,u):return any(any(a['target']==u.handle for a in r['own']) for r in rows)
        before=life(hero);rows=tick_for(2.5)
        report['cases'].append(dict(name='hero_pressure_before_siege',passed=targeting(rows,hero) and life(hero)<before-1,
                                    before=before,after=life(hero),samples=rows))
        before=life(hero);rows=tick_for(6)
        report['cases'].append(dict(name='pressure_continues_past_three_seconds',passed=targeting(rows,hero) and life(hero)<before-1 and not targeting(rows,siege),
                                    before=before,after=life(hero),samples=rows))
        dev.jass.SetUnitPosition(hero.jass_handle,x+620,y+100)
        before=life(siege);rows=tick_for(6)
        report['cases'].append(dict(name='range_exit_switch_to_siege',passed=targeting(rows,siege) and life(siege)<before-1,
                                    before=before,after=life(siege),samples=rows))
        dev.jass.RemoveUnit(siege.jass_handle)
        for u in army:g.hold(g.unit(u.handle))
        dev.jass.SetUnitPosition(hero.jass_handle,x+350,y+100)
        dev.jass.SetUnitState(hero.jass_handle,dev.jass.ConvertUnitState(0),500.)
        b=bot();before=life(hero);rows=tick_for(2)
        report['cases'].append(dict(name='hero_pressure',passed=targeting(rows,hero) and life(hero)<before-1,
                                    before=before,after=life(hero),samples=rows))
        before=life(hero);rows=tick_for(6)
        report['cases'].append(dict(name='sustained_pressure_without_siege',passed=targeting(rows,hero) and life(hero)<before-1 and not targeting(rows,foot),
                                    before=before,after=life(hero),samples=rows))
        b=bot()
        for u in army:g.hold(g.unit(u.handle))
        rows=tick_for(1.5);origin=sample();dev.jass.SetUnitPosition(hero.jass_handle,x+620,y+100)
        rows=tick_for(2.5)
        positions={tuple(u['handle']):(u['x'],u['y']) for u in origin['own']}
        movement=max((g.dist((a['x'],a['y']),positions[tuple(a['handle'])]) for r in rows for a in r['own']),default=9999)
        report['cases'].append(dict(name='retreat_switch_no_chase',passed=targeting(rows,foot) and movement<100,
                                    max_displacement_after_retreat=movement,origin=origin,samples=rows))
        # The existing two-spell finisher still wins over a visible siege unit.
        dev.jass.SetUnitPosition(hero.jass_handle,x+350,y+100)
        dev.jass.SetUnitState(hero.jass_handle,dev.jass.ConvertUnitState(0),150.)
        siege=enemy('ebal',300)
        dk=dev.spawn('Udea',x,y-50);lich=dev.spawn('Ulic',x,y-100)
        for h in (dk,lich):
            dev.jass.UnitRemoveAbility(h.jass_handle,'Aatk')
            dev.jass.SetUnitState(h.jass_handle,dev.jass.ConvertUnitState(2),300.)
        for u in army:g.hold(g.unit(u.handle));dev.jass.PauseUnit(u.jass_handle,True)
        time.sleep(.2);g.snapshot(max_age=0);g.learn(g.unit(dk.handle),'AUdc');g.learn(g.unit(lich.handle),'AUfn')
        time.sleep(.2);g.snapshot(max_age=0);b=bot()
        b.combat_spells([g.unit(dk.handle),g.unit(lich.handle)],g.enemies(),g.clock())
        time.sleep(.85);g.snapshot(max_age=0)
        hp=life(hero);cd=[g.cooldown(g.unit(u.handle),code) for u,code in ((dk,'AUdc'),(lich,'AUfn'))]
        report['cases'].append(dict(name='nc_over_siege',passed=hp<=0 and all(c is not None and c>0 for c in cd),engine_hero_life=hp,cooldowns=cd))
        # Single-spell finishers must leave the other offensive spell unused.
        for name,hp,dk_mana,bracers,expected in (
            ('coil_only',65,300,False,'AUdc'),
            ('nova_only_without_coil_mana',95,0,False,'AUfn'),
            ('nova_only_with_bracers',65,0,True,'AUfn')):
            hero=enemy('Ekee',350,100)
            if bracers:dev.jass.UnitAddItemById(hero.jass_handle,'brac')
            dev.jass.SetUnitState(hero.jass_handle,dev.jass.ConvertUnitState(0),float(hp))
            for h,mana in ((dk,dk_mana),(lich,300)):
                dev.jass.UnitResetCooldown(h.jass_handle)
                dev.jass.SetUnitState(h.jass_handle,dev.jass.ConvertUnitState(2),float(mana))
            time.sleep(.2);g.snapshot(max_age=0);b=bot()
            actors=[g.unit(dk.handle),g.unit(lich.handle)]
            b.combat_spells(actors,g.enemies(),g.clock())
            b.fight(actors,g.enemies(),g.clock())
            time.sleep(.85);g.snapshot(max_age=0)
            life_after=life(hero);cds=[g.cooldown(g.unit(u.handle),code) for u,code in ((dk,'AUdc'),(lich,'AUfn'))]
            used=0 if expected=='AUdc' else 1
            report['cases'].append(dict(name=name,passed=life_after<=0 and cds[used]>0 and cds[1-used]==0,
                                        engine_hero_life=life_after,cooldowns=cds))
            dev.jass.RemoveUnit(hero.jass_handle)
        report['passed']=all(c['passed'] for c in report['cases'])
    except Exception as exc:report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['wall_seconds']=round(time.monotonic()-start,2)
        report['owned_processes_closed']=not any(Session.matches(r) for r in report.get('owned_processes',[]))
        report['limitations']=['Fixture targets spawned and AI/targets paused; retreat position injected. Not a natural complete match.',
                               'Static public weapon ranges are conservative; no opponent hidden upgrades are queried.']
        (ROOT/'artifacts/p1-combat-focus-0.1.40.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in {'source_hashes','events','cases'}},ensure_ascii=False))
        print(json.dumps([dict(name=c['name'],passed=c['passed']) for c in report['cases']]))
    return report['passed'] and report['owned_processes_closed']
if __name__=='__main__':raise SystemExit(0 if run() else 1)
