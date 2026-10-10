"""Isolated real full-DK/orb-reservation/portal handoff fixture."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.policy import Action


def main():
    report=dict(version='0.1.24-dev',fixture=True,counts_as_match=False,passed=False,events=[],samples=[])
    session=Session(400);dev=None
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0];x,y=home.x,home.y
        player=dev.jass.Player(g.me())
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(1),10000)
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(2),10000)
        tier=dev.spawn('unp2',x+650,y);shop=dev.spawn('utom',x+650,y-650)
        dk=dev.spawn('Udea',x+500,y-650);lich=dev.spawn('Ulic',x+650,y-850)
        if not all((tier,shop,dk,lich)):raise RuntimeError('Fixture spawn failed')
        for code in ['rnec','rat6','ocor','cnob','bspd','rlif']:dev.jass.UnitAddItemById(dk.jass_handle,code)
        for _ in range(5):dev.jass.UnitAddItemById(lich.jass_handle,'rat6')
        time.sleep(.5)
        b=Controller(g,lambda event,**kw:report['events'].append(dict(event=event,**kw)))
        b.home=home;b.action=Action.ATTACK
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop')
            snap=g.snapshot(max_age=0);a=g.unit(dk.handle);c=g.unit(lich.handle)
            if not a or not c:time.sleep(.2);continue
            bags=dict(dk=g.inventory(a),lich=g.inventory(c))
            if any(v is None for v in bags.values()):time.sleep(.2);continue
            report['samples'].append(dict(clock=snap.clock,**bags))
            if 'ocor' in bags['lich'] and 'stwp' in bags['dk']:
                report['passed']=bags['lich'].count('rat6')==5 and all(code in bags['dk'] for code in ['rnec','rat6','cnob','bspd','rlif'])
                report['after']=bags;break
            b.prepare_attack(g.my_heroes(),snap.clock)
            time.sleep(.2)
        if not report['passed']:report['error']='No completed orb delivery plus portal purchase with all prior items preserved'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-equipment-portal-fixture-0.1.24.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'events','samples'}},ensure_ascii=False),flush=True)
    return report['passed']


if __name__=='__main__':raise SystemExit(0 if main() else 1)
