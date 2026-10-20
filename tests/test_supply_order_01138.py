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

    def test_full_population_after_paid_lich_still_builds_house_before_supply(self):
        g,e=self.scene(25)
        home=g.own[0];home.type='unp1';g.busy.pop(home.handle)
        e.tick(g,300);self.assertEqual(g.commands,['unp2'])
        g.busy[home.handle]=N(kind='upgrade',queue=['unp2'],progress=.1)
        e.tick(g,304);self.assertEqual(g.commands,['unp2','Ulic'])
        g.food+=5
        e.tick(g,308);self.assertEqual([b[1] for b in g.builds],['uslh'])
        house=unit('uslh',999,owner=0);house.x,house.y=g.builds[-1][2:];house.hp=10;g.own.append(house)
        g.busy[house.handle]=N(kind='construction',queue=['uslh'])
        e.tick(g,312);self.assertEqual([b[1] for b in g.builds],['uslh','uzig'])

    def test_paid_lich_alone_does_not_release_third_fiend(self):
        g,e=self.scene(25)
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[2:]]
        g.busy[g.my_buildings({'uaod'})[0].handle]=N(kind='queue',queue=['Ulic'])
        crypt=g.my_buildings({'usep'})[0]
        self.assertFalse(e.train(g,crypt,'ucry',300));self.assertEqual(g.food,25)


if __name__=='__main__':unittest.main()
