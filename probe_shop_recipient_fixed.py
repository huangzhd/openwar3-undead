"""Isolated shop recipient diagnosis; never a P1 match or training sample."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from run_window import parse_deadline,ensure_time

session=Session(400);dev=None
until=parse_deadline('2026-10-09T00:00:00+08:00')
report={'fixture':True,'counts_as_match':False,'version':'0.1.14-dev','passed':False}
try:
    g=session.start(until=until);dev=Game(pid=g.pid,fair=False)
    home=g.my_buildings({'unpl'})[0];x,y=home.x,home.y
    player=dev.jass.Player(g.me())
    dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(1),10000)
    dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(2),10000)
    tier=dev.spawn('unp2',x+650,y)
    shop=dev.spawn('utom',x+650,y-650)
    dk=dev.spawn('Udea',x+500,y-650)
    lich=dev.spawn('Ulic',x+650,y-900)
    if not all((tier,shop,dk,lich)):raise RuntimeError('Fixture spawn failed')
    for i in range(6):dev.jass.UnitAddItemById(dk.jass_handle,int.from_bytes(b'rat6','big'))
    time.sleep(.4);g.snapshot(max_age=0)
    report['before']={'dk':g.inventory(dk),'lich':g.inventory(lich)}
    if None in report['before']['dk']:raise RuntimeError('DK fixture bag not full')
    report['events']=[]
    bot=Controller(g,lambda event,**kw:report['events'].append(dict(event=event,**kw)))
    bot.home=home
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        ensure_time(until);snap=g.snapshot(max_age=0)
        heroes=g.my_heroes();h=next(h for h in heroes if h.type=='Ulic')
        if 'ocor' in g.inventory(h):
            report['passed']=True;break
        if bot.shop_item(heroes,h,shop,'ocor',snap.clock):
            bot.go(heroes,(shop.x,shop.y),snap.clock)
        time.sleep(.2)
    report['after']={'dk':g.inventory(dk),'lich':g.inventory(lich)}
    report['all_original_items_preserved']=sum(inv.count('rat6') for inv in report['after'].values())==6
    report['passed']=report['passed'] and report['all_original_items_preserved']
except Exception as exc:
    report['error']=repr(exc);traceback.print_exc()
finally:
    if dev:dev.close()
    session.stop();report['owned_processes_closed']=not session.owned
    (ROOT/'artifacts/p1-shop-recipient-fixture-0.1.14.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
