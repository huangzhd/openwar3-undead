"""Bounded OpenWar3AI fixture. Dev setup/audit never supplies policy observations."""
import hashlib,json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.policy import Action
from undead.nc_combo import damage

def run():
    start=time.monotonic();session=Session(400,2,4);dev=None
    report=dict(version='0.1.38-dev',rules_version='0.1.38',fixture=True,normal_match=False,passed=False,events=[],cases=[])
    files=[ROOT/'probe_nc_combo.py',ROOT/'session.py',ROOT/'bot.py',ROOT/'run_match.py',*sorted((ROOT/'undead').glob('*.py'))]
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    def check():
        if time.monotonic()-start>150:raise TimeoutError('150 wall second fixture limit')
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
    def log(event,**kw):report['events'].append(dict(event=event,**kw))
    try:
        g=session.start();report['owned_processes']=list(session.owned)
        report['verified_opponent']=session.settings['verified_opponent'];dev=Game(pid=g.pid,fair=False)
        dev.jass.PauseCompAI(dev.jass.Player(1-g.me()),True)
        dev.jass.SetFloatGameState(dev.jass.ConvertFGameState(2),12.)
        dev.jass.SetTimeOfDayScale(0.)
        home=g.my_buildings({'unpl'})[0];direction=1 if home.x<0 else -1
        x,y=home.x+direction*800,home.y
        dk=dev.spawn('Udea',x,y);lich=dev.spawn('Ulic',x,y+80)
        if not dk or not lich:raise RuntimeError('Own hero setup failed')
        handles=(dk.handle,lich.handle);jhandles=(dk.jass_handle,lich.jass_handle)
        for j in jhandles:
            dev.jass.SetUnitAcquireRange(j,0.)
            if not dev.jass.UnitRemoveAbility(j,'Aatk'):raise RuntimeError('Unable to remove fixture weapon attacks')
        time.sleep(.2);g.snapshot(max_age=0)
        if not g.learn(g.unit(dk.handle),'AUdc') or not g.learn(g.unit(lich.handle),'AUfn'):raise RuntimeError('Learn rejected')
        def state(j,hp=None,mana=None):
            if hp is not None:dev.jass.SetUnitState(j,dev.jass.ConvertUnitState(0),float(hp))
            if mana is not None:dev.jass.SetUnitState(j,dev.jass.ConvertUnitState(2),float(mana))
        def reset():
            for j in jhandles:
                dev.jass.UnitResetCooldown(j);state(j,hp=600,mana=300)
            time.sleep(.15);g.snapshot(max_age=0)
            for h in handles:g.hold(g.unit(h))
        def spawn(code='Obla',hp=500,bracers=False):
            e=dev.spawn(code,x+direction*400,y,player=1-g.me())
            if not e:raise RuntimeError('Enemy hero setup failed')
            dev.jass.PauseUnit(e.jass_handle,True)
            if bracers:dev.jass.UnitAddItemById(e.jass_handle,'brac')
            state(e.jass_handle,hp=hp)
            time.sleep(.15);g.snapshot(max_age=0)
            if not any(u.handle==e.handle for u in g.enemies()):raise RuntimeError('Fixture target not visible')
            return e
        def sample(e):
            g.snapshot(max_age=0);u=g.unit(e.handle)
            return dict(clock=g.clock(),hp=u.hp if u else None,
                        engine_life=dev.jass.GetWidgetLife(e.jass_handle),
                        heroes=[dict(type=g.unit(h).type,hp=g.unit(h).hp,mana=g.unit(h).mana,
                                     cooldown=g.cooldown(g.unit(h),a)) for h,a in zip(handles,('AUdc','AUfn'))])
        def settle(e,bot=None):
            started=g.clock();rows=[];end=time.monotonic()+5
            while time.monotonic()<end:
                check();row=sample(e);rows.append(row)
                if bot:bot.nc_combo.observe(g,g.clock())
                if g.clock()-started>1:
                    for h in handles:g.hold(g.unit(h))
                if g.clock()-started>=3:break
                time.sleep(.08)
            return rows
        # Calibrate each spell without weapon attacks, against an isolated paused visible hero.
        for handle,spell,raw,bracers in ((dk.handle,'deathcoil',100,False),(lich.handle,'frostnova',150,False),
                                        (dk.handle,'deathcoil',100,True),(lich.handle,'frostnova',150,True)):
            reset();e=spawn(bracers=bracers);before=sample(e)
            accepted=bool(g.cast(g.unit(handle),spell,target=g.unit(e.handle)))
            rows=settle(e);loss=before['engine_life']-rows[-1]['engine_life']
            report['cases'].append(dict(name=spell+('_bracers' if bracers else '')+'_damage',accepted=accepted,before=before,samples=rows,
                                        target_abilities=g.abilities(g.unit(e.handle)),target_inventory=g.inventory(g.unit(e.handle)),
                                        actual_loss=loss,raw_damage=raw,factor=loss/raw,
                                        passed=accepted and abs(loss-raw*.7*(.67 if bracers else 1))<1.5))
            dev.jass.RemoveUnit(e.jass_handle)
        for name,code,hp,critical,bracers,expected in (
            ('nc_kill','Obla',160,False,False,'kill'),
            ('nc_bracers_kill','Obla',110,False,True,'kill'),
            ('critical_hero_first','Obla',160,True,False,'heal'),
            ('undead_excluded','Ulic',160,False,False,'preserve'),
            ('bracers_not_lethal','Obla',160,False,True,'preserve'),
        ):
            reset();e=spawn(code,hp,bracers)
            if critical:state(lich.jass_handle,hp=80);time.sleep(.15);g.snapshot(max_age=0)
            b=Controller(g,log,2);b.action=Action.ATTACK
            before=sample(e);event_start=len(report['events'])
            inputs=[dict(type=u.type,hp=u.hp,owner=u.owner,x=u.x,y=u.y,hero=u.is_hero,detail=u.has_detail,
                         abilities=g.abilities(u),buffs=g.buffs(u)) for u in [g.unit(h) for h in handles]+g.enemies()]
            current=[g.unit(h) for h in handles];target=g.unit(e.handle)
            if not target or not target.has_detail or any(g.dist(u,target)>=600 for u in current):
                raise RuntimeError('Fixture target must have detail and a safe margin inside combat range')
            b.combat_spells(current,g.enemies(),g.clock())
            rows=settle(e,b);after=rows[-1]
            ev=report['events'][event_start:];attempts=[r for r in ev if r['event']=='nc_attempt']
            if expected=='kill':
                passed=(bool(attempts) and attempts[0]['accepted'] and after['engine_life']<=.405 and
                        all(u['cooldown'] and u['cooldown']>0 for u in after['heroes']))
            elif expected=='heal':
                passed=(not attempts and after['heroes'][1]['hp']>before['heroes'][1]['hp']+150 and
                        after['heroes'][1]['mana']>=before['heroes'][1]['mana'] and after['engine_life']>0)
            else:
                passed=not attempts and all(a['mana']>=z['mana'] for a,z in zip(after['heroes'],before['heroes']))
            report['cases'].append(dict(name=name,before=before,samples=rows,events=ev,inputs=inputs,
                                        target_abilities=g.abilities(g.unit(e.handle)),target_inventory=g.inventory(g.unit(e.handle)),passed=bool(passed)))
            dev.jass.RemoveUnit(e.jass_handle)
        report['predicted_level_one']=damage(1,1)
        report['passed']=all(c['passed'] for c in report['cases'])
        report['limitations']=['Paused, spawned targets and reset mana/cooldowns; not a natural match.',
            'Only fair g supplies combat_spells observations; dev engine life is fixture audit only.',
            'Own heroes Aatk removed to isolate spell damage; target regen remains within measurement tolerance. No map-search or natural home-defense validation.']
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop()
        report['owned_processes_closed']=not any(Session.matches(r) for r in report.get('owned_processes',[]))
        report['wall_seconds']=round(time.monotonic()-start,2)
        (ROOT/'artifacts/p1-nc-fixture-0.1.38.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],wall_seconds=report['wall_seconds'],
                         closed=report['owned_processes_closed'],error=report.get('error'),
                         cases=[{k:v for k,v in c.items() if k in ('name','passed','actual_loss','factor')} for c in report['cases']]),ensure_ascii=False,indent=2))
    return report['passed'] and report['owned_processes_closed']

if __name__=='__main__':raise SystemExit(0 if run() else 1)
