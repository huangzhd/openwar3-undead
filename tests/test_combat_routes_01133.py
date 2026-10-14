import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_support_fan_01122 as fan_tests
import test_creep_support_01132 as mana_tests
from test_micro_loot import unit,dist
from undead.creeping import Creeping
from undead.policy import Action
from undead.controller import ground_attack_range


class CombatRouteTests(unittest.TestCase):
    def real_creep_guard(self,b,point=(420,0)):
        b.creeping.safe_route=Creeping.safe_route.__get__(b.creeping)
        b.creeping.enemy_main=point

    def test_enemy_base_exclusion_does_not_disable_battle_fan(self):
        b,g,_=fan_tests.FanTests().scene();self.real_creep_guard(b)
        self.assertFalse(b.creeping.safe_route(g,(0,0),(0,200)))
        b.battle_formation.step(b,g.army,g.foes,g.foes[0],10)
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual(len(moves),2)
        self.assertTrue(moves[0][2][1]*moves[1][2][1]<0)

    def test_visible_tower_still_blocks_flank_into_its_fire(self):
        b,g,_=fan_tests.FanTests().scene();self.real_creep_guard(b)
        tower=unit('hgtw',99,-12);tower.y=800;tower.owner=1
        g.foes.append(tower)
        b.battle_formation.step(b,g.army,[g.foes[0]],g.foes[0],10)
        moves=[o for o in g.orders if o[0]=='move']
        self.assertTrue(moves)
        self.assertTrue(all(dist(o[2],tower)>=ground_attack_range(tower.type) for o in moves))

    def test_statues_follow_attack_inside_enemy_base(self):
        b,g,_=fan_tests.StatueTests().scene();self.real_creep_guard(b)
        b.action=Action.ATTACK
        for u in g.statues:u.x=-1100
        b.statue_support.tick(b,g.army,[],10)
        self.assertEqual(len([o for o in g.orders if o[0]=='move']),2)

    def test_peacetime_creeping_and_blocked_terrain_still_reject_path(self):
        b,g,_=fan_tests.StatueTests().scene();self.real_creep_guard(b)
        for u in g.statues:u.x=-1100
        b.action=Action.CREEP;b.statue_support.tick(b,g.army,[],10)
        self.assertFalse(g.orders)
        b.action=Action.ATTACK;g.map=lambda:N(walkable=lambda *a:False)
        b.statue_support.tick(b,g.army,[],15)
        self.assertFalse(g.orders)

    def test_statue_cannot_cross_new_tower_fire_on_combat_route(self):
        b,g,_=fan_tests.StatueTests().scene();self.real_creep_guard(b)
        tower=unit('hgtw',99,0);tower.owner=1
        self.assertIsNone(b.army_recovery.safe_path(b,(-1200,0),(1200,0),[tower],combat=True))

    def test_recorded_stranded_pair_rejoins_in_open_route_model(self):
        b,g,_=fan_tests.StatueTests().scene();self.real_creep_guard(b,(-2304,-4736))
        data=json.loads((Path(__file__).parent/'fixtures/ch-statue-stranded-01133.json').read_text(encoding='utf-8'))
        # Preserve real coordinates/HP/mana; this model tests the region guard,
        # not the recorded map's walls or unknown per-unit max-mana values.
        g.army=[N(**{**r,'handle':tuple(r['handle']),'owner':0,
                     'is_hero':r['type'][0].isupper(),'mana_max':600}) for r in data['sample']['army']]
        g.heroes=[u for u in g.army if u.is_hero];g.foes=[];b.action=Action.ATTACK
        for u in g.army:
            if u.type=='uobs':b.army_recovery.statue_modes[u.handle]={'mode':data['roles'][':'.join(map(str,u.handle))]}
        b.statue_support.tick(b,g.army,[],data['sample']['clock'])
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual({o[1] for o in moves},{u.handle for u in g.army if u.type=='uobs'})
        for _,h,p in moves:
            self.assertLess(dist(p,(-2127,-4807)),dist(g.unit(h),(-2127,-4807)))


class CreepRescueTests(unittest.TestCase):
    def test_dying_expendable_skeleton_does_not_spend_lich_mana(self):
        b,a,dk,lich,e,casts=mana_tests.CreepManaTests().scene()
        dk.mana=0;lich.mana=250
        skeleton=unit('uske',99,120,10);a.append(skeleton)
        b.g.current_target=lambda u:skeleton if u is e else None
        self.assertTrue(b.coil_rescue_needed(skeleton))
        b.fight(a,[e],500)
        self.assertFalse(casts)

    def test_dying_permanent_fiend_still_allows_emergency_nova(self):
        b,a,dk,lich,e,casts=mana_tests.CreepManaTests().scene()
        dk.mana=0;lich.mana=250;victim=a[-1];victim.x=120;victim.hp=10
        b.g.current_target=lambda u:victim if u is e else None
        b.fight(a,[e],500)
        self.assertEqual(casts,[('frostnova','ngnw')])


if __name__=='__main__':unittest.main()
