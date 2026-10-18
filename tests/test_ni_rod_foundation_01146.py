import unittest
from types import SimpleNamespace as N
import test_foundation_owner_01124 as foundation
import test_battle_shop_0163 as shopping
import test_ni_route_01142 as ni
import test_ch_stage_01135 as lich
from undead.ni_rod_stop import NIRodStop


class FastGraveyardTests(unittest.TestCase):
    def test_lost_order_reselects_in_observation_tick_and_reserves_same_worker(self):
        l,g,h,w,bs,ws,orders,events,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True
        first=l.build(g,w,'ugrv',h,81.875)
        self.assertTrue(l.observe(g,84))
        self.assertNotEqual(l.pending['ugrv']['point'],first)
        self.assertEqual(l.reserved,{w.handle})
        self.assertEqual(sum(o[0]=='ugrv' for o in orders),2)
        self.assertTrue(any(e.get('reason')=='order_lost' for e in events))

    def test_real_travel_and_actual_foundation_are_preserved(self):
        l,g,h,w,bs,ws,orders,events,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True
        point=l.build(g,w,'ugrv',h,80);order[0]=0x75677276
        for t in (82,84,86):
            w.x=(w.x+point[0])/2;w.y=(w.y+point[1])/2
            l.observe(g,t)
        self.assertEqual(len(orders),1)
        bs.append(N(type='ugrv',handle=(99,99),x=point[0],y=point[1]))
        l.observe(g,87);self.assertFalse(l.pending);self.assertEqual(len(orders),1)

    def test_motionless_build_order_is_cancelled_and_next_point_tried(self):
        l,g,h,w,bs,ws,orders,events,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True;first=l.build(g,w,'ugrv',h,80);order[0]=0x75677276
        self.assertTrue(l.observe(g,83))
        self.assertIn(('hold',w.handle),orders)
        self.assertNotEqual(l.pending['ugrv']['point'],first)

    def test_sdk_old_point_after_cancellation_is_not_registered_again(self):
        l,g,h,w,bs,ws,orders,events,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True;first=l.build(g,w,'ugrv',h,80)
        g.build_near=lambda *a,**k:first
        l.observe(g,83);self.assertFalse(l.pending)


