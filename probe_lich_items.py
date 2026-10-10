"""Bounded API fixture for 0.1.29 equipment and intelligence tome ownership."""
import hashlib,json,time,traceback
from bootstrap import ROOT,UPSTREAM
from session import Session
from openwar3 import Game
from undead.equipment import Equipment
from undead.loot import Loot


def run():
    report=dict(version='0.1.29-dev',rules_version='0.1.29',fixture=True,counts_as_match=False,passed=False,events=[],book_cases=[],samples=[])
    report['source_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'undead').glob('*.py'))}
    report['probe_hash']=hashlib.sha256(__file__ and open(__file__,'rb').read()).hexdigest()
    session=Session(400);dev=None;handles=[];overall_end=time.monotonic()+110
    def check():
        if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop requested')
        if time.monotonic()>=overall_end:raise TimeoutError('Fixture wall limit')
    def log(event,**kw):report['events'].append(dict(event=event,**kw))
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0];mp=g.map()
        point=next(( (home.x+dx,home.y+dy) for dx,dy in [(700,-500),(700,500),(-700,-500)] if all(mp.walkable(home.x+dx+n,home.y+dy) for n in (0,100,500))))
        dk=dev.spawn('Udea',*point)
        if not dk:raise RuntimeError('DK spawn failed')
        handles.append(dk.handle);g.hold(dk);time.sleep(.3)
        loot=Loot(json.loads((UPSTREAM/'data/game/items.json').read_text(encoding='utf-8')),log)
        def heroes():
            return [u for h in handles if (u:=g.unit(h)) and u.alive]
        def book(code,expected):
            check();before={u.type:u.mana_max for u in heroes()};start=g.clock();deadline=time.monotonic()+18
            dk_now=g.unit(dk.handle)
            dev.jass.CreateItem(code,dk_now.x+30,dk_now.y)
            observed=False
            while time.monotonic()<deadline and g.clock()-start<55:
                check();g.snapshot(max_age=0);hs=heroes()
                observed=observed or any(it.type==code for it in g.items_on_ground())
                loot.tick(g,hs,[],g.clock(),hs)
                after={u.type:u.mana_max for u in hs}
                if observed and after.get(expected,0)>before[expected]:
                    case=dict(code=code,expected=expected,before_mana_max=before,after_mana_max=after,clock=g.clock(),inventory={u.type:g.inventory(u) for u in hs},passed=all(after[t]==v for t,v in before.items() if t!=expected))
                    report['book_cases'].append(case);return case['passed']
                time.sleep(.1)
            report['book_cases'].append(dict(code=code,expected=expected,passed=False,before_mana_max=before,observed_ground=observed));return False
        if not book('tint','Udea'):raise RuntimeError('Early DK tome effect not confirmed')
        lich=dev.spawn('Ulic',point[0]+500,point[1]);handles.append(lich.handle);g.hold(lich);time.sleep(.3)
        if not book('tint','Ulic'):raise RuntimeError('Lich tome priority/effect not confirmed')
        wanted=['gcel','rin1','ciri','hcun','belv']
        for code in wanted:dev.jass.UnitAddItemById(dk.jass_handle,code)
        equipment=Equipment(log);protected={};deadline=time.monotonic()+25;reserved=False
        while time.monotonic()<deadline:
            check();g.snapshot(max_age=0);hs=heroes();now=g.clock()
            equipment.tick(g,hs,[],now,protected)
            bags={u.type:g.inventory(u) for u in hs}
            report['samples'].append(dict(clock=now,bags=bags))
            if all(c in (bags.get('Ulic') or []) for c in wanted) and bags['Ulic'].count(None)==1:
                report['before_orb']=bags;reserved=True;break
            time.sleep(.1)
        if not reserved:raise RuntimeError('Equipment transfer/orb reservation not observed')
        dev.jass.UnitAddItemById(lich.jass_handle,'ocor');dev.jass.UnitAddItemById(dk.jass_handle,'gcel');time.sleep(.3)
        full_bag=g.inventory(g.unit(lich.handle))
        report['full_lich_before_tome']=full_bag
        if not full_bag or None in full_bag:raise RuntimeError('Full inventory setup failed')
        if not book('tin2','Ulic'):raise RuntimeError('Full-inventory Lich tome effect not confirmed')
        start=g.clock();deadline=time.monotonic()+5
        while time.monotonic()<deadline and g.clock()-start<8:
            check();g.snapshot(max_age=0);equipment.tick(g,heroes(),[],g.clock(),protected);time.sleep(.1)
        report['final_inventory']={u.type:g.inventory(u) for u in heroes()}
        report['transfer_confirmations']=sum(e['event']=='equipment_transfer_confirmed' for e in report['events'])
        report['passed']=all(c['passed'] for c in report['book_cases']) and report['transfer_confirmations']==5 and all(c in report['final_inventory']['Ulic'] for c in wanted+['ocor']) and 'gcel' in report['final_inventory']['Udea']
        report['limitations']=['Isolated own-unit/item setup; not a normal match or training sample.','Tome effects verified by recipient mana-max increase and no increase for the other present hero.','Equipment ownership is verified through inventories; this is not a measured attack-speed DPS benchmark.','No equipment was discarded, sold, or automatically replaced; overflow remains with DK.']
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-lich-items-fixture-0.1.29.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'source_hashes','events','samples'}},ensure_ascii=False,indent=2),flush=True)
    return report['passed']
if __name__=='__main__':raise SystemExit(0 if run() else 1)
