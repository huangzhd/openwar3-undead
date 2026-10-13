import unittest
from types import SimpleNamespace as N
import test_tempo_01115 as tempo


class HomeHalfAxisTests(unittest.TestCase):
    def test_north_south_starts_keep_entire_lower_half_including_mercenary(self):
        c,g,home,_,_=tempo.TMCreepTests().scene();c.enemy_main=(-3584,4480)
        self.assertTrue(c.home_half(g,dict(x=6000,y=-500),home))
        self.assertFalse(c.home_half(g,dict(x=-6500,y=700),home))
        merc=next(p for p in c.catalog if p['id']=='tm-14')
        self.assertTrue(c.home_half(g,merc,home))

    def test_reversed_north_south_and_left_right_follow_own_start_side(self):
        c,g,_,_,_=tempo.TMCreepTests().scene()
        c.enemy_main=(-4672,-3840);home=N(x=-3584,y=4480)
        self.assertTrue(c.home_half(g,dict(x=-6500,y=700),home))
        c.enemy_main=(3712,-5056);home=N(x=-4672,y=-3840)
        self.assertTrue(c.home_half(g,dict(x=-800,y=-7000),home))
        self.assertFalse(c.home_half(g,dict(x=0,y=7000),home))
        c.enemy_main=(-4672,-3840);home=N(x=3712,y=-5056)
        self.assertTrue(c.home_half(g,dict(x=0,y=7000),home))

    def test_seen_enemy_offset_uses_verified_start_not_arbitrary_building_midline(self):
        c,g,home,_,_=tempo.TMCreepTests().scene();c.enemy_main=(-3200,4200)
        self.assertTrue(c.home_half(g,dict(x=6000,y=250),home))

    def test_unknown_enemy_does_not_pick_unscouted_opponent_start(self):
        c,g,home,_,_=tempo.TMCreepTests().scene();c.enemy_main=None
        c.resupply_home=False
        self.assertTrue(c.home_half(g,dict(x=0,y=5000),home))
        self.assertIsNone(c.enemy_main)
