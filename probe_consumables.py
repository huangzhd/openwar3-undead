"""Bounded isolated API fixture; setup uses dev client, policy uses fair client."""
import hashlib,json,time,traceback,sys
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.consumables import Consumables,ScrollSupply,ITEMS
from undead.controller import Controller
from undead.equipment import Equipment

def run(effects_only=False):
    report=dict(version='0.1.30-dev',rules_version='0.1.30',fixture=True,counts_as_match=False,effects_only=effects_only,passed=False,events=[],cases=[])
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'undead').glob('*.py'))}
    report['probe_hash']=hashlib.sha256(open(__file__,'rb').read()).hexdigest()
    session=Session(800);dev=None;deadline=time.monotonic()+200
    def check():
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
        if time.monotonic()>deadline:raise TimeoutError('200 second fixture limit')
    def log(event,**kw):
        row=dict(event=event,**kw);report['events'].append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        report['owned_processes']=list(session.owned)
        home=g.my_buildings({'unpl'})[0];x,y=home.x,home.y
        units=[]
        for code,dx,dy in [('unp2',600,0),('utom',600,-600),('Udea',400,-600),('Ulic',400,-400),('Nbrn',400,-500)]:
            u=dev.spawn(code,x+dx,y+dy)
            if not u:raise RuntimeError('Spawn failed '+code)
            units.append(u)
        shop=units[1];dk,lich,dark=units[2:]
        for i,code in enumerate(['ucry']*6+['uobs']*2+['uaco']*2+['ugho']*2):
            units.append(dev.spawn(code,x+200+(i%4)*60,y-600-(i//4)*60))
        player=dev.jass.Player(g.me())
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(1),10000)
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(2),10000)
        handles=[u.handle for u in units if u and u.type in {'Udea','Ulic','Nbrn','ucry','uobs'}]
        def army():return [u for h in handles if (u:=g.unit(h)) and u.alive]
        jass_handles={u.handle:u.jass_handle for u in units if u}
        def state(u,hp=None,mana=None):
            if hp is not None:dev.jass.SetUnitState(jass_handles[u.handle],dev.jass.ConvertUnitState(0),float(hp))
            if mana is not None:dev.jass.SetUnitState(jass_handles[u.handle],dev.jass.ConvertUnitState(2),float(mana))
        for u in army():g.hold(u)
        c=Consumables(log);lock={};controller=Controller(g,log);controller.home=home;controller.cast_until=lock
        g.learn(dk,'AUdc');time.sleep(.2)
        def effect_case(code,hero,hp=None,mana=None,foes=(),add_item=True):
            check();state(hero,hp,mana)
            if add_item:dev.jass.UnitAddItemById(hero.jass_handle,code)
            time.sleep(.2);g.snapshot(max_age=0)
            report['cases'].append(dict(code=code,inventory=g.inventory(g.unit(hero.handle)),
                abilities=g.abilities(g.unit(hero.handle)),before=[dict(type=u.type,handle=u.handle,hp=u.hp,mana=u.mana) for u in army()],passed=False))
            if code=='sror':
                stop_clock=g.clock()+3;end=time.monotonic()+4
                while g.clock()<stop_clock and time.monotonic()<end:
                    check();g.snapshot(max_age=0)
                    c.tick(g,army(),foes,g.clock(),lock,attacking=False);time.sleep(.1)
                report['roar_saved_outside_attack']='sror' in (g.inventory(g.unit(hero.handle)) or []) and 'Broa' not in g.buffs(g.unit(hero.handle))
                if not report['roar_saved_outside_attack']:raise RuntimeError('Roar used outside attack phase')
            start=len(report['events']);end=time.monotonic()+15
            while time.monotonic()<end:
                check();g.snapshot(max_age=0);c.tick(g,army(),foes,g.clock(),lock,coil_needed=controller.coil_needed(g.unit(dk.handle)),attacking=code=='sror')
                found=[e for e in report['events'][start:] if e['event']=='consumable_effect_observed' and e['code']==code]
                if found:
                    report['cases'][-1].update(passed=True,evidence=found[-1]);return
                time.sleep(.12)
            raise RuntimeError('Actual effect not observed: '+code)
        effect_case('pghe',dk,hp=100)
        # Visible hostile fixture near Lich establishes genuine threat (no hidden input).
        enemy=dev.spawn('hfoo',lich.x+150,lich.y,player=1-g.me());time.sleep(.2)
        if not enemy:raise RuntimeError('Threat fixture failed')
        dev.jass.PauseUnit(enemy.jass_handle,True)
        effect_case('pnvu',lich,hp=120,foes=[e for e in g.enemies() if e.handle==enemy.handle])
        dev.jass.RemoveUnit(enemy.jass_handle)
        for u in army():state(u,hp=u.hp_max,mana=u.mana_max)
        near=[u for u in army() if u.type=='ucry' and g.dist(u,dark)<500][:2]
        if len(near)!=2:raise RuntimeError('Group fixture placement invalid')
        for u in near:state(u,hp=150)
        statue=next(u for u in army() if u.type=='uobs');state(statue,hp=100)
        effect_case('shea',dark)
        if len(report['cases'][-1]['evidence']['gains'])<2:raise RuntimeError('Need two actual group healing recipients')
        report['statue_after_group_heal']=g.unit(statue.handle).hp
        if report['statue_after_group_heal']>140:raise RuntimeError('Unexpected mechanical target healing')
        for u in army():state(u,hp=u.hp_max,mana=u.mana_max)
        state(dk,mana=0);dev.jass.UnitAddItemById(lich.jass_handle,'pgma');time.sleep(.2)
        equipment=Equipment(log);end=time.monotonic()+8;start=len(report['events'])
        while time.monotonic()<end:
            check();g.snapshot(max_age=0);equipment.tick(g,army(),[],g.clock(),lock)
            if any(e['event']=='equipment_transfer_confirmed' and e.get('code')=='pgma' for e in report['events'][start:]):break
            time.sleep(.1)
        else:raise RuntimeError('Blue potion handoff to DK not confirmed')
        start_clock=g.clock();end=time.monotonic()+4
        while g.clock()-start_clock<4 and time.monotonic()<end:
            check();g.snapshot(max_age=0);c.tick(g,army(),[],g.clock(),lock,coil_needed=controller.coil_needed(g.unit(dk.handle)));time.sleep(.1)
        report['blue_saved_without_coil_target']='pgma' in (g.inventory(g.unit(dk.handle)) or []) and g.unit(dk.handle).mana<20
        if not report['blue_saved_without_coil_target']:raise RuntimeError('Blue potion wasted without Coil need')
        state(near[0],hp=100)
        effect_case('pgma',dk,mana=0,add_item=False)
        start=len(report['events']);end=time.monotonic()+8
        while time.monotonic()<end:
            check();g.snapshot(max_age=0);controller.heal_allies(army(),g.clock())
            if any(e['event']=='coil_heal_observed' for e in report['events'][start:]):break
            time.sleep(.1)
        else:raise RuntimeError('No actual Coil heal after drinking blue potion')
        report['blue_followed_by_coil_heal']=True
        for u in near:state(u,hp=100)
        state(lich,hp=200,mana=0)
        effect_case('sres',dark,mana=0)
        for u in army():state(u,hp=u.hp_max,mana=u.mana_max)
        enemy=dev.spawn('hfoo',dk.x+150,dk.y,player=1-g.me());time.sleep(.2)
        if not enemy:raise RuntimeError('Combat buff threat fixture failed')
        dev.jass.PauseUnit(enemy.jass_handle,True)
        visible_threat=[e for e in g.enemies() if e.handle==enemy.handle]
        effect_case('spro',dk,foes=visible_threat)
        effect_case('sror',dark,foes=visible_threat)
        dev.jass.RemoveUnit(enemy.jass_handle)
        if not effects_only:
            # Shop uses natural stock; no AddItemToStock or synthetic successful receipts.
            dev.jass.UnitAddItemById(lich.jass_handle,'ocor')
            supply=ScrollSupply(log)
            while g.clock()<450:
                check();g.snapshot(max_age=0);time.sleep(.2)
            report['purchase_start_resources']=g.resources()
            if g.resources()['food_used']<50:raise RuntimeError('Population setup below 50')
            # Already-near safe shop, single purchases and engine-chosen recipient handoffs.
            end=time.monotonic()+65
            while time.monotonic()<end:
                check();g.snapshot(max_age=0);heroes=[u for u in army() if u.is_hero]
                supply.tick(g,heroes,[g.unit(shop.handle)],g.clock(),0,lock,True)
                bags={u.type:g.inventory(u) for u in heroes}
                report['purchase_last_state']=dict(clock=g.clock(),bags=bags,distances={u.type:g.dist(u,g.unit(shop.handle)) for u in heroes})
                if all(bag.count('shea')==1 for bag in bags.values()):
                    report['purchase_final_inventory']=bags;report['purchase_final_resources']=g.resources();break
                time.sleep(.12)
            else:raise RuntimeError('Three distinct hero scroll inventories not confirmed')
        report['passed']=all(case['passed'] for case in report['cases'])
        report['limitations']=['Own units/items/resources were initialized using a separate dev client; policy observations and commands used fair Game API.',
            'Not a normal match; no win/loss credit. No synthetic shop stock was added.',
            'Purchasing fixture isolates distribution; core-budget and exact 49/50,499/500 boundaries are covered by behavioral tests.',
            'Not every consumable variant is individually live-tested.']
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/('artifacts/p1-consumables-effects-0.1.30.json' if effects_only else 'artifacts/p1-consumables-fixture-0.1.30.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'source_hashes','events','cases'}},ensure_ascii=False,indent=2),flush=True)
    return report['passed']
if __name__=='__main__':raise SystemExit(0 if run('--effects-only' in sys.argv) else 1)
