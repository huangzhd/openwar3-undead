import unittest
import test_tavern_0145 as prior
from test_micro_loot import dist
from undead.maps import pool


class PublicTavernTests(unittest.TestCase):
    def test_ni_scouts_actual_public_site_and_waits_for_visible_shop(self):
        b,a,shops,m,buys,ev,res=prior.TavernTests().setup_game()
        shop=shops.pop()
        b.tavern_sites=[(s['x'],s['y']) for s in pool()['NI']['neutral_buildings'] if s['code']=='ntav']
        b.recruit_tavern(a,[],10,3,set())
        courier=next(u for u in a if u.handle==b.tavern_mission['courier'])
        self.assertEqual(m[-1],(courier.handle,(2048,0)))
        courier.x=2048
        b.recruit_tavern(a,[],20,3,set())
        self.assertFalse(buys) # Public coordinates cannot manufacture a shop handle.
        shop.x=2048;shops.append(shop)
        b.recruit_tavern(a,[],23,3,set())
        self.assertEqual(buys,['Nbrn'])
        self.assertFalse(any(e['event']=='tavern_hero_observed' for e in ev))

    def test_multiple_sites_choose_reachable_shortest_path(self):
        b,a,shops,m,buys,ev,res=prior.TavernTests().setup_game()
        shops.clear();b.tavern_sites=[(-1900,0),(4000,0),(1000,0)]
        b.g.path_distance=lambda p,q:None if q==(-1900,0) else dist(p,q)
        b.recruit_tavern(a,[],10,3,set())
        self.assertEqual(m[-1][1],(1000,0))
        self.assertFalse(buys)

    def test_unreachable_public_sites_do_not_dispatch_to_origin(self):
        b,a,shops,m,buys,ev,res=prior.TavernTests().setup_game()
        shops.clear();b.tavern_sites=[(2048,0)]
        b.g.path_distance=lambda p,q:None if q==(2048,0) else dist(p,q)
        b.recruit_tavern(a,[],10,3,set())
        self.assertIsNone(b.tavern_mission);self.assertFalse(m)

    def test_visible_shop_overrides_public_scout_destination(self):
        b,a,shops,m,buys,ev,res=prior.TavernTests().setup_game()
        shop=shops.pop();b.tavern_sites=[(2048,0)]
        b.recruit_tavern(a,[],10,3,set())
        shop.x=1800;shops.append(shop)
        b.recruit_tavern(a,[],13,3,set())
        self.assertEqual(m[-1][1],(1800,0))


if __name__=='__main__':unittest.main()
