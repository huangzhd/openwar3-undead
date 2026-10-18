import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_creep_tempo_01101 as tempo
import test_ch_stage_01135 as stage
from test_micro_loot import unit
from undead.creeping import Creeping
from undead.policy import Situation,attack_ready,choose_rule,Action


class NIRouteTests(unittest.TestCase):
    def scene(self,north=False,strong=False):
        x,y=(6912,3264) if north else (-2752,-3328)
        if strong:b,g,army,_=stage.CHCenterTests().scene(x,y)
        else:b,g,army,_=tempo.TempoTests().opening(x,y)
        m=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['NI']
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in m['starts']])
        c=Creeping(b.log,m['camps']);b.creeping=c;c.map_alias='NI';c.home_only=True
        c.enemy_main=(-2752,-3328) if north else (6912,3264)
        g.walk_path=lambda a,z:[a,z]
        return b,g,army,c

    def test_first_rod_departure_targets_two_fish_at_both_spawns(self):
        for north,expected in ((False,'ni-2'),(True,'ni-15')):
            b,g,a,c=self.scene(north)
            b.creep(a,(b.home.x,b.home.y),145)
            self.assertEqual(c.active['id'],expected)

    def test_mirrored_order_without_statue_and_no_red_mine(self):
        for north,route in ((False,['ni-2','ni-6','ni-4','ni-9']),
                            (True,['ni-15','ni-11','ni-13','ni-8'])):
            b,g,a,c=self.scene(north,True);c.tier=2;a=[u for u in a if u.type!='uobs']
            for i,k in enumerate(route):
                self.assertEqual(c.ni_route_stage(b.home),k)
                self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,200+i*40)},{k})
                c.cleared.add(k)

    def test_real_first_clear_army_can_start_second_camp_without_fiend(self):
        b,g,a,c=self.scene()
        frame=json.loads((Path(__file__).parent/'fixtures/ni_004213_first_camp_army.json').read_text())['frame']
        army=[]
        for r in frame['army']:
            u=unit(r['type'],r['handle'][0],r['x'],r['hp']);u.y=r['y'];u.hp_max=r['hp_max'];u.mana=r['mana'];army.append(u)
        c.cleared={'ni-2'}
        self.assertLess(c.strength(army),8)
        c.choose(g,army,tuple(frame['center']),b.home,170.005)
        self.assertEqual(c.active['id'],'ni-6')

    def test_two_healthy_skeletons_continue_second_small_at_both_spawns(self):
        for north,first,second in ((False,'ni-2','ni-6'),(True,'ni-15','ni-11')):
            b,g,a,c=self.scene(north);c.cleared={first}
            self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,180)},{second})

    def test_uncontested_route_keeps_going_with_injured_hero_and_expiring_skeletons(self):
        b,g,a,c=self.scene();c.cleared={'ni-2'}
        a[0].hp=300;a[1].hp=20
        self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,180)},{'ni-6'})
        c.ni_contested=True
        self.assertFalse(c.candidates(g,a,b.home,180))

    def test_fish_continuation_does_not_fail_for_missing_statue(self):
        b,g,a,c=self.scene();point,_=c.choose(g,a,(b.home.x,b.home.y),b.home,150)
        foe=unit('nmfs',999,point[0],400);foe.y=point[1];g.creeps=lambda:[foe]
        self.assertEqual(c.choose(g,a,point,b.home,152)[0],point)
        self.assertEqual(c.active['id'],'ni-2');self.assertNotIn('ni-2',c.deferred)

    def test_player_interference_restores_health_and_strength_checks(self):
        b,g,a,c=self.scene();c.ni_contested=True;a[0].hp=100
        self.assertFalse(c.candidates(g,a,b.home,150))
        b,g,a,c=self.scene();c.ni_contested=True;c.cleared={'ni-2','ni-4'}
        self.assertFalse(c.candidates(g,a[:1],b.home,230))

    def test_no_murloc_requires_statue_but_strong_camp_still_requires_strength(self):
        b,g,a,c=self.scene();fish=next(p for p in c.catalog if p['id']=='ni-2')
        self.assertFalse(c.needs_support(fish))
        c.catalog=[dict(fish,difficulty=30,hp=4000)]
        self.assertFalse(c.candidates(g,a,b.home,150))

    def test_central_pair_only_after_tier_three_orb_and_before_attack(self):
        for north in (False,True):
            b,g,a,c=self.scene(north,True)
            for tier,orb in ((2,True),(3,False)):
                c.tier=tier;self.assertFalse(c.prepare_ni_center(g,a,b.home,450,orb,False))
                self.assertFalse({'ni-7','ni-10'}&{p['id'] for p in c.candidates(g,a,b.home,450)})
            c.cleared.update(c.ni_opening(b.home));c.tier=3
            self.assertTrue(c.prepare_ni_center(g,a,b.home,500,True,False))
            self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,500)},{'ni-7'})
            c.cleared.add('ni-7')
            self.assertTrue(c.prepare_ni_center(g,a,b.home,550,True,False))
            self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,550)},{'ni-10'})
            c.cleared.add('ni-10')
            self.assertFalse(c.prepare_ni_center(g,a,b.home,600,True,False))

    def test_central_camp_stays_active_outside_own_half(self):
        b,g,a,c=self.scene(True,True);c.cleared.update(c.ni_opening(b.home));c.tier=3
        c.prepare_ni_center(g,a,b.home,500,True,False)
        point,_=c.choose(g,a,(b.home.x,b.home.y),b.home,500)
        self.assertEqual(c.active['id'],'ni-7')
        foe=unit('ngnv',999,point[0],500);foe.y=point[1];g.creeps=lambda:[foe]
        self.assertEqual(c.choose(g,a,point,b.home,502)[0],point)
        self.assertEqual(c.active['id'],'ni-7')

    def test_orb_does_not_abandon_unfinished_camp_or_jump_opening(self):
        b,g,a,c=self.scene(False,True);c.tier=2
        c.choose(g,a,(b.home.x,b.home.y),b.home,400)
        c.tier=3;c.prepare_ni_center(g,a,b.home,500,True,False)
        c.choose(g,a,(b.home.x,b.home.y),b.home,500)
        self.assertEqual(c.active['id'],'ni-2');self.assertNotIn('ni-2',c.cleared)
        self.assertFalse(c.ni_route_skipped)

    def test_timeout_does_not_skip_or_fabricate_clear(self):
        b,g,a,c=self.scene(False,True);c.cleared.update(c.ni_opening(b.home));c.tier=3
        c.prepare_ni_center(g,a,b.home,500,True,False)
        c.prepare_ni_center(g,a,b.home,900,True,False)
        self.assertFalse(c.ni_route_skipped);self.assertNotIn('ni-7',c.cleared)
        self.assertEqual(c.ni_route_stage(b.home),'ni-7')

    def test_attack_and_other_map_release_route_constraints(self):
        b,g,a,c=self.scene(False,True);c.tier=3
        self.assertFalse(c.prepare_ni_center(g,a,b.home,600,True,True))
        self.assertIsNone(c.ni_route_stage(b.home))
        c.map_alias='CH';self.assertFalse(c.prepare_ni_center(g,a,b.home,601,True,False))
        self.assertIsNone(c.ni_route_stage(b.home))

    def test_pre_attack_gate_keeps_defense_and_retreat_priority(self):
        s=Situation(500,tier=3,lich=True,orb=True,third_hero=True,pre_attack_camp_pending=True)
        self.assertFalse(attack_ready(s));s.threatened=True
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.local_enemy_hp=2000;s.army_hp=500
        self.assertEqual(choose_rule(s),Action.RETREAT)


if __name__=='__main__':unittest.main()
