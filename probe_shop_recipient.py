"""Isolated shop recipient diagnosis; never a P1 match or training sample."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from run_window import parse_deadline,ensure_time

session=Session(400);dev=None
until=parse_deadline('2026-10-09T00:00:00+08:00')
report={'fixture':True,'counts_as_match':False,'version':'0.1.13-dev','passed':False}
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
    first=g.buy(shop,'ocor');report['full_nearby_dk']={'accepted':bool(first),'reason':first.reason}
    # A semantic move changes only fixture positioning, not resources or stock.
    g.move(dk,x-800,y-650)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        ensure_time(until);g.snapshot(max_age=0);u=g.unit(dk.handle)
        if u and g.dist(u,shop)>900:break
        time.sleep(.2)
    time.sleep(.3);g.snapshot(max_age=0)
    report['dk_shop_distance']=g.dist(g.unit(dk.handle),shop)
    second=g.buy(shop,'ocor');report['dk_moved_away']={'accepted':bool(second),'reason':second.reason}
    time.sleep(.4);g.snapshot(max_age=0)
    report['after']={'dk':g.inventory(dk),'lich':g.inventory(lich)}
    report['passed']=not bool(first) and bool(second) and 'ocor' in report['after']['lich']
except Exception as exc:
    report['error']=repr(exc);traceback.print_exc()
finally:
    if dev:dev.close()
    session.stop();report['owned_processes_closed']=not session.owned
    (ROOT/'artifacts/p1-shop-recipient-fixture-0.1.13.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
