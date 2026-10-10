import unittest
from types import SimpleNamespace as N
from test_baseline import FakeGame,unit as base_unit
from test_micro_loot import unit,dist
from undead.economy import Economy
from undead.controller import Controller
from undead.creeping import Creeping
from undead.policy import Action,Situation

class OpeningTests(unittest.TestCase):
    def game(self):
        g=FakeGame(gold=2000)
        g.own=[u for u in g.own if u.type not in {'ucry','ugho'}]
        g.own.append(base_unit('ugho',100,owner=0))
        g.inventory=lambda u:[]
        g.resources=lambda:dict(gold=g.gold,lumber=500,food_cap=20,food_used=17)
        e=Economy(lambda *a,**k:None)
        e.build=lambda g,code,home,now:g.commands.append(code) or True
        return g,e

    def test_full_opening_waits_for_actual_units_inventory_and_upgrade(self):
        g,e=self.game();grave=g.my_buildings({'ugrv'})[0];crypt=g.my_buildings({'usep'})[0];home=g.my_buildings({'unpl'})[0]
        g.busy[grave.handle]=N(kind='construction',queue=[]);grave.hp=50
        g.busy[crypt.handle]=N(kind='construction',queue=[]);crypt.hp=50
        e.tick(g,1);self.assertFalse(g.commands);self.assertFalse(e.opening_rod_allowed)
        crypt.hp=100;g.busy.pop(crypt.handle);e.tick(g,5);self.assertEqual(g.commands,['ugho'])
        g.busy[crypt.handle]=N(kind='queue',queue=['ugho'])
        e.tick(g,9);self.assertFalse(e.opening_rod_allowed)
        g.busy.pop(crypt.handle,None);g.own.append(base_unit('ugho',101,owner=0));e.tick(g,13)
        self.assertEqual(g.commands,['ugho','ugho'])
        g.busy[crypt.handle]=N(kind='queue',queue=['ugho']);e.tick(g,17)
        self.assertFalse(e.opening_rod_allowed)
        g.busy.pop(crypt.handle,None);g.own.append(base_unit('ugho',102,owner=0));e.tick(g,21)
        self.assertTrue(e.opening_rod_allowed);self.assertEqual(g.commands,['ugho','ugho'])
        # Accepted shop order is insufficient until DK inventory actually changes.
        e.tick(g,25);self.assertEqual(g.commands,['ugho','ugho'])
        g.inventory=lambda u:['rnec'] if u.type=='Udea' else []
        g.gold=319;e.tick(g,29);self.assertEqual(g.commands,['ugho','ugho'])
        g.gold=320;e.tick(g,33);self.assertEqual(g.commands,['ugho','ugho','unp1'])
        g.busy[home.handle]=N(kind='upgrade',queue=[])
        g.busy[grave.handle]=N(kind='construction',queue=[]);grave.hp=50
        e.tick(g,35);self.assertNotIn('ucry',g.commands)
        g.busy.pop(grave.handle);grave.hp=100;e.tick(g,37)
        self.assertEqual(g.commands,['ugho','ugho','unp1','ucry'])
        g.busy[crypt.handle]=N(kind='queue',queue=['ucry']);e.tick(g,41)
        self.assertEqual(g.commands,['ugho','ugho','unp1','ucry','uzig'])
        g.own.append(base_unit('uzig',103,owner=0));e.tick(g,45)
        self.assertTrue(e.opening_complete)

    def test_ready_crypt_trains_ghoul_before_building_graveyard_or_extra_supply(self):
        g,e=self.game();g.own=[u for u in g.own if u.type!='ugrv']
        e.tick(g,1);self.assertEqual(g.commands,['ugho'])

    def test_controller_cannot_buy_rod_until_ghouls_release_opening_gate(self):
        g,e=self.game();g.dist=dist;g.inventory=lambda h:[None]*6
        b=Controller(g,lambda *a,**k:None);b.home=g.my_buildings({'unpl'})[0]
        purchases=[];b.shop_item=lambda heroes,h,shop,code,now:purchases.append(code) or True
        b.restock_scrolls=lambda *a:None
        b.items(100,1);self.assertFalse(purchases)
        b.economy.opening_rod_allowed=True;b.items(104,1)
        self.assertEqual(purchases,['rnec'])

    def test_late_game_still_recruits_lich_without_replaying_opening(self):
        g=FakeGame(tier=2,gold=425);e=Economy(lambda *a,**k:None)
        e.tick(g,300);self.assertIn('Ulic',g.commands)
        self.assertTrue(e.opening_complete)