class NIRodTests(unittest.TestCase):
    def scene(self,north=False):
        g,b,shop,events=shopping.ShoppingTests().make()
        g.walk_path=lambda a,z:[a,z]
        _,_,_,c=ni.NIRouteTests().scene(north)
        b.creeping=c;b.home=N(x=6912 if north else -2752,y=3264 if north else -3328)
        c.cleared.update(c.ni_opening(b.home)[:2])
        b.rod_acquisitions={'Udea':1};b.battle_shop=shop
        g.heroes=[g.dk];g.dk.y=0
        stop=NIRodStop(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        return g,b,shop,stop,events

    def test_both_spawns_buy_one_new_rod_even_with_old_rod_then_rejoin(self):
        for north in (False,True):
            g,b,shop,s,ev=self.scene(north);g.bags[g.dk.handle][1]='rnec'
            self.assertTrue(s.tick(b,[g.dk],220))
            self.assertEqual(g.orders[-1],('move','Udea',(0,0)))
            g.dk.x=0;s.tick(b,[g.dk],225)
            self.assertEqual(g.inventory(g.dk).count('rnec'),2)
            self.assertFalse(s.mission['returning'])
            shop.observe(g,229);s.tick(b,[g.dk],229)
            self.assertTrue(s.mission['returning'])
            g.dk.x,g.dk.y=s.mission['rally']
            self.assertFalse(s.tick(b,[g.dk],240));self.assertTrue(s.done)
            self.assertEqual(b.rod_acquisitions['Udea'],2)
            g.bags[g.dk.handle]=[None]*6;s.tick(b,[g.dk],250)
            self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)

    def test_not_before_second_fish_or_on_other_map(self):
        for why in ('first','other'):
            g,b,shop,s,ev=self.scene()
            if why=='first':b.creeping.cleared={'ni-2'}
            else:b.creeping.map_alias='CH'
            self.assertFalse(s.tick(b,[g.dk],170));self.assertFalse(g.orders)

    def test_receipts_alone_never_complete_and_retries_are_bounded(self):
        g,b,shop,s,ev=self.scene();g.dk.x=0
        g.buy=lambda *a:g.orders.append(('fake-buy',)) or True
        for t in (220,224,228,232,236):
            shop.observe(g,t);s.tick(b,[g.dk],t)
        self.assertEqual(sum(o[0]=='fake-buy' for o in g.orders),3)
        self.assertFalse(s.done);self.assertTrue(s.failed)
        self.assertFalse(any(e['event']=='ni_dk_rod_inventory_confirmed' for e in ev))

    def test_wrong_recipient_transfer_and_no_repeat_purchase(self):
        g,b,shop,s,ev=self.scene();g.heroes.append(g.lich);g.dk.x=g.lich.x=0
        def buy(*args):
            g.bags[g.lich.handle][1]='rnec';g.orders.append(('buy','Ulic','rnec'));return True
        g.buy=buy;s.tick(b,g.heroes,220);shop.observe(g,224);s.tick(b,g.heroes,224)
        shop.observe(g,228);s.tick(b,g.heroes,228)
        self.assertTrue(s.mission['returning'])
        self.assertIn('rnec',g.inventory(g.dk));self.assertNotIn('rnec',g.inventory(g.lich))
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)

    def test_dk_wrong_recipient_does_not_consume_lich_own_purchase_allowance(self):
        g,b,shop,s,ev=self.scene();b.ni_rod_stop=s
        g.heroes.append(g.lich);g.dk.x=g.lich.x=0
        def buy(*args):
            g.bags[g.lich.handle][1]='rnec';return True
        g.buy=buy;s.tick(b,g.heroes,220);shop.observe(g,224)
        self.assertEqual(shop.rod_tick(b,[],224,2),{g.lich.handle})
        self.assertFalse(shop.lich_rod_bought)
        s.tick(b,g.heroes,224)
        self.assertIn('rnec',g.inventory(g.dk))

    def test_lich_own_purchase_is_not_mistaken_for_dk_purchase(self):
        g,b,shop,s,ev=self.scene();s.tick(b,[g.dk],220)
        g.heroes.append(g.lich);g.bags[g.lich.handle][1]='rnec';g.dk.x=0
        s.tick(b,g.heroes,225)
        self.assertFalse(any(o[0]=='give' for o in g.orders))
        self.assertEqual(sum(o[:2]==('buy','Udea') for o in g.orders),1)

    def test_same_tick_four_fish_clear_does_not_issue_ogre_attack_before_purchase(self):
        b,g,a,c=ni.NIRouteTests().scene();c.cleared={'ni-2'}
        c.active=next(p for p in c.catalog if p['id']=='ni-6')
        point=(c.active['x'],c.active['y']);g.visible=lambda *p:True;g.creeps=lambda:[]
        b.ni_rod_stop.tick=lambda bot,army,now:bool(c.ni_route_stage(b.home)=='ni-4')
        moves=[];b.go=lambda army,goal,now,attack=False:moves.append(goal)
        b.creep(a,point,220)
        self.assertIn('ni-6',c.cleared);self.assertFalse(moves)

    def test_lich_first_rod_at_tier_three_still_buys_once_and_rejoins_dk(self):
        g,b,s,ev=lich.RodCourierTests().scene();g.lich.x=0;g.bags[g.dk.handle][1]='rnec'
        s.rod_tick(b,[],350,3);s.observe(g,354);s.rod_tick(b,[],354,3)
        self.assertIn('rnec',g.inventory(g.lich))
        self.assertEqual(g.orders[-1],('move','Ulic',(g.dk.x,g.dk.y)))
        g.lich.x=g.dk.x;s.rod_tick(b,[],360,3)
        g.bags[g.lich.handle]=[None]*6;s.rod_tick(b,[],370,3)
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)


if __name__=='__main__':unittest.main()
