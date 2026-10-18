import unittest
from types import SimpleNamespace as N
import test_ch_stage_01135 as stage
import test_creep_tempo_01101 as tempo
import test_support_fan_01122 as support
import test_destroyer_01139 as destroyer
from test_micro_loot import unit


class CHRouteTests(unittest.TestCase):
    def scene(self,north=True):
        b,g,a,c=stage.CHCenterTests().scene(*( (2176,4224) if north else (-2304,-4736)))
        c.cleared=set();c.ch_home_returned=False;c.tier=3;c.ch_orb_ready=True
        g.walk_path=lambda x,y:[x,y]
        return b,g,a,c

    def test_both_spawn_routes_do_not_skip_side_and_lab_for_orb(self):
        for north,opening,shop,side,lab in ((True,{'ch-9','ch-13'},'ch-6',{'ch-0','ch-5'},'ch-14'),
                                           (False,{'ch-8','ch-3'},'ch-10',{'ch-15','ch-11'},'ch-2')):
            b,g,a,c=self.scene(north);c.cleared=opening|{shop}
            ids={p['id'] for p in c.candidates(g,a,b.home,400)}
            self.assertTrue(ids);self.assertLessEqual(ids,side);self.assertNotIn('ch-7',ids)
            c.cleared.add(sorted(side)[0])
            self.assertEqual(c.ch_route_stage(b.home),('laboratory',[lab]))
            self.assertTrue(c.prepare_ch_center(g,a,b.home,450,True,False))
            self.assertIsNone(c.ch_center_started)
            c.cleared.add(lab)
            self.assertEqual(c.ch_route_stage(b.home),('center',['ch-7']))
            c.prepare_ch_center(g,a,b.home,500,True,False)
            self.assertIn('ch-7',{p['id'] for p in c.candidates(g,a,b.home,500)})

    def test_home_is_a_waypoint_and_lab_follows_without_idling(self):
        b,g,a,c=self.scene();c.cleared={'ch-9','ch-13','ch-6','ch-0'}
        home=(b.home.x,b.home.y)
        point,_=c.choose(g,a,(-4291,3287),b.home,410)
        self.assertEqual(point,home);self.assertIsNone(c.active)
        point,_=c.choose(g,a,home,b.home,430)
        self.assertEqual(c.active['id'],'ch-14');self.assertNotEqual(point,home)

    def test_no_statue_uses_remaining_safe_murlocs_instead_of_home_wait(self):
        b,g,a,c=self.scene();c.tier=2;c.ch_orb_ready=False;c.cleared={'ch-9','ch-13','ch-6','ch-0'}
        a=[u for u in a if u.type!='uobs']
        point,_=c.choose(g,a,(-4291,3287),b.home,410)
        self.assertEqual(c.active['id'],'ch-5');self.assertNotEqual(point,(b.home.x,b.home.y))
        e=unit('nmrl',999,point[0],100);e.y=point[1];g.creeps=lambda:[e]
        c.choose(g,a,point,b.home,412)
        self.assertEqual(c.active['id'],'ch-5') # Same support rule on selection and continuation.

    def test_occupied_fallback_is_finished_before_lab_return(self):
        b,g,a,c=self.scene();c.cleared={'ch-9','ch-13','ch-6','ch-0'}
        c.active=next(p for p in c.catalog if p['id']=='ch-5')
        point=(c.active['x'],c.active['y']);e=unit('nmrl',999,point[0],100);e.y=point[1];g.creeps=lambda:[e]
        self.assertEqual(c.choose(g,a,point,b.home,450)[0],point)
        self.assertFalse(c.ch_home_returned)

    def test_route_timeout_is_explicit_skip_not_fake_clear(self):
        b,g,a,c=self.scene();c.cleared={'ch-9','ch-13','ch-6'}
        c.ch_route_waypoint(g,a,(0,0),b.home,400)
        c.ch_route_waypoint(g,a,(0,0),b.home,581)
        self.assertIn('side',c.ch_route_skipped);self.assertFalse({'ch-0','ch-5'}&c.cleared)

    def test_other_maps_do_not_inherit_ch_route(self):
        b,g,a,c=self.scene();c.map_alias='TM'
        self.assertEqual(c.ch_route_stage(b.home),(None,[]))


