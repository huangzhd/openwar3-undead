"""P0 live behavioural probe; uses game API only, never mouse/keyboard input."""
import json
import time
import traceback
from bootstrap import ROOT
from session import Session

results = {'stage':'P0','checks':{},'errors':[]}
path = ROOT / 'artifacts' / 'p0-probe.json'
def record(name, value):
    results['checks'][name] = value
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'check':name,'value':value},ensure_ascii=False),flush=True)

def receipt(r):
    return {'accepted':bool(r),'reason':getattr(r,'reason',None)}

session = Session()
try:
    g = session.start()
    record('undead_start',True)
    initial = g.resources().copy()
    acolytes = g.units('me',{'uaco'})
    ghouls = g.units('me',{'ugho'})
    home = g.my_buildings({'unpl'})[0]
    mine = g.nearest([m for m in g.gold_mines() if m.type == 'ugol' and m.owner == g.me()],home)
    if mine is None or not ghouls or len(acolytes) != 3:
        raise RuntimeError('Unexpected undead initial units/mine')
    trees = g.trees(home.x,home.y)
    if not trees:
        raise RuntimeError('Tree state unavailable')
    for a in acolytes:
        print('gather gold',receipt(g.gather(a,mine)),flush=True)
    print('gather wood',receipt(g.gather(ghouls[0],trees[0])),flush=True)
    print('train acolyte',receipt(g.train(home,'uaco')),flush=True)
    builder_handle = acolytes[0].handle
    started = time.monotonic()
    next_log = started
    altar_handle = None
    while time.monotonic() - started < 150:
        s = g.snapshot(max_age=0)
        if not s or not s.in_game:
            raise RuntimeError('Snapshot/game disappeared')
        res = g.resources()
        altars = g.my_buildings({'uaod'})
        if not altars:
            builder = g.unit(builder_handle)
            if builder:
                g.build_near(builder,'uaod',home.x,home.y,min_r=256,max_r=656,max_tries=24)
        else:
            altar_handle = altars[0].handle
            for a in g.idle_workers():
                g.gather(a,mine)
            if altars[0].hp >= altars[0].hp_max and not g.production(altars[0]):
                if not results['checks'].get('altar_completed'):
                    record('altar_completed',{'clock':s.clock,'hp':altars[0].hp,'hp_max':altars[0].hp_max})
        if res['gold_gathered'] > initial['gold_gathered'] and not results['checks'].get('gold_income'):
            record('gold_income',{'before':initial['gold_gathered'],'after':res['gold_gathered']})
        if res['lumber_gathered'] > initial['lumber_gathered'] and not results['checks'].get('wood_income'):
            record('wood_income',{'before':initial['lumber_gathered'],'after':res['lumber_gathered']})
        if len(g.units('me',{'uaco'})) > len(acolytes) and not results['checks'].get('acolyte_trained'):
            record('acolyte_trained',{'count':len(g.units('me',{'uaco'}))})
        if time.monotonic() >= next_log:
            print(json.dumps({'clock':s.clock,'resources':res,'altar':[(u.hp,u.hp_max) for u in altars],'orders':[(u.type,u.order) for u in g.my_units()]},ensure_ascii=False),flush=True)
            next_log = time.monotonic() + 10
        if all(results['checks'].get(k) for k in ('altar_completed','gold_income','wood_income','acolyte_trained')):
            break
        time.sleep(.25)
    required = ('altar_completed','gold_income','wood_income','acolyte_trained')
    missing = [k for k in required if not results['checks'].get(k)]
    if missing:
        raise RuntimeError('Behaviour not verified within 150 seconds: '+repr(missing))
    session.stop()
    record('first_session_closed',True)
    g = session.start()
    record('undead_restart',{'clock':g.clock(),'units':[u.type for u in g.my_units()]})
    session.stop()
    record('second_session_closed',True)
    results['passed'] = True
except Exception as exc:
    results['passed'] = False
    results['errors'].append(repr(exc))
    traceback.print_exc()
finally:
    try:
        session.stop()
    except Exception as exc:
        results['passed'] = False
        results['errors'].append('cleanup: '+repr(exc))
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if results.get('passed') else 1)
