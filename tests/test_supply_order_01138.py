import unittest
from types import SimpleNamespace as N
import test_economy_timing_01131 as timing
from test_baseline import unit


class SupplyOrderTests(unittest.TestCase):
    def scene(self, food):
        g,e=timing.TransitionBudgetTests().game()
        g.cap=30;g.food=food;g.gold=1500;g.lumber=900
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp1'],progress=.5)
        return g,e

    def test_third_fiend_waits_without_spending_lich_food_or_building_third_tower(self):
        g,e=self.scene(22)
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[2:]]
        e.tick(g,240);e.tick(g,244)
        self.assertFalse(g.commands);self.assertFalse(g.builds)
        self.assertEqual(g.food,22)

    def test_late_tier_two_through_slaughter_foundation_keeps_third_tower_last(self):
        g,e=self.scene(25)
        e.tick(g,280);self.assertFalse(g.commands);self.assertFalse(g.builds)
        home=g.own[0];home.type='unp1';g.busy.pop(home.handle)
        e.tick(g,300);self.assertEqual(g.commands,['unp2']);self.assertFalse(g.builds)
        g.busy[home.handle]=N(kind='upgrade',queue=['unp2'],progress=.1)
        e.tick(g,304);self.assertEqual(g.commands,['unp2','Ulic']);self.assertFalse(g.builds)
        g.food+=5 # Engine charges hero food on accepted recruitment.
        e.tick(g,308);self.assertEqual([b[1] for b in g.builds],['uslh'])
        e.tick(g,312);self.assertEqual([b[1] for b in g.builds],['uslh'])
        house=unit('uslh',999,owner=0);house.hp=10;g.own.append(house)
        g.busy[house.handle]=N(kind='construction',queue=['uslh'])
        e.tick(g,316)
        self.assertEqual([b[1] for b in g.builds],['uslh','uzig'])

    def test_paid_lich_releases_reserved_food_for_reinforcements(self):
        g,e=self.scene(25)
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[2:]]
        g.busy[g.my_buildings({'uaod'})[0].handle]=N(kind='queue',queue=['Ulic'])
        crypt=g.my_buildings({'usep'})[0]
        self.assertTrue(e.train(g,crypt,'ucry',300));self.assertEqual(g.food,28)


if __name__=='__main__':unittest.main()
