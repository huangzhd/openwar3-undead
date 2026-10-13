import unittest
from test_micro_loot import unit
import test_late_defense_0164 as recovery
from undead.policy import Action

class ManaSupportTests(unittest.TestCase):
    def make(self):
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        g.units=lambda side,codes:[u for u in army if u.type in codes]
        g.current_target=lambda u:None
        g.cast=lambda h,spell,target:g.orders.append(('cast',spell,target.handle)) or True
        return g,b,army,dk,lich,moves

    def test_creeping_missing_health_and_escaped_critical_do_not_spend(self):
        g,b,army,dk,lich,_=self.make()
        for hp in (400,100):
            lich.hp=hp;b.heal_allies(army,hp)
        self.assertFalse(g.orders)

    def test_neutral_in_range_rescue_but_not_distant_pursuer(self):
        g,b,army,dk,lich,_=self.make();lich.hp=150
        creep=unit('nogr',99,200);creep.owner=12
        g.creeps=lambda:[creep];g.current_target=lambda u:lich if u is creep else None
        b.heal_allies(army,500)
        self.assertIn(('cast','deathcoil',lich.handle),g.orders)
        g.orders.clear();creep.x=1500;b.heal_allies(army,510)
        self.assertFalse(g.orders)

    def test_damage_trend_rescues_before_fixed_hp_threshold(self):
        g,b,army,dk,lich,_=self.make();lich.hp=300
        b.micro.damage.rates[lich.handle]=80;b.heal_allies(army,500)
        self.assertIn(('cast','deathcoil',lich.handle),g.orders)

    def test_same_snapshot_coil_spend_blocks_departure_until_real_mana(self):
        g,b,army,dk,lich,_=self.make();dk.mana=150;lich.hp=100
        b.player_contact=[unit('hfoo',99,100)]
        b.heal_allies(army,500);b.player_contact=[];lich.hp=600
        g.bags[dk.handle][0]='stwp';g.gold=0
        self.assertFalse(b.prepare_attack(army,500))
        dk.mana=76;self.assertFalse(b.prepare_attack(army,502))
        dk.mana=150;self.assertTrue(b.prepare_attack(army,506))

    def test_initial_home_departure_requires_two_coils(self):
        g,b,army,dk,lich,_=self.make();dk.mana=76;g.gold=0
        self.assertFalse(b.prepare_recovery(army,500))
        dk.mana=150;self.assertTrue(b.prepare_recovery(army,505))

    def test_wrong_recipient_transfers_and_consumes_before_departure(self):
        g,b,army,dk,lich,moves=self.make();dk.mana=76;donor=g.heroes[2]
        donor.x=900;g.bags[donor.handle][0]='pman';g.bags[dk.handle][0]='stwp'
        b.go_raw=lambda units,point,now:moves.append(point)
        self.assertFalse(b.prepare_recovery(army,500));self.assertIn((dk.x,dk.y),moves)
        self.assertIn('pman',g.inventory(donor));self.assertFalse(any(o[0]=='buy' for o in g.orders))
        donor.x=100;b.prepare_recovery(army,503);b.battle_shop.observe(g,505)
        self.assertIn('pman',g.inventory(dk));self.assertNotIn('pman',g.inventory(donor))
        g.effect=True;b.consumables.tick(g,army,[],506,b.cast_until,preparing=True)
        self.assertGreaterEqual(dk.mana,150)
        self.assertTrue(b.prepare_recovery(army,506)) # available mana suffices; no supply wait
        b.consumables.observe(g,507.5)
        self.assertTrue(b.prepare_recovery(army,507.5))

    def test_forward_hero_rejoins_but_rear_hero_and_escape_are_free(self):
        g,b,army,dk,lich,_=self.make();b.enemy_main=(3000,0);lich.x=650
        result=b.hero_support_pullbacks(army,[],500)
        self.assertEqual(result[lich.handle],(dk.x,dk.y))
        lich.x=450;self.assertIn(lich.handle,b.hero_support_pullbacks(army,[],501))
        lich.x=390;self.assertNotIn(lich.handle,b.hero_support_pullbacks(army,[],502))
        lich.x=-900;self.assertNotIn(lich.handle,b.hero_support_pullbacks(army,[],503))
        lich.x=900;self.assertNotIn(lich.handle,b.hero_support_pullbacks(army,[],504,{lich.handle}))
        b.action=Action.RETREAT;self.assertFalse(b.hero_support_pullbacks(army,[],505))

    def test_early_damage_coil_reserve_and_lich_army_transition(self):
        g,b,army,dk,lich,_=self.make();fiends=[u for u in army if u.type=='ucry']
        self.assertTrue(b.creep_damage_coil_allowed([dk,*fiends[:2]],dk))
        dk.mana=149;self.assertFalse(b.creep_damage_coil_allowed([dk,*fiends[:2]],dk))
        dk.mana=300;self.assertFalse(b.creep_damage_coil_allowed([dk,lich,*fiends[:4]],dk))
        lich.x=2000;self.assertTrue(b.creep_damage_coil_allowed([dk,lich,*fiends[:4]],dk))

    def test_carried_ready_bottle_allows_empty_dk_to_depart(self):
        for code in ('pman','pgma','mnst','pres'):
            g,b,army,dk,lich,_=self.make();dk.mana=0;g.gold=0
            g.bags[dk.handle][:2]=['stwp',code]
            self.assertTrue(b.prepare_attack(army,500),code)
            self.assertFalse(any(o[0]=='buy' for o in g.orders))

    def test_other_hero_unknown_or_cooling_bottle_is_not_dk_reserve(self):
        for mode in ('other','cooldown','unknown'):
            g,b,army,dk,lich,_=self.make();dk.mana=0;g.gold=0
            if mode=='other':g.bags[lich.handle][0]='pman'
            else:
                g.bags[dk.handle][0]='pman';g.cd[(dk.handle,'AIm1')]=10 if mode=='cooldown' else None
            self.assertFalse(b.prepare_recovery(army,500),mode)

if __name__=='__main__':unittest.main()
