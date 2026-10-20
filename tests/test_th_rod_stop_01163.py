import unittest
from types import SimpleNamespace as N
import test_ni_rod_foundation_01146 as ni
import test_th_route_01152 as th
from test_micro_loot import unit,dist
from undead.battle_shop import RINGS,sellable


class THRodStopTests(unittest.TestCase):
    def scene(self,north=True):
        g,b,shop,s,ev=ni.NIRodTests().scene()
        _,_,_,c=th.THRouteTests().scene(north)
        b.creeping=c;b.ni_rod_stop=s
        b.home=N(x=-3904,y=2880) if north else N(x=2880,y=-3904)
        c.cleared.update(c.th_route(b.home)[:2])
        return g,b,shop,s,ev

    def test_both_spawns_buy_after_fish_then_rejoin_before_third_camp(self):
        for north in (True,False):
            g,b,shop,s,ev=self.scene(north)
            g.bags[g.dk.handle][1]='rnec'
            self.assertTrue(s.tick(b,[g.dk],220))
            self.assertEqual(ev[-1]['event'],'th_dk_rod_started')
            self.assertEqual(ev[-1]['after'],'th-1' if north else 'th-12')
            self.assertEqual(ev[-1]['before'],'th-2' if north else 'th-19')
            g.dk.x=0;s.tick(b,[g.dk],225)
            self.assertFalse(s.mission['returning'])
            shop.observe(g,229);s.tick(b,[g.dk],229)
            self.assertTrue(s.mission['returning'])
            self.assertEqual(g.inventory(g.dk).count('rnec'),2)
            g.dk.x,g.dk.y=s.mission['rally']
            self.assertFalse(s.tick(b,[g.dk],240));self.assertTrue(s.done)
            s.tick(b,[g.dk],245)
            self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)

    def test_first_camp_or_uncleared_second_camp_does_not_start_rebuy(self):
        for count in (0,1):
            g,b,shop,s,ev=self.scene()
            b.creeping.cleared=set(b.creeping.th_route(b.home)[:count])
            self.assertFalse(s.tick(b,[g.dk],190));self.assertFalse(g.orders)

    def test_escorts_stage_outside_third_camp_without_following_dk_home(self):
        g,b,shop,s,ev=self.scene()
        f=unit('ucry',90,1500)
        s.tick(b,[g.dk,f],220)
        rally=s.mission['rally'];camp=next(c for c in b.creeping.catalog if c['id']=='th-2')
        self.assertAlmostEqual(dist(rally,(camp['x'],camp['y'])),1100)
        self.assertIn(('move','ucry',rally),g.orders)
        self.assertIn(('move','Udea',(0,0)),g.orders)

    def test_full_bag_sells_cloak_and_ring_preserves_other_equipment_then_buys(self):
        g,b,shop,s,ev=self.scene();g.dk.x=0
        g.bags[g.dk.handle]=['stwp','clsd','rde1','rin1','rnec','ocor']
        def sell(h,i,target):
            code=g.bags[h.handle][i];g.bags[h.handle][i]=None
            g.gold+=RINGS.get(code,50);g.orders.append(('sell',h.type,code));return True
        g.sell_item=sell
        s.tick(b,[g.dk],220)
        self.assertEqual(g.orders[-1],('sell','Udea','clsd'))
        shop.observe(g,224);s.tick(b,[g.dk],224)
        self.assertEqual(g.orders[-1],('sell','Udea','rde1'))
        shop.observe(g,228);s.tick(b,[g.dk],228)
        self.assertEqual(g.orders[-1],('buy','Udea','rnec'))
        shop.observe(g,232);s.tick(b,[g.dk],232)
        self.assertTrue(s.mission['returning'])
        for code in ('rin1','ocor','stwp'):self.assertIn(code,g.inventory(g.dk))
        self.assertTrue(all(sellable(g.dk,code) for code in RINGS))
        self.assertFalse(sellable(g.dk,'rin1'))
        self.assertEqual(sum(e['event']=='shop_transaction_confirmed' and e['kind']=='sell' for e in ev),2)

    def test_rejected_sales_do_not_prevent_purchase_forever(self):
        g,b,shop,s,ev=self.scene();g.dk.x=0;g.bags[g.dk.handle][1]='clsd'
        g.sell_item=lambda *a:False
        for now in (220,224,228,232):
            shop.observe(g,now);s.tick(b,[g.dk],now)
        self.assertEqual(s.mission['sales']['clsd'],3)
        self.assertIn(('buy','Udea','rnec'),g.orders)
        self.assertFalse(s.mission['returning'])

    def test_same_tick_second_clear_starts_real_purchase_without_third_attack(self):
        b,g,a,c=th.THRouteTests().scene()
        c.cleared={'th-8'};c.active=next(p for p in c.catalog if p['id']=='th-1')
        point=(c.active['x'],c.active['y']);g.visible=lambda *a:True;g.creeps=lambda:[]
        g.my_heroes=lambda:[a[0]];g.inventory=lambda h:['rnec',None,None,None,None,None]
        b.rod_acquisitions={'Udea':1}
        b.economy.ready=lambda *a:[unit('utom',98,b.home.x)]
        moves=[];b.go=lambda *a,**kw:self.fail('third-camp group move before rebuy')
        b.go_raw=lambda army,p,now:moves.extend((u.type,p) for u in army)
        b.creep(a,point,218)
        self.assertIsNotNone(b.ni_rod_stop.mission)
        self.assertEqual(c.active['id'],'th-2')
        self.assertTrue(any(typ=='Udea' for typ,p in moves))


if __name__=='__main__':unittest.main()
