"""Isolated equipment transfer fixture; setup mutations never enter normal matches."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.equipment import Equipment


def main():
    report=dict(version='0.1.23-dev',fixture=True,counts_as_match=False,passed=False,events=[],samples=[])
    session=Session(400);dev=None
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0];mp=g.map()
        origin=next(((home.x+dx,home.y+dy) for dx,dy in [(700,-500),(700,500),(-700,-500),(-700,500)]
                     if mp.walkable(home.x+dx,home.y+dy) and mp.walkable(home.x+dx+120,home.y+dy)),None)
        if origin is None:raise RuntimeError('No walkable fixture location')
        dk=dev.spawn('Udea',*origin);lich=dev.spawn('Ulic',origin[0]+120,origin[1])
        if not dk or not lich:raise RuntimeError('Hero fixture spawn failed')
        wanted=['ratf','ratc','rat9','cnob','bspd']
        for code in wanted:dev.jass.UnitAddItemById(dk.jass_handle,code)
        time.sleep(.5)
        equip=Equipment(lambda event,**kw:report['events'].append(dict(event=event,**kw)));protected={}
        deadline=time.monotonic()+40;reserved=False;orb_added=False;full_at=None
        while time.monotonic()<deadline:
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop')
            snap=g.snapshot(max_age=0);heroes=[g.unit(dk.handle),g.unit(lich.handle)]
            if not all(heroes):time.sleep(.2);continue
            before={u.type:g.inventory(u) for u in heroes}
            if any(bag is None for bag in before.values()):time.sleep(.2);continue
            equip.tick(g,heroes,[],snap.clock,protected)
            report['samples'].append(dict(clock=snap.clock,inventory=before))
            bag=before['Ulic']
            if not orb_added and all(code in bag for code in wanted) and bag.count(None)==1:
                reserved=True;report['before_orb']=before
                dev.jass.UnitAddItemById(lich.jass_handle,'ocor')
                dev.jass.UnitAddItemById(dk.jass_handle,'rat6')
                orb_added=True
            if orb_added and 'ocor' in bag:
                if full_at is None:full_at=snap.clock
                if snap.clock-full_at>=8:
                    report['after']=before
                    report['passed']=reserved and all(code in bag for code in wanted) and 'rat6' in before['Udea'] and bag.count(None)==0
                    break
            time.sleep(.2)
        report['orb_slot_observed']=reserved
        report['transfer_confirmations']=sum(e['event']=='equipment_transfer_confirmed' for e in report['events'])
        report['passed']=report['passed'] and report['transfer_confirmations']==5
        if not report['passed']:report['error']='Missing transfer, reserved slot, or overflow-preservation evidence'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-equipment-fixture-0.1.23.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'events','samples'}},ensure_ascii=False),flush=True)
    return report['passed']


if __name__=='__main__':raise SystemExit(0 if main() else 1)
