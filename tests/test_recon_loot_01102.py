import unittest
from types import SimpleNamespace as N
import test_map_pool_0161 as recon
import test_battle_shop_0163 as shopping
from test_micro_loot import FakeLootGame,unit,dist
from test_baseline import FakeGame,unit as worker
from undead.economy import Economy
from undead.loot import Loot

class ReconTests(unittest.TestCase):
    def test_third_unseen_start_beats_expired_nearby_empty_starts(self):
        fixture=recon.ReconTests();g,s,home=fixture.make();s.update(g,home,1)
        missing=(3000,3000);s.checked={p:100 for p in s.points if p!=missing}
        scout=N(x=-2900,y=2900)
        self.assertEqual(s.choose(g,scout,250),missing)
        self.assertIsNone(s.confirmed)

    def test_failed_last_start_waits_bounded_retry_without_repeating_empty_loop(self):
        fixture=recon.ReconTests();g,s,home=fixture.make();s.update(g,home,1)
        missing=(3000,3000);s.checked={p:100 for p in s.points if p!=missing};s.failures[missing]=240
        self.assertIsNone(s.choose(g,home,250))
        self.assertEqual(s.choose(g,home,271),missing)
        self.assertIsNone(s.update(g,home,271))

    def test_dead_scout_replaced_from_extra_worker_and_five_miners_preserved(self):
        g=FakeGame(gold=2000);e=Economy(lambda *a,**k:None)
        e.tick(g,1);old=e.scout;self.assertIsNotNone(old)
        g.own=[u for u in g.own if u.handle!=old];g.commands.clear()
        e.tick(g,5);self.assertIsNone(e.scout);self.assertIn('uaco',g.commands)
        self.assertEqual(len(g.units('me',{'uaco'})),5)
        recruit=worker('uaco',999,owner=0)
        g.own.append(recruit);e.tick(g,9)
        self.assertEqual(e.scout,recruit.handle)
        self.assertEqual(len([u for u in g.units('me',{'uaco'}) if u.handle!=e.scout]),5)

    def test_known_enemy_and_two_exhausted_replacements_stop_extra_scout_spend(self):
        for why in ('known','limit'):
            g=FakeGame(gold=2000);e=Economy(lambda *a,**k:None);e.tick(g,1)
            old=e.scout;g.own=[u for u in g.own if u.handle!=old];g.commands.clear()
            if why=='known':e.enemy_start_known=True
            else:e.scout_losses=2
            e.tick(g,5)
            self.assertIsNone(e.scout);self.assertNotIn('uaco',g.commands)

class LootTests(unittest.TestCase):
    def test_distant_visible_camp_does_not_block_wounded_hero_collecting_cleared_drop(self):
        for code,powerup in [('ratf',False),('tstr',True)]:
            g=FakeLootGame(code);g.hero.hp=g.hero.hp_max*.6;g.item.x=800
            creep=unit('nogr',8,2500);creep.owner=12
            loot=Loot({code:{'powerup':powerup}},lambda *a,**k:None)
            self.assertIsNotNone(loot.tick(g,[g.hero],[creep],1,camp_combat=True))
            self.assertEqual(g.pickups,[code])

    def test_drop_near_secondary_hero_is_not_lost_to_center_or_distant_preferred_hero(self):
        g=FakeLootGame();g.hero.x=0;lich=unit('Ulic',2,1900)
        army=[lich,unit('ucry',3,1900),unit('ucry',4,1950),g.hero]
        picked=[];g.pick_up=lambda h,it:picked.append(h.type) or True
        self.assertIsNotNone(Loot({},lambda *a,**k:None).tick(g,army,[],1))
        self.assertEqual(picked,['Udea'])

    def test_pending_picker_pulled_out_cannot_be_reordered_to_item(self):
        g=FakeLootGame();lich=unit('Ulic',2,200);loot=Loot({},lambda *a,**k:None)
        loot.tick(g,[g.hero],[],1);self.assertEqual(len(g.pickups),1)
        self.assertIsNone(loot.tick(g,[lich],[],4))
        self.assertEqual(len(g.pickups),1);self.assertIsNone(loot.pending)

    def test_nearby_player_or_neutral_combat_still_prevents_wounded_pickup(self):
        for owner in (1,12):
            g=FakeLootGame();g.hero.hp=g.hero.hp_max*.4;foe=unit('ogru',8,200);foe.owner=owner
            self.assertIsNone(Loot({},lambda *a,**k:None).tick(g,[g.hero],[foe],1,camp_combat=True))
            self.assertFalse(g.pickups)

class CloakTests(unittest.TestCase):
    def test_cloak_sale_on_any_hero_needs_real_inventory_change_and_net_refund(self):
        for who in ('dk','lich'):
            for refund in (0,50):
                g,b,s,events=shopping.ShoppingTests().make();h=getattr(g,who);h.x=0;g.bags[h.handle][1]='clsd'
                def sell(hero,slot,shop):
                    g.bags[hero.handle][slot]=None;g.gold+=refund
                    g.orders.append(('sell',hero.type,'clsd'));return True
                g.sell_item=sell
                self.assertTrue(s.sell_nearby(b,g.heroes,[],1))
                g.gold+=20;g.gathered+=20;s.observe(g,5)
                self.assertEqual(events[-1]['event'],'shop_transaction_confirmed' if refund else 'shop_transaction_unconfirmed')
                self.assertNotIn('clsd',g.inventory(h))

    def test_cloak_does_not_recall_army_or_sell_under_fire(self):
        g,b,s,events=shopping.ShoppingTests().make();g.bags[g.dk.handle][1]='clsd';g.dk.x=1000
        self.assertFalse(s.sell_nearby(b,g.heroes,[],1));self.assertFalse(g.orders)
        g.dk.x=0;foe=unit('ogru',8,100)
        self.assertFalse(s.sell_nearby(b,g.heroes,[foe],5));self.assertIn('clsd',g.inventory(g.dk))

if __name__=='__main__':unittest.main()
