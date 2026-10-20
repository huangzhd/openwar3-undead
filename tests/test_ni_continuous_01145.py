import unittest
from types import SimpleNamespace as N
import test_ni_route_01142 as ni
import test_opening_safety_0131 as ticks
from test_micro_loot import unit
from undead.creeping import Creeping
from undead.policy import Action, Situation, choose_rule


class NIContinuousTests(unittest.TestCase):
    def test_complete_mirrored_route_with_weak_subgroups_and_observed_clears(self):
        for north,route in ((False,['ni-2','ni-6','ni-4','ni-9','ni-0','ni-3','ni-7','ni-10']),
                            (True,['ni-15','ni-11','ni-13','ni-8','ni-17','ni-14','ni-7','ni-10'])):
            b,g,a,c=ni.NIRouteTests().scene(north)
            center=(b.home.x,b.home.y);now=150
            for index,expected in enumerate(route):
                if index==4:c.tier=2
                if index==6:
                    c.tier=3;c.prepare_ni_center(g,a,b.home,now,True,False)
                point,_=c.choose(g,a,center,b.home,now)
                self.assertEqual(c.active['id'],expected)
                foe=unit('nogr',999,point[0],3000);foe.y=point[1];foe.owner=12
                g.creeps=lambda:[foe];g.visible=lambda *p:True
                a[0].hp=200
                # Old camp_too_strong and no-progress branches both interrupted here.
                self.assertEqual(c.choose(g,a[:1],point,b.home,now+30)[0],point)
                self.assertEqual(c.choose(g,a[:1],point,b.home,now+60)[0],point)
                self.assertEqual(c.choose(g,a[:1],point,b.home,now+250)[0],point)
                self.assertNotIn(expected,c.deferred)
                self.assertNotIn(expected,c.cleared)
                g.creeps=lambda:[]
                self.assertTrue(c.observe_clear(g,point,now+251,[]))
                center=point;now+=252
            self.assertEqual(c.cleared,set(route))
            self.assertIsNone(c.ni_route_stage(b.home))
            self.assertFalse(c.candidates(g,a,b.home,now))

    def test_no_extra_camps_after_mine_and_no_fake_clear_or_timeout_skip(self):
        b,g,a,c=ni.NIRouteTests().scene()
        c.cleared.update(c.ni_opening(b.home))
        self.assertFalse(c.candidates(g,a,b.home,450))
        moves=[];b.go=lambda army,point,now,attack=False:moves.append(point)
        b.creep(a,(a[0].x,a[0].y),450)
        self.assertTrue(moves)
        self.assertNotEqual(moves[-1],(b.home.x,b.home.y))
        self.assertIsNone(c.active)
        c.cleared.update(c.ni_midgame(b.home));c.tier=3;c.prepare_ni_center(g,a,b.home,500,True,False)
        point,_=c.choose(g,a,(b.home.x,b.home.y),b.home,500)
        g.visible=lambda *p:False
        self.assertFalse(c.observe_clear(g,point,800,[]))
        c.choose(g,a,point,b.home,900)
        self.assertEqual(c.active['id'],'ni-7')
        self.assertFalse(c.ni_route_skipped)

    def test_controller_creep_keeps_main_fighting_when_dk_is_pulling(self):
        b,g,a,c=ni.NIRouteTests().scene();c.cleared={'ni-2'}
        camp=next(p for p in c.catalog if p['id']=='ni-6')
        point=(camp['x'],camp['y']);c.active=camp
        foe=unit('nmfs',999,point[0],2000);foe.y=point[1];foe.owner=12
        g.creeps=lambda:[foe]
        for u in a:u.x=point[0];u.y=point[1];u.hp=30
        b.micro.pulling.add(a[0].handle)
        b.micro.dk_support=dict(handle=a[0].handle,point=(b.home.x,b.home.y))
        self.assertFalse(b.support_dk(a,300))
        actions=[];b.fight=lambda army,foes,now:actions.append(('fight',[u.handle for u in army]))
        b.go=lambda army,goal,now,attack=False:actions.append(('move',goal))
        b.skeleton_opening=lambda *args:False;b.creep_strength=a[:1]
        b.creep(a[1:],point,300)
        self.assertIn(('fight',[u.handle for u in a[1:]]),actions)
        self.assertNotIn(('move',(b.home.x,b.home.y)),actions)
        self.assertEqual(c.active['id'],'ni-6')

    def test_clear_reissues_next_camp_in_same_controller_call(self):
        b,g,a,c=ni.NIRouteTests().scene();c.active=next(p for p in c.catalog if p['id']=='ni-2')
        center=(c.active['x'],c.active['y']);g.creeps=lambda:[];g.visible=lambda *p:True
        actions=[];b.go=lambda army,goal,now,attack=False:actions.append(goal)
        b.creep(a,center,200)
        self.assertEqual(c.active['id'],'ni-6')
        self.assertIn((c.active['x'],c.active['y']),actions)

    def test_temporary_defer_cannot_lock_uncontested_prescribed_camp(self):
        for reason in ('army_not_ready','camp_too_strong','no_movement_or_damage_progress','player_contact'):
            b,g,a,c=ni.NIRouteTests().scene();c.active=next(p for p in c.catalog if p['id']=='ni-2')
            c.defer(180,reason)
            c.choose(g,a,(b.home.x,b.home.y),b.home,181)
            self.assertEqual(c.active['id'],'ni-2')

    def test_enemy_route_and_unreachable_path_are_not_overridden(self):
        for blocked in ('enemy','unreachable'):
            b,g,a,c=ni.NIRouteTests().scene()
            if blocked=='enemy':c.safe_route=lambda *args:False
            else:g.path_distance=lambda *args:None
            self.assertIsNone(c.choose(g,a,(b.home.x,b.home.y),b.home,150)[0])
            self.assertFalse(c.cleared)

    def test_neutral_strength_does_not_force_group_retreat_but_player_pressure_does(self):
        s=Situation(200,local_enemy_hp=3000,army_hp=400,army_health=.3,recent_losses=3,
                    continuous_creeping=True)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.continuous_creeping=False
        self.assertEqual(choose_rule(s),Action.RETREAT)
        s.continuous_creeping=True;s.threatened=True;s.local_enemy_hp=0;s.recent_losses=0
        self.assertEqual(choose_rule(s),Action.DEFEND)

    def test_full_tick_neutral_pressure_keeps_creeping_and_dk_pull_is_individual(self):
        g,b,dk,allies,orders,clock=ticks.EmergencyTests().controller()
        _,_,_,reference=ni.NIRouteTests().scene()
        b.creeping=Creeping(b.log,reference.catalog);b.creeping.map_alias='NI'
        home=g.my_buildings()[0];home.x=-2752;home.y=-3328
        camp=next(p for p in b.creeping.catalog if p['id']=='ni-6')
        b.creeping.cleared={'ni-2'};b.creeping.active=camp
        for u in [dk,*allies]:u.x=camp['x'];u.y=camp['y']
        foe=unit('nmfs',999,dk.x+100,5000);foe.y=dk.y;foe.owner=12
        g.enemies=lambda:[];g.creeps=lambda:[foe];g.visible=lambda *p:True
        g.map=lambda:N(starts=[(-2752,-3328),(6912,3264)],walkable=lambda *p:True)
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
        loot_checks=[]
        b.collect_loot=lambda army,hostiles,now,heroes:loot_checks.append(now) or False
        b.tick()
        self.assertEqual(len(loot_checks),1) # An active NI camp must not bypass visible-drop checks.
        self.assertEqual(b.action,Action.CREEP)
        self.assertTrue(b.situation.continuous_creeping)
        self.assertIn(('creep',[u.handle for u in allies]),orders)
        self.assertTrue(any(o[:2]==('move',dk.handle) for o in orders))
        self.assertFalse(any(o[0]=='portal' for o in orders))
        # The same visible unit now belongs to the enemy player: normal safety
        # takes priority rather than treating actual interference as a creep.
        foe.owner=1;g.enemies=lambda:[foe];g.creeps=lambda:[]
        b.emergency_portal=lambda *a:False
        b.collective_retreat=lambda *a:orders.append(('group-retreat',))
        clock[0]+=6;b.tick()
        self.assertFalse(b.situation.continuous_creeping)
        self.assertEqual(b.action,Action.RETREAT)
        self.assertIn(('group-retreat',),orders)


if __name__=='__main__':unittest.main()
