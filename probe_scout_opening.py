"""Bounded natural opening observation through OpenWar3AI; no dev setup."""
import hashlib,json,time,traceback
from bootstrap import ROOT
from session import Session
from undead.controller import Controller
from undead.debug_console import DebugConsole

def run():
    start=time.monotonic();session=Session(400,4,4);console=None
    report=dict(version='0.1.40-dev',rules_version='0.1.40',normal_match=False,
                natural_opening=True,passed=False,events=[],samples=[])
    files=[ROOT/'probe_scout_opening.py',ROOT/'session.py',ROOT/'bot.py',ROOT/'run_match.py',*sorted((ROOT/'undead').glob('*.py'))]
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        g=session.start();report['owned_processes']=list(session.owned);report['verified_opponent']=session.settings['verified_opponent']
        def log(e,**kw):report['events'].append(dict(event=e,**kw))
        b=Controller(g,log,4);console=DebugConsole(g,log);last=-1;last_wall=time.monotonic()
        while time.monotonic()-start<125:
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
            s=g.snapshot(max_age=0)
            if not s or not s.in_game:raise RuntimeError('Opening snapshot unavailable')
            if s.clock==last:
                if time.monotonic()-last_wall>10:raise RuntimeError('Opening clock stopped')
                time.sleep(.15);continue
            last=s.clock;last_wall=time.monotonic()
            b.observe_events(g.events());b.tick();console.observe(s,b)
            def row(u):
                target=g.current_target(u)
                return dict(type=u.type,handle=u.handle,x=u.x,y=u.y,hp=u.hp,alive=u.alive,
                            target=target.handle if target else None,target_type=target.type if target else None,
                            order=g.order_of(u))
            report['samples'].append(dict(clock=s.clock,
                own=[row(u) for u in g.units('me',{'Udea','uaco','uske','uskm','ucry'})],
                neutral=[row(u) for u in g.units(15,alive=False) if u.hp_max<=100],
                creeps=[row(u) for u in g.creeps()],
                rod=g.inventory(next(iter(g.my_heroes()),None)) if g.my_heroes() else None))
            if s.clock>=320:break
            time.sleep(.2)
        report['last_clock']=last
        events=report['events'];samples=report['samples']
        corpses=[e for e in events if e['event']=='scout_corpse_observed']
        ready=[e for e in events if e['event']=='opening_skeletons_ready' and e['fiends']==0]
        goals=[e for e in events if e['event']=='creep_goal']
        birth=next((s['clock'] for s in samples if any(u['type']=='ucry' for u in s['own'])),None)
        first=goals[0] if goals else None
        gnolls={'ngnb','ngna'}
        pre_fiend=[s for s in samples if (birth is None or s['clock']<birth) and
                   any(u['type']=='Udea' and u['target_type'] in gnolls for u in s['own']) and
                   sum(u['type']=='uske' for u in s['own'])>=2]
        fiend_combat=[s for s in samples if any(u['type']=='ucry' and u['target_type'] in {e['type'] for e in s['creeps']} for u in s['own'])]
        # Damage must be observed on the actual creep targeted by the first fiend.
        fiend_damage=False
        for i,s in enumerate(samples):
            targets={tuple(u['target']) for u in s['own'] if u['type']=='ucry' and u['target']}
            for e in s['creeps']:
                if tuple(e['handle']) not in targets:continue
                for later in samples[i+1:i+7]:
                    seen=next((v for v in later['creeps'] if v['handle']==e['handle']),None)
                    if seen and seen['hp']<e['hp']-1:fiend_damage=True
        checks=dict(observed_scout_corpse=bool(corpses),two_skeletons_before_fiend=any(sum(u['type']=='uske' for u in s['own'])>=2 and not any(u['type']=='ucry' for u in s['own']) for s in samples),
                    first_goal_gnoll=bool(first and first['kind']=='gnoll'),
                    dk_and_two_skeletons_fight_before_fiend=bool(pre_fiend),
                    fiend_joins_combat=bool(fiend_combat and fiend_damage))
        report.update(checks=checks,passed=all(checks.values()),first_fiend_clock=birth,
                      first_creep_goal=first,first_pre_fiend_combat=pre_fiend[0] if pre_fiend else None,
                      first_fiend_combat=fiend_combat[0] if fiend_combat else None)
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if console:console.close()
        session.stop();report['wall_seconds']=round(time.monotonic()-start,2)
        report['owned_processes_closed']=not any(Session.matches(r) for r in report.get('owned_processes',[]))
        report['limitations']=['Natural first 320 game seconds only; not a normal win/loss or complete match.',
                               'Creep damage while fiend targets it may include DK/skeleton damage.']
        (ROOT/'artifacts/p1-scout-opening-0.1.40.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in {'samples','events','source_hashes'}},ensure_ascii=False,indent=2))
    return report['passed'] and report['owned_processes_closed']

if __name__=='__main__':raise SystemExit(0 if run() else 1)