class EmergencyTests(unittest.TestCase):
    def controller(self):
        dk=unit('Udea',1,0,100);allies=[unit('ucry',i+2,-i*30,200) for i in range(4)]
        home=unit('unpl',20,-5000);foe=unit('hfoo',30,300,900);foe.owner=1
        own=[dk,*allies,home]
        for u in own:u.owner=0
        # Transport fixtures have no reachable retreat; viable escape is tested separately.
        orders=[];clock=[100]
        g=N(snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own),
            my_buildings=lambda *a:[home],map=lambda:N(starts=[],walkable=lambda *p:False),me=lambda:0,
            my_heroes=lambda:[dk],units=lambda owner,codes:[u for u in own if u.type in codes],
            enemies=lambda:[foe],creeps=lambda:[],my_units=lambda:own,dist=dist,path_distance=dist,
            current_target=lambda u:dk if u is foe else None,inventory=lambda u:['stwp'] if u is dk else [],cooldown=lambda *a:0,
            use_item=lambda h,slot,**kw:orders.append(('portal',h.handle,kw)) or True,
            unit=lambda handle:next((u for u in own if u.handle==handle),None))
        b=Controller(g,lambda *a,**kw:None)
        b.economy.tick=lambda *a:None;b.scout=lambda *a:None;b.skills=lambda *a:None;b.items=lambda *a:None
        b.consumables.tick=lambda *a:None;b.fight=lambda *a:None
        b.creep_aggro.step=lambda *a:None
        return g,b,dk,allies,orders,clock

    def test_emergency_cast_reaches_all_tactics_without_overwriting_caster(self):
        for action in (Action.CREEP,Action.HARASS,Action.ATTACK,Action.DEFEND):
            with self.subTest(action=action):
                g,b,dk,allies,orders,clock=self.controller()
                b.tick(forced=action)
                self.assertEqual(orders[0][0],'portal');self.assertEqual(b.teleport['hero'],dk.handle)
                # Channel survives subsequent controller ticks, and actual home arrival confirms.
                clock[0]+=1;b.tick(forced=action);self.assertEqual(len(orders),1)
                dk.x=-4900
                for ally in allies:ally.x=-4900
                # Avoid normal post-arrival gameplay in this focused transport test.
                b.heal_allies=lambda *a:None;b.frost_armor=lambda *a:None
                b.shields.plan=lambda *a:{};b.support_dk=lambda *a:True
                clock[0]+=3;b.tick(forced=action);self.assertIsNone(b.teleport)

    def test_critical_hero_without_nearby_threat_does_not_trigger_portal(self):
        g,b,dk,allies,orders,clock=self.controller();b.home=unit('unpl',20,-5000)
        b.situation=Situation(100,local_enemy_hp=900,army_health=.8)
        dk.hp=50;g.enemies()[0].x=2000
        self.assertFalse(b.emergency_portal([dk,*allies],100));self.assertFalse(orders)

    def test_rejected_cast_is_throttled_and_cast_protected_carrier_is_skipped(self):
        g,b,dk,allies,orders,clock=self.controller();b.home=unit('unpl',20,-5000)
        b.situation=Situation(100,local_enemy_hp=900,army_health=.4)
        g.use_item=lambda *a,**kw:orders.append('rejected') or False
        b.cast_until[dk.handle]=105
        self.assertFalse(b.emergency_portal([dk,*allies],100));self.assertFalse(orders)
        b.emergency_portal([dk,*allies],106);b.emergency_portal([dk,*allies],107)
        self.assertEqual(orders,['rejected'])

class CreepRouteTests(unittest.TestCase):
    def test_segment_crossing_base_is_rejected_even_when_both_endpoints_are_far(self):
        c=Creeping(lambda *a,**k:None,[]);c.enemy_main=(0,0)
        g=N(dist=dist,walk_path=lambda a,b:[b])
        self.assertFalse(c.safe_route(g,(-2500,0),(2500,0)))
        g.walk_path=lambda a,b:[(-2500,2500),(2500,2500),b]
        self.assertTrue(c.safe_route(g,(-2500,0),(2500,0)))

    def test_safe_alternative_selected_and_active_unsafe_route_abandoned(self):
        bad=dict(id='bad',kind='ogre',x=2500,y=0,max_level=3,hp=500)
        good=dict(id='good',kind='ogre',x=-5000,y=0,max_level=3,hp=500)
        c=Creeping(lambda *a,**k:None,[bad,good]);c.enemy_main=(0,0);c.active=bad
        g=N(dist=dist,path_distance=dist,walk_path=lambda a,b:[b],map=lambda:True,creeps=lambda:[],visible=lambda *p:False)
        goal,_=c.choose(g,[unit('Udea',1,-2500)],(-2500,0),N(x=-5000,y=0),100)
        self.assertEqual(goal,(-5000,0));self.assertIn('bad',c.deferred)

    def test_already_inside_margin_can_leave_but_cannot_cross_deeper(self):
        c=Creeping(lambda *a,**k:None,[]);c.enemy_main=(0,0)
        g=N(dist=dist,walk_path=lambda a,b:[b])
        self.assertTrue(c.safe_route(g,(1000,0),(3000,0)))
        self.assertFalse(c.safe_route(g,(1000,0),(-3000,0)))
        g.walk_path=lambda a,b:None
        self.assertFalse(c.safe_route(g,(2500,0),(4000,0)))

if __name__=='__main__':unittest.main()
