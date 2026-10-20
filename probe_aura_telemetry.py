"""Isolated engine experiment; setup mutations never enter a normal match.

Compare aura handoff with direct semantic casting while the ability list is
missing. The production Coil readiness guard is deliberately bypassed only in
the labelled direct-cast cases, never by changing the normal bot.
"""
import hashlib
import argparse
import json
import time
import traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game as SDKGame


def run(hero_level=1):
    stamp=time.strftime('%Y%m%d-%H%M%S')
    out=ROOT/'artifacts'/('aura-probe-'+stamp)
    out.mkdir()
    sources=[ROOT/'probe_aura_telemetry.py',ROOT/'session.py',ROOT/'bot.py',
             ROOT/'run_match.py',*sorted((ROOT/'undead').glob('*.py'))]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for p in sources:
        target=out/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(p.read_bytes())
    report=dict(version='0.1.157-dev',fixture=True,counts_as_match=False,hero_level=hero_level,
                source_hashes=hashes,cases=[],completed=False)
    session=Session(400,4,4,map_alias='TH');dev=None
    deadline=time.monotonic()+240
    def save():
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check():
        if time.monotonic()>deadline:raise TimeoutError('240 wall second fixture budget')
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('Stop requested')
    try:
        g=session.start(until=time.time()+100);dev=SDKGame(pid=g.pid,fair=False)
        report['settings']=session.settings
        dev.jass.PauseCompAI(dev.jass.Player(1-g.me()),True)
        home=g.my_buildings({'unpl'})[0];mp=g.map()
        origin=next(((home.x+dx,home.y+dy) for dx,dy in
                     [(700,-500),(700,500),(-700,-500),(-700,500)]
                     if all(mp.walkable(home.x+dx+sx,home.y+dy+sy)
                            for sx,sy in [(0,0),(100,0),(0,100),(250,0)])),None)
        if origin is None:raise RuntimeError('No walkable test area')

        def wait(seconds):
            until=g.clock()+seconds;wall=time.monotonic()+10
            while g.clock()<until:
                check()
                if time.monotonic()>wall:raise TimeoutError('Simulation clock stalled')
                time.sleep(.08);g.snapshot(max_age=0)

        def state(u,hp=None,mana=None):
            if hp is not None:dev.jass.SetUnitState(u.jass_handle,dev.jass.ConvertUnitState(0),float(hp))
            if mana is not None:dev.jass.SetUnitState(u.jass_handle,dev.jass.ConvertUnitState(2),float(mana))

        def fresh(u):
            found=g.unit(u.handle)
            if found is None:raise RuntimeError('Fixture unit disappeared')
            return found

        def sample(dk,third,target,enemy):
            g.snapshot(max_age=0)
            return dict(clock=g.clock(),heroes=[
                dict(type=fresh(u).type,handle=u.handle,hp=fresh(u).hp,mana=fresh(u).mana,
                     inventory=g.inventory(fresh(u)),abilities=g.abilities(fresh(u)))
                for u in (dk,third)],
                target_hp=fresh(target).hp,enemy_hp=fresh(enemy).hp,enemy_buffs=g.buffs(fresh(enemy)))

        def has(row,hero,code):
            return any(a['code']==code and a['level']>0 for a in row['heroes'][hero]['abilities'])

        def coil_case(case,dk,third,target,enemy,label,direct):
            # Only set target HP in setup. Do not reset cooldown or hero mana
            # after the missing-telemetry condition has been established.
            state(target,hp=80)
            wait(.6);before=sample(dk,third,target,enemy)
            call=SDKGame.cast if direct else type(g).cast
            receipt=call(g,fresh(dk),'deathcoil',target=fresh(target))
            samples=[]
            for _ in range(5):
                wait(.6);samples.append(sample(dk,third,target,enemy))
            after=samples[-1]
            spent=before['heroes'][0]['mana']-min(s['heroes'][0]['mana'] for s in samples)
            gain=max(s['target_hp'] for s in samples)-before['target_hp']
            row=dict(name=label,direct=direct,accepted=bool(receipt),reason=getattr(receipt,'reason',None),
                     before=before,samples=samples,mana_spent=spent,healing_gain=gain,
                     effect_observed=spent>=60 and gain>=150)
            case['casts'].append(row);save()
            print(json.dumps(dict(case=case['name'],test=label,effect=row['effect_observed'],
                                  accepted=bool(receipt),mana_spent=spent,healing_gain=gain)),flush=True)
            wait(7)  # More than 9 game seconds between attempts.
            return row

        for code in ('sbch','lhst'):
            for third_code,ability,spell in (('Nngs','ANfl','forkedlightning'),('Nbrn','ANsi','silence')):
                check();x,y=origin
                spawned=[]
                for typ,dx,dy,owner in [('Udea',0,0,g.me()),(third_code,100,0,g.me()),
                                        ('ugho',0,100,g.me()),('hfoo',250,0,1-g.me())]:
                    u=dev.spawn(typ,x+dx,y+dy,player=owner)
                    if not u:raise RuntimeError('Spawn failed: '+typ)
                    spawned.append(u)
                    dev.jass.SetUnitAcquireRange(u.jass_handle,0.)
                    if not dev.jass.UnitRemoveAbility(u.jass_handle,'Aatk'):
                        raise RuntimeError('Could not isolate spell effects from attacks')
                dk,third,target,enemy=spawned
                dev.jass.PauseUnit(enemy.jass_handle,True)
                wait(1)
                if hero_level==3:
                    for u in (dk,third):dev.jass.SetHeroLevel(u.jass_handle,3,False)
                    wait(1)
                skills=['AUdc'] if hero_level==1 else ['AUdc','AUau','AUdc']
                third_skills=[ability] if hero_level==1 else (
                    ['ANfl','ANfa','ANfl'] if third_code=='Nngs' else ['ANba','ANsi','ANba'])
                for u,sequence in ((dk,skills),(third,third_skills)):
                    for skill in sequence:
                        if not g.learn(fresh(u),skill):raise RuntimeError('Skill learning rejected: '+skill)
                        wait(.5)
                wait(1)
                case=dict(name=code+'_'+third_code,item=code,receiver=third_code,casts=[])
                report['cases'].append(case)
                baseline=case['baseline']=sample(dk,third,target,enemy)
                if not has(baseline,0,'AUdc') or not has(baseline,1,ability):
                    raise RuntimeError('Baseline learned ability not visible')
                g.observe_coil([fresh(dk)],g.clock(),lambda *a,**k:None)
                dev.jass.UnitAddItemById(dk.jass_handle,code)
                wait(2);case['dk_holding']=sample(dk,third,target,enemy)
                case['dk_missing_reproduced']=not has(case['dk_holding'],0,'AUdc')
                if code not in case['dk_holding']['heroes'][0]['inventory']:
                    raise RuntimeError('Aura item setup unconfirmed')
                # Two independently observed heals, separated by full cooldown.
                coil_case(case,dk,third,target,enemy,'direct_while_holding_1',True)
                coil_case(case,dk,third,target,enemy,'direct_while_holding_2',True)
                receipt=g.give_item(fresh(dk),g.inventory(fresh(dk)).index(code),fresh(third))
                case['transfer_accepted']=bool(receipt);wait(3)
                transferred=case['after_transfer']=sample(dk,third,target,enemy)
                case['transfer_confirmed']=(code not in transferred['heroes'][0]['inventory']
                                           and code in transferred['heroes'][1]['inventory'])
                case['dk_restored_after_transfer']=has(transferred,0,'AUdc')
                case['receiver_skill_preserved']=has(transferred,1,ability)
                # Refill mana only after handoff; a fresh normal readiness check
                # must now use the actual restored ability list and cooldown.
                state(dk,mana=255);wait(.6)
                coil_case(case,dk,third,target,enemy,'normal_after_transfer',False)
                before=sample(dk,third,target,enemy)
                if third_code=='Nngs':receipt=SDKGame.cast(g,fresh(third),spell,target=fresh(enemy))
                else:receipt=SDKGame.cast(g,fresh(third),spell,x=fresh(enemy).x,y=fresh(enemy).y)
                wait(2);after=sample(dk,third,target,enemy)
                case['receiver_direct_cast']=dict(accepted=bool(receipt),before=before,after=after,
                    mana_spent=before['heroes'][1]['mana']-after['heroes'][1]['mana'],
                    damage=before['enemy_hp']-after['enemy_hp'],
                    new_buffs=sorted(set(after['enemy_buffs'])-set(before['enemy_buffs'])))
                save()
                print(json.dumps(dict(case=case['name'],reproduced=case['dk_missing_reproduced'],
                    transfer=case['transfer_confirmed'],dk_restored=case['dk_restored_after_transfer'],
                    receiver_preserved=case['receiver_skill_preserved'])),flush=True)
                for u in spawned:dev.jass.RemoveUnit(u.jass_handle)
                wait(1)
        report['completed']=True
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop()
        report['owned_processes_closed']=not session.owned
        report['source_unchanged']=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        (ROOT/'artifacts/STOP').write_text('review_hold: isolated aura validation ended\n',encoding='utf-8')
        save()
    print(json.dumps(dict(report=str(out/'report.json'),completed=report['completed'],
                          error=report.get('error'),closed=report['owned_processes_closed'])),flush=True)
    return report['completed']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hero-level',type=int,choices=(1,3),default=1)
    args=parser.parse_args()
    raise SystemExit(0 if run(args.hero_level) else 1)
