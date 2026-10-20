import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.home_layout import HomeLayout
from test_micro_loot import unit
import test_growth_expansion_0149 as growth


class FoundationTests(unittest.TestCase):
    def scene(self):
        home=unit('unp1',1,-3904);home.y=-3968
        worker=unit('uaco',2,-4200);worker.y=-4200
        buildings=[home];workers=[worker];orders=[];events=[];order=[0]
        g=N(my_buildings=lambda:buildings,units=lambda side,codes:workers,
            build_near=lambda w,c,x,y,**kw:orders.append((c,x,y)) or (x,y),
            can_afford=lambda code:False,order_of=lambda u:order[0],hold=lambda u:orders.append(('hold',u.handle)) or True)
        layout=HomeLayout(lambda event,**kw:events.append(dict(event=event,**kw)))
        return layout,g,home,worker,buildings,workers,orders,events,order

    def test_delayed_foundation_keeps_builder_and_never_reissues_build(self):
        l,g,h,w,bs,ws,orders,events,order=self.scene()
        point=l.build(g,w,'uaod',h,3)
        order[0]=0x75616f64;w.x=(w.x+point[0])/2;w.y=(w.y+point[1])/2
        l.observe(g,18);self.assertEqual(l.reserved,{w.handle})
        self.assertEqual(l.build(g,w,'uaod',h,18),point);self.assertEqual(len(orders),1)
        foundation=unit('uaod',3,point[0]-32);foundation.y=point[1]-32;foundation.hp=12
        bs.append(foundation);l.observe(g,24)
        self.assertFalse(l.reserved);self.assertFalse(l.pending)
        self.assertEqual(events[-1]['event'],'home_foundation_observed')

    def test_walking_progress_extends_wait_and_stall_releases_once(self):
        l,g,h,w,bs,ws,orders,events,order=self.scene();point=l.build(g,w,'uslh',h,1)
        order[0]=0x75736c68
        w.x=(w.x+point[0])/2;w.y=(w.y+point[1])/2
        l.observe(g,25);self.assertTrue(l.pending)
        l.observe(g,42);self.assertFalse(l.pending)
        self.assertEqual(orders[-1],('hold',w.handle));self.assertEqual(events[-1]['event'],'home_foundation_unconfirmed')

    def test_idle_pending_builder_is_not_sent_to_gold_or_other_construction(self):
        g,e,_=growth.GrowthExpansionTests().make()
        worker=g.units('me',{'uaco'})[0];home=g.my_buildings({'unp2'})[0]
        e.home_layout.pending['uaod']=dict(worker=worker.handle,point=(worker.x,worker.y),started=700,progress=700,gap=0,before={u.handle for u in g.my_buildings()})
        e.tick(g,701)
        self.assertFalse(any(h==worker.handle for h,mine in g.gathers))
        self.assertFalse(any(h==worker.handle for h,code,x,y in g.builds))

    def test_fixture_proves_duplicate_buildings_are_real_not_just_receipts(self):
        f=json.loads((Path(__file__).parent/'fixtures/lr-duplicate-foundations-01124.json').read_text(encoding='utf-8'))
        own=f['samples'][-1]['own']
        for code in ('uaod','utom','uslh'):
            self.assertEqual(sum(u['type']==code and u['hp']>0 for u in own),2)


if __name__=='__main__':unittest.main()
