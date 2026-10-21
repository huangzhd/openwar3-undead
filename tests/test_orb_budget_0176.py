import unittest
import test_battle_shop_0163 as shopping
import test_tavern_0145 as tavern
import test_upgrades_portal as macro


class OrbBudgetTests(unittest.TestCase):
    def test_arrived_courier_can_wait_for_income_then_buy_and_deliver(self):
        g,b,s,events=shopping.ShoppingTests().make()
        s.orb_tick(b,g.heroes,[],500,3)
        g.dk.x=0;g.gold=100
        s.orb_tick(b,g.heroes,[],508,3)
        s.orb_tick(b,g.heroes,[],544,3)
        self.assertIsNotNone(s.orb);self.assertFalse(any(o[0]=='buy' for o in g.orders))
        g.gold=375;s.orb_tick(b,g.heroes,[],550,3);s.observe(g,552)
        self.assertIn('ocor',g.inventory(g.dk));self.assertEqual(s.orb_reserve(g),0)
        g.dk.x=g.lich.x;s.orb_tick(b,g.heroes,[],555,3);s.observe(g,557)
        s.orb_tick(b,g.heroes,[],559,3)
        self.assertIn('ocor',g.inventory(g.lich));self.assertIsNone(s.orb)

    def test_shop_wait_remains_bounded_and_real_travel_stall_still_exits(self):
        for arrived in (False,True):
            g,b,s,events=shopping.ShoppingTests().make();s.orb_tick(b,g.heroes,[],500,3)
            if arrived:g.dk.x=0;g.gold=0
            s.orb_tick(b,g.heroes,[],530 if not arrived else 621,3)
            self.assertIsNone(s.orb)
            self.assertFalse(s.orb_tick(b,g.heroes,[],622,3))

    def test_optional_macro_spending_releases_only_after_observed_orb(self):
        g,e=macro.UpgradeTests().make();s=shopping.BattleShop(lambda *a,**k:None)
        g.invs['Ulic']=[None]*6;s.orb=dict(hero=g.my_heroes()[0].handle)
        e.save_for_trade=bool(s.orb_reserve(g));e.tick(g,500)
        self.assertFalse(g.commands)
        g.invs['Ulic'][0]='ocor';e.save_for_trade=bool(s.orb_reserve(g));e.tick(g,505)
        self.assertEqual(g.commands,['Rura'])

    def test_tavern_waits_for_actual_orb_purchase_even_when_both_are_affordable(self):
        b,a,shops,moves,buys,events,res=tavern.TavernTests().setup_game()
        b.g.inventory=lambda h:[None]*6;b.battle_shop.orb=dict(hero=a[0].handle)
        res['gold']=799;b.recruit_tavern(a,[],500,3,set())
        self.assertFalse(moves);self.assertFalse(buys)
        res['gold']=800;b.recruit_tavern(a,[],503,3,set())
        self.assertIsNone(b.tavern_mission);self.assertFalse(moves);self.assertFalse(buys)
        b.g.inventory=lambda h:['ocor'] if h.type=='Udea' else []
        res['gold']=425;b.recruit_tavern(a,[],504,3,set())
        courier=next(u for u in a if u.handle==b.tavern_mission['courier']);courier.x=0
        b.recruit_tavern(a,[],506,3,set())
        self.assertEqual(buys,['Nbrn'])


if __name__=='__main__':unittest.main()