class RodTests(unittest.TestCase):
    def test_dk_has_initial_rod_and_only_one_confirmed_repurchase(self):
        b,g,dk,bag,buys=tempo.RodTempoTests().make();dk.x=0
        bag[1]='rnec';b.items(200,1)
        self.assertEqual(b.rod_acquisitions['Udea'],1)
        bag[1]=None;b.items(250,1);self.assertEqual(buys,['rnec'])
        bag[1]='rnec';b.items(254,1);bag[1]=None;b.shop_goal=None;b.items(280,1)
        self.assertEqual(buys,['rnec']);self.assertIsNone(b.shop_goal)

    def test_lich_buys_despite_dk_rod_then_does_not_rebuy_after_consumption(self):
        g,b,s,ev=stage.RodCourierTests().scene();g.bags[g.dk.handle][1]='rnec';g.lich.x=0
        s.rod_tick(b,[],350,2);s.observe(g,354);s.rod_tick(b,[],354,2)
        self.assertTrue(s.lich_rod_bought);g.lich.x=g.dk.x;s.rod_tick(b,[],358,2)
        g.bags[g.lich.handle]=[None]*6;s.rod_tick(b,[],400,2)
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)
        self.assertFalse(any(o[0]=='move' and o[1]=='Udea' for o in g.orders))

    def test_wrong_shop_recipient_is_transferred_without_duplicate_buy(self):
        g,b,s,ev=stage.RodCourierTests().scene();g.lich.x=g.dk.x=0
        def buy(shop,code):
            g.bags[g.dk.handle][1]=code;g.orders.append(('buy','Udea',code));return True
        g.buy=buy;s.rod_tick(b,[],350,2);s.observe(g,354);s.rod_tick(b,[],354,2)
        s.observe(g,358);s.rod_tick(b,[],358,2)
        self.assertIn('rnec',g.inventory(g.lich));self.assertIsNone(s.rod)
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)


    def test_lich_reserves_mission_before_gold_arrives_without_recalling_dk(self):
        g,b,s,ev=stage.RodCourierTests().scene();g.gold=80;g.lich.x=0
        self.assertEqual(s.rod_tick(b,[],350,2),{g.lich.handle})
        self.assertFalse(g.orders);self.assertFalse(s.rod['returning'])
        g.gold=150;s.rod_tick(b,[],360,2)
        self.assertIn('rnec',g.inventory(g.lich))

    def test_wrong_recipient_moving_away_does_not_send_lich_back_to_shop(self):
        g,b,s,ev=stage.RodCourierTests().scene();g.lich.x=g.dk.x=0
        def buy(shop,code):
            g.bags[g.dk.handle][1]=code;g.orders.append(('buy','Udea',code));return True
        g.buy=buy;s.rod_tick(b,[],350,2);s.observe(g,354);g.dk.x=1600
        s.rod_tick(b,[],354,2);self.assertEqual(g.orders[-1],('move','Ulic',(1600,0)))
        g.lich.x=600;s.rod_tick(b,[],358,2)
        self.assertEqual(g.orders[-1],('move','Ulic',(1600,0)))
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)


class ManualStatueTests(unittest.TestCase):
    def scene(self):
        b,g,ev=support.StatueTests().scene();u=g.statues[0];h=g.heroes[0]
        g.army=[u,h];u.x=h.x=0;h.hp=400;h.mana=0
        return b,g,u,h,ev

    def test_single_statue_auto_life_plus_manual_alternating_mana(self):
        b,g,u,h,ev=self.scene();b.army_recovery.statues(b,9)
        self.assertIn(('cast',u.handle,'replenishlifeon'),g.orders)
        b.statue_support.tick(b,g.army,[],10)
        b.statue_support.observe_supply(g,14);b.statue_support.tick(b,g.army,[],14)
        self.assertIn(('cast',u.handle,'replenishlife'),g.orders)
        self.assertIn(('cast',u.handle,'replenishmana'),g.orders)
        self.assertFalse(any(o[0]=='move' for o in g.orders))

    def test_after_partner_morph_auto_life_persists_until_replacement_nearby(self):
        b,g,ev=support.StatueTests().scene();first,second=g.statues
        b.army_recovery.statues(b,10);first.type='ubsp';g.orders.clear()
        b.army_recovery.statues(b,14)
        self.assertIn(('cast',second.handle,'replenishlifeon'),g.orders)
        replacement=unit('uobs',999,3000);g.army.append(replacement);g.orders.clear()
        b.army_recovery.statues(b,18)
        self.assertTrue(b.army_recovery.statue_modes[second.handle]['single'])
        self.assertNotIn(('cast',second.handle,'replenishlifeoff'),g.orders)
        replacement.x=second.x;b.army_recovery.statues(b,22)
        self.assertFalse(b.army_recovery.statue_modes[second.handle]['single'])
        self.assertIn(('cast',second.handle,'replenishlifeoff'),g.orders)

    def test_full_health_single_still_manually_restores_mana(self):
        b,g,u,h,ev=self.scene();h.hp=h.hp_max
        b.statue_support.tick(b,g.army,[],10)
        self.assertIn(('cast',u.handle,'replenishmana'),g.orders)

    def test_life_cooldown_does_not_prevent_manual_mana(self):
        b,g,u,h,ev=self.scene();g.cooldown=lambda unit,code:2 if code=='Arpl' else 0
        b.statue_support.tick(b,g.army,[],10)
        self.assertIn(('cast',u.handle,'replenishmana'),g.orders)

    def test_research_waits_for_second_actual_statue_not_queue(self):
        g,e=destroyer.DestroyerEconomyTests().scene();house=g.my_buildings({'uslh'})[0]
        statues=g.units('me',{'uobs'});g.own.remove(statues[-1])
        self.assertFalse(e.research_destroyer(g,[house],500));self.assertFalse(g.commands)
        g.busy[house.handle]=N(kind='queue',queue=['uobs'],progress=.5)
        self.assertFalse(e.research_destroyer(g,[house],505));self.assertFalse(g.commands)
        g.busy.pop(house.handle);g.own.append(statues[-1])
        self.assertTrue(e.research_destroyer(g,[house],510));self.assertEqual(g.commands,['Rusp'])


if __name__=='__main__':unittest.main()
