import unittest
import test_upgrades_portal as portal
import test_late_defense_0164 as recovery
import test_upkeep_bank_0165 as bank
import test_battle_shop_0163 as shop
from undead.policy import Situation,Action

class FormedAttackTests(unittest.TestCase):
    def make(self):
        fixture=portal.PortalTests();g,b,events=fixture.make()
        b.situation=Situation(700,tier=3,lich=True,orb=True,third_hero=True)
        return g,b,fixture

    def test_used_scroll_does_not_freeze_recovery_replacements_in_full_tick(self):
        import test_opening_safety_0131 as opening
        from test_micro_loot import unit
        g,b,dk,allies,orders,clock=opening.EmergencyTests().controller()
        own=g.my_units();home=g.my_buildings()[0];home.type='unp2'
        lich=unit('Ulic',80,0);dark=unit('Nbrn',81,0)
        for h in (lich,dark):h.owner=0
        own.extend([lich,dark]);dk.hp=dk.hp_max
        g.my_heroes=lambda:[dk,lich,dark];g.enemies=lambda:[];g.abilities=lambda h:[]
        g.current_target=lambda u:None
        g.inventory=lambda h:['ocor']+[None]*5 if h is lich else [None]*6
        g.resources=lambda:dict(gold=520,lumber=240,food_used=41,food_cap=70)
        b.action=Action.ATTACK;b.recovery_pending=True
        production=portal.UpgradeGame();production.food=41;production.gold=520;production.lumber=240
        production.invs['Udea']=[None]*6
        fiends=production.units('me',{'ucry'})
        production.own=[u for u in production.own if u not in fiends[3:]]
        b.economy.opening_complete=True
        real_tick=type(b.economy).tick.__get__(b.economy)
        class AfterEconomy(Exception):pass
        def run_economy(_g,now,threat):
            real_tick(production,now,threat)
            raise AfterEconomy()
        b.economy.tick=run_economy
        with self.assertRaises(AfterEconomy):b.tick()
        self.assertTrue(b.situation.orb and b.situation.third_hero)
        self.assertIn('ucry',production.commands)
        self.assertFalse(b.economy.save_for_tp)

    def test_full_tick_frontline_contact_releases_upgrade_funds(self):
        import test_opening_safety_0131 as opening
        for enemy_kind in ('hfoo','htow','distant_building','neutral','absent'):
            with self.subTest(enemy=enemy_kind):
                g,b,dk,allies,orders,clock=opening.EmergencyTests().controller()
                home=g.my_buildings()[0];home.type='unp2';dk.hp=dk.hp_max
                foe=g.enemies()[0];foe.type='hfoo' if enemy_kind=='neutral' else enemy_kind
                if enemy_kind=='distant_building':
                    foe.type='htow';foe.x=800;allies[0].x=400
                foe.owner=15 if enemy_kind=='neutral' else 1
                g.my_heroes=lambda:[dk];g.abilities=lambda h:[];g.inventory=lambda h:[None]*6
                if enemy_kind=='absent':g.enemies=lambda:[]
                production=portal.UpgradeGame();production.gold=250
                production.levels.update(Rura=2,Rucr=0);production.invs['Udea']=[None]*6
                b.economy.opening_complete=True
                real_tick=type(b.economy).tick.__get__(b.economy)
                class AfterEconomy(Exception):pass
                def run_economy(_g,now,threat):
                    real_tick(production,now,threat)
                    raise AfterEconomy()
                b.economy.tick=run_economy
                with self.assertRaises(AfterEconomy):b.tick()
                if enemy_kind in ('hfoo','htow','distant_building'):
                    self.assertIn('Rura',production.commands)
                else:self.assertNotIn('Rura',production.commands)

    def test_unknown_dk_bag_does_not_recall_a_formed_army(self):
        g,b,f=self.make();g.inv[g.dk.handle]=None
        self.assertTrue(b.prepare_attack(g.heroes,700))
        self.assertFalse(f.moves);self.assertFalse(g.purchases);self.assertFalse(b.tp_waiting)

    def test_missing_scroll_full_bag_low_mana_or_no_shop_does_not_delay(self):
        for cause in ('full','no_shop','distant','gold'):
            with self.subTest(cause=cause):
                g,b,f=self.make()
                if cause=='full':g.inv[g.dk.handle]=['rat6']*6
                elif cause=='no_shop':g.shops=[]
                elif cause=='distant':g.dk.x=5000
                elif cause=='gold':g.gold=0
                self.assertTrue(b.prepare_attack(g.heroes,700));self.assertFalse(f.moves)

    def test_nearby_scroll_purchase_does_not_gate_advance_on_receipt(self):
        g,b,f=self.make()
        self.assertTrue(b.prepare_attack(g.heroes,700));self.assertEqual(g.purchases,['stwp'])
        self.assertFalse(f.moves)

    def test_actual_recovery_still_protects_wounded_army(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        b.situation=Situation(700,tier=3,lich=True,orb=True,third_hero=True)
        b.recovery_pending=True;b.creep_strength=army;lich.hp=100
        self.assertFalse(b.prepare_attack(army,700));self.assertTrue(moves)

    def test_invulnerability_restock_does_not_detour_formed_army(self):
        g,b,s,events=shop.ShoppingTests().make()
        g.shop.x=5000
        self.assertTrue(s.prepare_potion(b,g.heroes,[],700,opportunistic=True))
        self.assertFalse(g.orders)

class BankItemTests(unittest.TestCase):
    def test_48_food_finishes_needed_items_before_400_gold_release(self):
        g,e,events=bank.UpkeepTests().make();g.food=48;g.gold=850;e.bank_item_reserve=450
        e.tick(g,700);self.assertFalse(g.commands);self.assertFalse(e.upkeep_released)
        e.bank_item_reserve=0;g.gold=399;e.tick(g,703);self.assertFalse(g.commands)
        g.gold=400;e.tick(g,706);self.assertEqual(g.commands,['ucry']);self.assertEqual(g.food,51)

    def test_nearby_needed_mana_and_one_team_heal_are_budgeted_without_travel(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make();g.food=48;dk.mana=0;b.situation=Situation(700,tier=3,lich=True,orb=True)
        self.assertNotIn('pman',[j[2] for j in b.bank_supply_jobs(700)]) # No actual team orb yet.
        g.bags[lich.handle][0]='ocor'
        jobs=b.bank_supply_jobs(700)
        self.assertEqual([(j[2],j[3]) for j in jobs],[('pman',200),('shea',250)])
        self.assertFalse(moves)
        g.bags[dk.handle][:2]=['pman','shea'];self.assertFalse(b.bank_supply_jobs(701))
        g.bags[dk.handle]=[None]*6
        for h in g.heroes:h.x=5000
        self.assertFalse(b.bank_supply_jobs(702));self.assertFalse(moves)

    def test_carried_mana_stone_avoids_duplicate_blue_potion_budget(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        g.food=48;dk.mana=0;b.situation=Situation(700,tier=3,lich=True,orb=True)
        g.bags[dk.handle][:2]=['mnst','shea']
        self.assertFalse(b.bank_supply_jobs(700));self.assertFalse(moves)
        self.assertFalse(b.battle_shop.prepare_mana(b,army,dk,700));self.assertFalse(moves)

    def test_last_three_food_batch_prioritizes_upgrades_after_formation(self):
        g,e,_=bank.UpkeepTests().make();g.food=48;g.levels['Rura']=0;g.gold=200
        self.assertFalse(e.research_upgrades(g,696))
        e.mass_army=True
        self.assertTrue(e.research_upgrades(g,700));self.assertEqual(g.commands,['Rura'])

if __name__=='__main__':unittest.main()
