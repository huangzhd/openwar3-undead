"""Bounded isolated own-position fixture. Never counts as a normal match."""
import hashlib
import json
import time
import traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.policy import Action


def run():
    report=dict(fixture=True,counts_as_match=False,passed=False,events=[],samples=[],
                version='0.1.25-dev',rules_version='0.1.25',
                source_run='20261009-150553',source_clock=1401.68,
                limitations=['Only own positions are replayed; historical enemies/orders are not reconstructed.',
                             'This tests march recovery only, not search coverage, combat survival or normal win/loss.'])
    source=ROOT/'artifacts'/'20261009-150553'/'events.jsonl'
    row=next(r for line in source.read_text(encoding='utf-8').splitlines()
             if (r:=json.loads(line))['event']=='combat_state' and r['clock']==report['source_clock'])
    positions=[u for u in row['army'] if u['type'] in {'Udea','Ulic','Nbrn','ucry','uobs'}]
    report['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted((ROOT/'undead').glob('*.py'))}
    session=Session(400);dev=None
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        # Developer client prepares only own units. Policy uses fair=True g.
        spawned=[dev.spawn(u['type'],u['x'],u['y']) for u in positions]
        if not all(spawned):raise RuntimeError('Fixture own-unit spawn failed')
        handles={u.handle for u in spawned}
        bot=Controller(g,lambda event,**kw:report['events'].append(dict(event=event,**kw)))
        bot.action=Action.ATTACK
        target=(-4653.8,-2971.9);report['target']=target
        wall_end=time.monotonic()+45;first=None
        while time.monotonic()<wall_end:
            snap=g.snapshot(max_age=0)
            army=[u for u in g.my_units() if u.handle in handles]
            if len(army)!=len(spawned):raise RuntimeError('Fixture unit missing')
            dk=next(u for u in army if u.type=='Udea');others=[u for u in army if u is not dk]
            main=min(others,key=lambda u:sum(g.dist(u,v) for v in others))
            sample=dict(clock=snap.clock,gap=round(g.dist(dk,main)),
                        dk=[dk.x,dk.y],main=[main.x,main.y],
                        army=[dict(handle=u.handle,type=u.type,x=u.x,y=u.y,hp=u.hp) for u in army])
            report['samples'].append(sample)
            if first is None:first=sample
            if sample['gap']<=550 and g.dist(first['main'],sample['main'])>=1000:
                report['passed']=first['gap']>3000
                break
            if snap.clock-first['clock']>=120:break
            bot.go(army,target,snap.clock,attack=True)
            time.sleep(.2)
        report['initial']=report['samples'][0]
        report['final']=report['samples'][-1]
        report['elapsed_game_seconds']=report['final']['clock']-report['initial']['clock']
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        path=ROOT/'artifacts'/'p1-march-recovery-fixture-0.1.25.json'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'samples','events','initial','final','source_hashes'}},ensure_ascii=False))
    if report.get('initial'):print(json.dumps(dict(initial_gap=report['initial']['gap'],final_gap=report['final']['gap'])))


if __name__=='__main__':run()
