import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_tempo_01115 as tempo
from test_formation import u
from undead.formation import Formation,distance


class TMChainRegressionTests(unittest.TestCase):
    def scene(self, index):
        c,g,home,_,_=tempo.TMCreepTests().scene()
        fixture=json.loads((Path(__file__).parent/'fixtures/tm-chain-01118.json').read_text())
        frame=fixture['frames'][index]
        army=[N(**{**u,'handle':tuple(u['handle'])}) for u in frame['own']]
        dk=next(u for u in army if u.type=='Udea')
        return c,g,home,army,dk,frame['clock']

    def test_remaining_skeletons_continue_immediately_without_fiend(self):
        c,g,home,army,dk,now=self.scene(0)
        self.assertFalse(any(u.type=='ucry' for u in army))
        goal,_=c.choose(g,army,(dk.x,dk.y),home,185.15)
        self.assertIsNotNone(goal)
        self.assertTrue(c.central_green_gnoll(c.active))

    def test_fiend_arrival_and_skeleton_expiry_do_not_recall_green_route(self):
        c,g,home,army,dk,now=self.scene(1)
        c.enemy_main=(-3584,4480)
        c.active=next(x for x in c.catalog if x['id']=='tm-10')
        army=[u for u in army if u.type not in {'uske','uskm'}]
        goal,_=c.choose(g,army,(dk.x,dk.y),home,232.205)
        self.assertEqual(goal,(-2322.1,191.03))
        self.assertNotIn('tm-10',c.deferred)

    def test_weak_skeletons_do_not_override_actual_camp_health_check(self):
        c,g,home,army,dk,now=self.scene(0)
        dk.hp=.7*dk.hp_max
        for u in army:
            if not u.is_hero:u.hp=20
        goal,_=c.choose(g,army,(dk.x,dk.y),home,185.15)
        self.assertIsNone(goal)

    def test_new_fiend_follows_without_stopping_dk_and_remaining_skeleton(self):
        dk,skel,fiend=u('Udea',0,0,1),u('uske',0,30,2),u('ucry',-3000,0,3)
        formation=Formation(lambda *a,**k:None)
        formation.plan([dk,skel],(2000,0),180,distance,lambda a,b:[b])
        orders=formation.plan([dk,skel,fiend],(2000,0),181,distance,lambda a,b:[b])
        self.assertTrue(all(not hold for _,_,hold in orders))
        self.assertEqual(next(p for unit,p,_ in orders if unit is dk),(2000,0))
        self.assertGreater(next(p for unit,p,_ in orders if unit is fiend)[0],fiend.x)


if __name__=='__main__':unittest.main()
