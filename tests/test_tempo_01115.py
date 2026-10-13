import unittest,json
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist,FakeLootGame
import test_tm_opening_01112 as tm
import test_late_defense_0164 as recovery
from test_formation import u
from undead.formation import Formation,distance
from undead.loot import Loot
from undead.policy import Action

class TimingTests(unittest.TestCase):
    def test_recovered_attack_does_not_wait_for_six_fiends_statue_or_nova_mana(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        army[:]=[x for x in army if x.type!='uobs'][:7]
        b.creep_strength=army;b.recovery_pending=True;dk.mana=90;lich.mana=30
        self.assertTrue(b.prepare_recovery(army,800));self.assertFalse(moves)

    def test_later_wave_neither_shops_nor_casts_a_second_portal(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        b.attack_portal_spent=True;b.recovery_pending=True
        self.assertTrue(b.prepare_attack(army,900));self.assertFalse(g.orders)
        self.assertFalse(b.emergency_portal(army,901));self.assertFalse(moves)

    def test_two_isolated_fiends_rejoin_heroes_without_recalling_main_body(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make();b.action=Action.ATTACK
        front=[x for x in army if x.type=='ucry'][:2]
        for x in front:x.x=1200
        commands=[];b.go_raw=lambda us,p,n,attack=False:commands.extend((x.handle,p,attack) for x in us)
        remaining=b.regroup_isolated_fiends(army,900)
        self.assertEqual({x[0] for x in commands},{x.handle for x in front})
        self.assertTrue(all(not x[2] and x[1]==(0,0) for x in commands))
        self.assertTrue(all(x not in remaining for x in front));self.assertIn(dk,remaining)

class TMCreepTests(unittest.TestCase):
    def scene(self):
        c,g,home,dk,skels=tm.TMOpeningTests().scene();c.map_alias='TM';c.home_only=True
        c.opening_gnoll=False;c.cleared.add('tm-12');dk.x=-520;dk.y=-2602;dk.level=2
        for s in skels:s.x=dk.x;s.y=dk.y
        return c,g,home,dk,skels

    def test_tm_second_green_without_waiting_for_fiends_and_keeps_goal(self):
        c,g,home,dk,skels=self.scene()
        goal,_=c.choose(g,[dk,*skels],(dk.x,dk.y),home,181)
        self.assertIsNotNone(goal);self.assertTrue(c.central_green_gnoll(c.active))
        self.assertNotEqual(c.active['id'],'tm-12')
        self.assertEqual(c.choose(g,[dk,*skels],(dk.x,dk.y),home,182)[0],goal)

    def test_actual_first_clear_continues_with_level_one_dk_and_remaining_skeletons(self):
        c,g,home,_,_=self.scene()
        fixture=json.loads((Path(__file__).parent/'fixtures/tm-first-clear-01114.json').read_text(encoding='utf-8'))
        army=[N(**{**r,'handle':tuple(r['handle'])}) for r in fixture['own']]
        dk=next(u for u in army if u.type=='Udea')
        self.assertLess(c.strength(army),7)
        goal,_=c.choose(g,army,(dk.x,dk.y),home,fixture['clock'])
        self.assertIsNotNone(goal);self.assertTrue(c.central_green_gnoll(c.active))
        self.assertNotEqual(c.active['id'],'tm-12')

    def test_chain_is_tm_only_and_requires_remaining_healthy_skeleton(self):
        for reason in ('other_map','no_skeleton','hurt_dk'):
            c,g,home,dk,skels=self.scene()
            if reason=='other_map':c.map_alias='TR'
            if reason=='no_skeleton':skels=[]
            if reason=='hurt_dk':dk.hp=100
            self.assertFalse(c.tm_green_chain([dk,*skels],181))

    def test_actual_laboratory_needs_support_against_control_chain(self):
        c,g,home,dk,skels=self.scene();c.tier=2;c.cleared.clear();c.home_only=False
        lab=next(x for x in c.catalog if x['id']=='tm-1');c.catalog=[lab]
        army=[dk,unit('Ulic',20,dk.x),*[unit('ucry',i,dk.x,600) for i in range(30,40)]]
        self.assertFalse(c.candidates(g,army,home,390))
        army.append(unit('uobs',50,dk.x,600))
        self.assertEqual(c.candidates(g,army,home,390),[lab])

class MarchTests(unittest.TestCase):
    def test_forward_fiends_return_without_holding_main_army(self):
        army=[u('Udea',0,0,1),u('Ulic',0,30,2),u('Nbrn',0,-30,3),u('ucry',1200,0,4),u('ucry',1250,0,5)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(4000,0),0,distance,lambda a,b:[b])
        self.assertTrue(all(p[0]<=0 and not hold for x,p,hold in orders if x.type=='ucry'))
        self.assertTrue(all(p==(4000,0) and not hold for x,p,hold in orders if x.is_hero))

    def test_stalled_local_corner_advances_unit_without_resetting_others(self):
        army=[u('Udea',0,0,1),u('ucry',10,0,2)]
        f=Formation(lambda *a,**k:None);route=[(300,0),(500,100),(2000,100)]
        f.plan(army,(2000,100),0,distance,lambda a,b:route)
        orders=f.plan(army,(2000,100),6,distance,lambda a,b:route)
        self.assertTrue(all(p==(500,100) for _,p,_ in orders));self.assertEqual(f.route,route)

class LootSafetyTests(unittest.TestCase):
    def test_attack_phase_collects_visible_cleared_camp_item_and_confirms_inventory(self):
        from undead.controller import Controller
        g=FakeLootGame();events=[];b=Controller(g,lambda e,**kw:events.append(e));b.action=Action.ATTACK
        b.loot=Loot({},b.log);g.creeps=lambda:[]
        self.assertTrue(b.collect_loot([g.hero],[],600,[g.hero]));self.assertEqual(g.pickups,['ratf'])
        g.ground=[];g.inv[0]='ratf';g.hero.item_addrs=[99]
        self.assertFalse(b.collect_loot([g.hero],[],601,[g.hero]))
        self.assertIn('loot_confirmed',events)

    def test_enemy_near_item_outside_army_radius_does_not_lure_picker(self):
        g=FakeLootGame();g.hero.x=0;g.item.x=800;enemy=unit('ogru',99,1100);enemy.owner=1
        self.assertIsNone(Loot({},lambda *a,**k:None).tick(g,[g.hero],[enemy],1))
        self.assertFalse(g.pickups)

if __name__=='__main__':unittest.main()
