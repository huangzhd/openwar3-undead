import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_scout_opening as opening
import test_scout_regroup_01105 as scout_fixture
from test_micro_loot import unit, dist
from undead.creeping import Creeping


class TMOpeningTests(unittest.TestCase):
    def scene(self):
        catalog=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['TM']
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        b.home=N(x=-4672,y=-3840);dk.x=-2806;dk.y=-2957;dk.level=1;dk.hp=dk.hp_max=675
        skels=[unit('uske',i,dk.x,180) for i in (4,5)]
        for u in skels:u.y=dk.y;u.hp_max=180
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in catalog['starts']])
        c=Creeping(lambda *a,**k:None,catalog['camps']);c.opening_gnoll=True
        return c,g,b.home,dk,skels

    def test_actual_tm_dk_two_skeletons_select_central_green_camp_without_fiend(self):
        c,g,home,dk,skels=self.scene()
        goal,_=c.choose(g,[dk,*skels],(dk.x,dk.y),home,143.405)
        self.assertIsNotNone(goal)
        self.assertEqual(c.active['id'],'tm-12')
        self.assertNotIn('tm-11',[x['id'] for x in c.candidates(g,[dk,*skels],home,143)])

    def test_opening_exception_needs_two_healthy_skeletons_and_healthy_dk(self):
        for case in ('one_skeleton','injured_dk','injured_skeleton'):
            c,g,home,dk,skels=self.scene()
            if case=='one_skeleton':skels.pop()
            if case=='injured_dk':dk.hp=400
            if case=='injured_skeleton':skels[0].hp=40
            self.assertNotIn('tm-12',[x['id'] for x in c.candidates(g,[dk,*skels],home,143)])


class ScoutRouteTests(unittest.TestCase):
    def test_command_follows_safe_first_leg_instead_of_shortcutting_to_final_goal(self):
        g,scout,foe,s=scout_fixture.ScoutSafetyTests().game()
        g.walk_path=lambda a,b:[(0,1000),(2500,1000),b]
        p=s.safe_step(g,scout,(2500,0),1)
        self.assertLessEqual(dist(scout,p),400)
        for i in range(101):self.assertGreaterEqual(dist((p[0]*i/100,p[1]*i/100),foe),799)

    def test_lost_vision_does_not_immediately_forget_observed_guard(self):
        g,scout,foe,s=scout_fixture.ScoutSafetyTests().game()
        s.safe_step(g,scout,(2500,0),1)
        g.creeps=lambda:[]
        p=s.safe_step(g,scout,(2500,0),2)
        self.assertNotEqual(p,(2500,0))
        for i in range(101):self.assertGreaterEqual(dist((p[0]*i/100,p[1]*i/100),foe),799)


if __name__=='__main__':unittest.main()
