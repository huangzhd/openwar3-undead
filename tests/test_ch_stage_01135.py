import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_battle_shop_0163 as shops
import test_ch_opening_01130 as opening
import test_creep_tempo_01101 as tempo
from test_micro_loot import unit
from undead.policy import Situation,Action,choose_rule,attack_ready


class RodCourierTests(unittest.TestCase):
    def scene(self):
        g,b,s,events=shops.ShoppingTests().make()
        b.economy.opening_rod_allowed=True
        g.bags[g.dk.handle]=[None]*6
        return g,b,s,events

    def test_dk_alone_buys_and_rejoins_moving_lich_after_inventory_confirmation(self):
        g,b,s,events=self.scene()
        self.assertEqual(s.rod_tick(b,[],350,2),{g.dk.handle})
        self.assertEqual(g.orders,[('move','Udea',(0,0))])
        g.dk.x=0;s.rod_tick(b,[],355,2)
        self.assertIn('rnec',g.inventory(g.dk));self.assertIsNotNone(s.rod)
        s.observe(g,357);g.lich.x=2700;s.rod_tick(b,[],359,2)
        self.assertEqual(g.orders[-1],('move','Udea',(2700,0)))
        g.lich.x=3000;g.dk.x=2700
        self.assertFalse(s.rod_tick(b,[],370,2));self.assertIsNone(s.rod)
        self.assertEqual(events[-1]['reason'],'rejoined')
        self.assertFalse(any(o[0]=='group' or o[0]=='move' and o[1]!='Udea' for o in g.orders))

    def test_receipt_without_dk_bag_cannot_claim_purchase_or_loop_forever(self):
        g,b,s,events=self.scene();g.dk.x=0
        g.buy=lambda shop,code:g.orders.append(('fake-buy',code)) or True
        for t in (350,354,358,362):
            s.observe(g,t);s.rod_tick(b,[],t,2)
        self.assertEqual(len(g.orders),3);self.assertIsNone(s.rod)
        self.assertFalse(any(e['event']=='rod_courier_inventory_confirmed' for e in events))
        s.rod_tick(b,[],370,2);self.assertEqual(len(g.orders),3)

    def test_tier_three_stops_restock_but_already_bought_rod_still_rejoins(self):
        for bought in (False,True):
            g,b,s,events=self.scene();s.rod_tick(b,[],350,2)
            if bought:g.bags[g.dk.handle][0]='rnec';g.dk.x=0
            reserved=s.rod_tick(b,[],360,3)
            self.assertEqual(bool(reserved),bought)
            self.assertEqual(bool(s.rod),bought)
            self.assertFalse(any(o[0]=='buy' for o in g.orders))

    def test_threat_missing_route_and_stall_release_assignment(self):
        for why in ('defend','route','stall'):
            g,b,s,events=self.scene();s.rod_tick(b,[],350,2)
            if why=='defend':b.action=Action.DEFEND
            if why=='route':g.path_distance=lambda *a:None
            s.rod_tick(b,[],380,2)
            self.assertIsNone(s.rod)
            old=list(g.orders);s.rod_tick(b,[],381,2);self.assertEqual(g.orders,old)

    def test_lich_present_disables_whole_army_rod_shop_goal(self):
        b,g,army,orders=tempo.TempoTests().opening();dk=army[0]
        lich=unit('Ulic',111,dk.x+100,475);g.my_heroes=lambda:[dk,lich]
        bags={dk.handle:[None]*6,lich.handle:[None]*6};g.inventory=lambda h:bags[h.handle]
        b.economy.opening_rod_allowed=True;b.economy.ready=lambda *a:[b.home]
        b.bank_supply_jobs=lambda *a:[];b.restock_scrolls=lambda *a:None
        b.shop_item=lambda *a:(_ for _ in ()).throw(AssertionError('group restock'))
        b.items(360,2)
        self.assertIsNone(b.shop_goal)


class CHCenterTests(unittest.TestCase):
    def scene(self,x=2176,y=4224):
        b,g,army,orders=opening.CHOpeningTests().scene(x,y)
        dk=army[0];dk.hp=dk.hp_max=875;dk.level=3
        lich=unit('Ulic',91,x+50,575);lich.y=y;lich.hp_max=575
        army=[dk,lich]+[unit('ucry',i,x+100,550) for i in range(120,126)]+[unit('uobs',140,x+120,550)]
        for u in army:u.y=y;u.hp=u.hp_max
        c=b.creeping;c.home_only=True
        return b,g,army,c

    def test_both_spawns_central_camp_waits_for_tier_three_and_lich_orb(self):
        for x,y in ((2176,4224),(-2304,-4736)):
            for tier,orb,allowed in ((2,False,False),(3,False,False),(2,True,False),(3,True,True)):
                b,g,army,c=self.scene(x,y);c.tier=tier
                c.prepare_ch_center(g,army,b.home,600,orb,False)
                self.assertEqual('ch-7' in {a['id'] for a in c.candidates(g,army,b.home,600)},allowed)

    def test_central_stage_precedes_attack_and_clearing_releases_attack_immediately(self):
        b,g,army,c=self.scene();c.tier=3
        s=Situation(600,tier=3,dk=True,lich=True,orb=True,third_hero=True)
        s.pre_attack_camp_pending=c.prepare_ch_center(g,army,b.home,600,True,False)
        self.assertEqual(choose_rule(s),Action.CREEP)
        c.choose(g,army,(b.home.x,b.home.y),b.home,600)
        self.assertEqual(c.active['id'],'ch-7')
        point=(c.active['x'],c.active['y']);c.observe_clear(g,point,650,[])
        s.pre_attack_camp_pending=c.prepare_ch_center(g,army,b.home,650,True,False)
        self.assertTrue(attack_ready(s));self.assertEqual(choose_rule(s),Action.ATTACK)
        self.assertNotIn('ch-7',{a['id'] for a in c.candidates(g,army,b.home,650)})

    def test_no_central_departure_without_dk_reunion_and_no_unbounded_attack_delay(self):
        b,g,army,c=self.scene();c.tier=3;army[0].x+=3000
        self.assertTrue(c.prepare_ch_center(g,army,b.home,600,True,False))
        self.assertNotIn('ch-7',{a['id'] for a in c.candidates(g,army,b.home,600)})
        self.assertFalse(c.prepare_ch_center(g,army,b.home,781,True,False))
        self.assertFalse(c.prepare_ch_center(g,army,b.home,900,True,False))

    def test_current_occupied_central_target_not_dropped_just_because_tier_three(self):
        b,g,army,c=self.scene();c.tier=3;c.prepare_ch_center(g,army,b.home,600,True,False)
        c.active=next(a for a in c.catalog if a['id']=='ch-7')
        point=(c.active['x'],c.active['y']);e=unit('nogl',888,point[0],700);e.y=point[1]
        g.creeps=lambda:[e];c.progress_at=600
        self.assertEqual(c.choose(g,army,point,b.home,601)[0],point)
        self.assertNotIn('ch-7',c.deferred)

    def test_safety_and_other_map_policy_remain_higher_priority(self):
        b,g,army,c=self.scene();c.map_alias='TR';c.tier=3
        self.assertFalse(c.prepare_ch_center(g,army,b.home,600,True,False))
        s=Situation(600,tier=3,lich=True,orb=True,third_hero=True,pre_attack_camp_pending=True)
        s.threatened=True;self.assertEqual(choose_rule(s),Action.DEFEND)
        s.local_enemy_hp=2000;s.army_hp=500
        self.assertEqual(choose_rule(s),Action.RETREAT)

if __name__=='__main__':unittest.main()
