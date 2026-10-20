import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_th_route_01152 as th
import test_opening_safety_0131 as ticks
import test_drop_priority_0185 as drops
from test_micro_loot import unit
from undead.creeping import Creeping
from undead.policy import Action


class THContinuousTests(unittest.TestCase):
    def test_real_first_camp_army_immediately_departs_for_433(self):
        b,g,a,c=th.THRouteTests().scene()
        frame=json.loads((Path(__file__).parent/'fixtures/th_191002_first_camp_army.json').read_text())['frame']
        army=[]
        for row in frame['army']:
            u=unit(row['type'],row['handle'][0],row['x'],row['hp'])
            u.y=row['y'];u.hp_max=row['hp_max'];u.mana=row['mana'];army.append(u)
        self.assertLess(c.strength(army),6)
        c.active=next(p for p in c.catalog if p['id']=='th-8')
        g.creeps=lambda:[];g.visible=lambda *args:True
        moves=[];b.go=lambda army,point,now,attack=False:moves.append(point)
        b.creep(army,tuple(frame['center']),183.975)
        self.assertIn('th-8',c.cleared);self.assertEqual(c.active['id'],'th-2')
        self.assertEqual(moves,[(c.active['x'],c.active['y'])])

    def test_both_routes_continue_without_statue_tech_or_strength_wait(self):
        for north in (True,False):
            b,g,a,c=th.THRouteTests().scene(north)
            route=c.th_route(b.home);c.cleared.add(route[0]);center=(b.home.x,b.home.y)
            g.visible=lambda *args:True
            for i,k in enumerate(route[1:]):
                point,_=c.choose(g,a[:1],center,b.home,250+i*3)
                self.assertEqual(c.active['id'],k)
                self.assertTrue(c.observe_clear(g,point,251+i*3,[]));center=point
            self.assertIsNone(c.th_route_stage(b.home))

    def test_stall_retries_remain_bounded_and_player_contact_restores_safety(self):
        b,g,a,c=th.THRouteTests().scene();c.cleared.add('th-8')
        c.th_contested=True
        self.assertIsNone(c.choose(g,a,(b.home.x,b.home.y),b.home,200)[0])
        c.th_contested=False;g.path_distance=lambda *args:None
        for now in (201,292,400):c.choose(g,a,(b.home.x,b.home.y),b.home,now)
        self.assertIn('th-2',c.exhausted);self.assertNotIn('th-2',c.cleared)
        self.assertEqual(c.failures['th-2'],2)

    def test_full_tick_neutral_pressure_keeps_main_fighting_while_dk_pulls(self):
        g,b,dk,allies,orders,clock=ticks.EmergencyTests().controller()
        _,_,_,reference=th.THRouteTests().scene()
        b.creeping=Creeping(b.log,reference.catalog);b.creeping.map_alias='TH'
        home=g.my_buildings()[0];home.x=-3904;home.y=2880
        camp=next(p for p in b.creeping.catalog if p['id']=='th-2')
        b.creeping.cleared={'th-8'};b.creeping.active=camp
        for u in [dk,*allies]:u.x=camp['x'];u.y=camp['y']
        foe=unit('nsgn',999,dk.x+100,5000);foe.y=dk.y;foe.owner=12
        g.enemies=lambda:[];g.creeps=lambda:[foe];g.visible=lambda *p:True
        g.map=lambda:N(starts=[(-3904,2880),(2880,-3904)],walkable=lambda *p:True)
        g.walk_path=lambda a,z:[a,z];g.current_target=lambda u:dk if u is foe else None
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        b.micro.plan=lambda *args,**kwargs:{dk.handle:(dk.x-300,dk.y)}
        b.shields.plan=lambda *a:{};b.frost_armor=lambda *a:None
        b.combat_spells=lambda *a:None;b.hero_support_pullbacks=lambda *a:{}
        b.recruit_tavern=lambda *a:set();b.recover_missing_heroes=lambda *a:False
        b.battle_shop.rod_tick=lambda *a:set();b.battle_shop.orb_tick=lambda *a:set()
        b.first_attack_supply.tick=lambda *a:set();b.battle_shop.sell_nearby=lambda *a:False
        b.escort_tavern=lambda *a:False;b.stop_hero_chases=lambda *a:None
        b.creep=lambda army,center,now:orders.append(('creep',[u.handle for u in army]))
        b.collect_loot=lambda *a:False
        b.tick()
        self.assertEqual(b.action,Action.CREEP)
        self.assertTrue(b.situation.continuous_creeping)
        self.assertIn(('creep',[u.handle for u in allies]),orders)
        self.assertTrue(any(o[:2]==('move',dk.handle) for o in orders))
        foe.owner=1;g.enemies=lambda:[foe];g.creeps=lambda:[]
        b.emergency_portal=lambda *a:False
        b.collective_retreat=lambda *a:orders.append(('group-retreat',))
        clock[0]+=6;b.tick()
        self.assertFalse(b.situation.continuous_creeping)
        self.assertEqual(b.action,Action.RETREAT)
        self.assertIn(('group-retreat',),orders)


class THSeaGiantTests(unittest.TestCase):
    def scene(self):
        b,own,carrier,other,orders,targets=drops.DropPriorityTests().make()
        b.creeping.map_alias='TH'
        giant=unit('nsgn',82,740,350);giant.owner=12
        b.creeping.catalog[0]['spawns'].append(dict(code='nsgn',x=740,y=0))
        b.creeping.observe_drop_carriers(b.g,[giant])
        b.g.creeps=lambda:[carrier,other,giant]
        return b,own,carrier,other,giant,orders,targets

    def test_fair_visible_sea_giant_overrides_carrier_and_low_hp_creep(self):
        b,own,c,o,giant,orders,targets=self.scene()
        b.fight(own,[o],10)
        self.assertTrue(orders)
        self.assertTrue(all(targets.get(u.handle) is giant for u in own))
        giant.hp=0;b.fight(own,[c,o,giant],12)
        self.assertTrue(all(targets.get(u.handle) is c for u in own))

    def test_no_chasing_hidden_distant_or_other_camp_giant_and_no_other_map_change(self):
        for why in ('hidden','distant','other_camp','other_map'):
            b,own,c,o,giant,orders,targets=self.scene()
            if why=='hidden':b.g.creeps=lambda:[c,o]
            if why=='distant':giant.x=1600
            if why=='other_camp':b.creeping.drop_camps[giant.handle]=99
            if why=='other_map':b.creeping.map_alias='NI'
            b.fight(own,[o],10)
            self.assertTrue(all(targets.get(u.handle) is c for u in own),why)

    def test_player_contact_overrides_neutral_priority(self):
        b,own,c,o,giant,orders,targets=self.scene()
        enemy=unit('hfoo',90,50,400);enemy.owner=1
        b.fight(own,[o,giant,enemy],10)
        self.assertTrue(all(targets.get(u.handle) is enemy for u in own))

    def test_first_skeleton_pull_targets_giant_before_carrier(self):
        b,own,c,o,giant,orders,targets=self.scene()
        b.action=Action.CREEP;b.attack_committed=False
        skeleton=unit('uske',83,580,180);skeleton.hp_max=180
        b.go_raw=lambda *a:None
        self.assertTrue(b.skeleton_opening([*own,skeleton],[c,o,giant],10))
        self.assertIs(targets[skeleton.handle],giant)


if __name__=='__main__':unittest.main()
