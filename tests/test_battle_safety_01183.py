import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock

import test_shared_battle_01181 as shared
import test_support_fan_01122 as support
from test_micro_loot import unit,dist,FakeLootGame
from training import TrainingController
from undead.micro import Micro
from undead.loot import Loot


class UrgentSilenceTests(unittest.TestCase):
    def test_tc_silence_precedes_dispel_and_protects_snapshot_gap(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        tc=foes[2];tc.x=300;effects[tc.handle]=['Broa','Bspe']
        for e in foes[:2]:effects[e.handle]=['Broa']
        b.battle_actions(own,foes,10,{})
        spells=[o for o in orders if o[0]=='cast']
        self.assertEqual(spells[0][2],'silence')
        self.assertIs(spells[0][3]['target'],tc)
        self.assertFalse(any(o[2]=='devourmagic' for o in spells))
        # Still no observed silence in the old snapshot: the accepted order
        # already protects the target until the effect can be observed.
        orders.clear();b.destroyer.tick(b,own,foes,11)
        self.assertFalse(orders)
        effects[tc.handle]=['BNsi','Broa'];b.destroyer.tick(b,own,foes,13)
        self.assertFalse(orders)

    def test_other_safe_buff_cluster_is_still_dispelled_after_tc_silence(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        tc=foes[2];tc.x=300;effects[tc.handle]=['Broa']
        foes[0].x=-300;foes[0].y=500;effects[foes[0].handle]=['Broa']
        b.rear_destroyers=Mock()
        b.battle_actions(own,foes,10,{})
        spells=[o for o in orders if o[0]=='cast']
        silence=next(i for i,o in enumerate(spells) if o[2]=='silence')
        dispel=next(i for i,o in enumerate(spells) if o[2]=='devourmagic')
        self.assertLess(silence,dispel)
        point=spells[dispel][3]
        self.assertGreater(dist((point['x'],point['y']),tc),200)

    def test_far_or_protected_dark_does_not_charge_in_for_tc(self):
        for why in ('far','blocked','cooldown'):
            b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
            if why=='far':foes[2].x=2000
            if why=='cooldown':g.cooldown=lambda u,c:5
            b.battle_actions(own,foes,10,{},blocked={own[7].handle} if why=='blocked' else ())
            self.assertFalse(any(o[0]=='cast' and o[2]=='silence' for o in orders))


class BattleDkEscapeTests(unittest.TestCase):
    def run_scene(self,dk,allies,foes,micro=None,now=10,target=True,walkable=lambda *p:True):
        micro=micro or Micro(lambda *a,**k:None)
        moves=micro.plan([dk,*allies],foes,now,lambda _:dk.handle if target else None,
                         dist,walkable,(-5000,0),lambda e:600 if e.type=='otbk' else 100,
                         aggressive_battle=True)
        return micro,moves

    def test_half_health_dk_escapes_fire_before_target_is_reported(self):
        dk=unit('Udea',1,0,300);ally=unit('ucry',2,-150);enemy=unit('otbk',3,400)
        micro,moves=self.run_scene(dk,[ally],[enemy],target=False)
        self.assertIn(dk.handle,moves)
        self.assertGreaterEqual(dist(moves[dk.handle],enemy),740)
        self.assertLess(moves[dk.handle][0],dk.x)

    def test_safety_overrides_support_leash_and_checks_every_enemy(self):
        dk=unit('Udea',1,1000,300);ally=unit('ucry',2,0)
        enemies=[unit('otbk',3,600),unit('otbk',4,1100)];enemies[1].y=-500
        micro,moves=self.run_scene(dk,[ally],enemies)
        point=moves[dk.handle]
        self.assertGreater(dist(point,ally),750)
        self.assertTrue(all(dist(point,e)>dist(dk,e) for e in enemies))
        self.assertGreaterEqual(min(dist(point,e)-600 for e in enemies),140)

    def test_no_reachable_escape_holds_instead_of_walking_back_into_fire(self):
        dk=unit('Udea',1,0,300);ally=unit('ucry',2,500);enemy=unit('otbk',3,400)
        micro,moves=self.run_scene(dk,[ally],[enemy],walkable=lambda *p:False)
        self.assertEqual(moves[dk.handle],(0,0))

    def test_safe_half_health_dk_waits_for_healing_then_rejoins(self):
        dk=unit('Udea',1,0,300);ally=unit('ucry',2,0);enemy=unit('otbk',3,400)
        micro,moves=self.run_scene(dk,[ally],[enemy])
        dk.x=-800
        _,moves=self.run_scene(dk,[ally],[enemy],micro,15,False)
        self.assertEqual(moves[dk.handle],(-800,0))
        dk.hp=400
        _,moves=self.run_scene(dk,[ally],[enemy],micro,16,False)
        self.assertNotIn(dk.handle,micro.pulling)


class SustainedSupplyTests(unittest.TestCase):
    def test_two_statues_return_to_complementary_roles_after_same_resource_use(self):
        b,g,events=support.StatueTests().scene()
        b.army_recovery.statues(b,1);g.orders.clear()
        for u in g.heroes:u.hp=300;u.mana=100
        for u in g.statues:b.statue_support.last_supply_mode[u.handle]='mana'
        for now in (10,14):
            b.statue_support.tick(b,g.army,[],now)
            casts=[o for o in g.orders if o[0]=='cast']
            self.assertEqual({o[2] for o in casts},{'replenishlife','replenishmana'})
            self.assertEqual(len(casts),2)
            g.orders.clear()

    def test_shared_engagement_never_overwrites_statue_supply_position(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        statue=own[9];statue.x=-1500
        b.engage_battle(own,foes,10)
        self.assertFalse(any(o[1]==statue.handle for o in orders))


class TrainingPotionTests(unittest.TestCase):
    def scene(self,code='phea',full=False):
        g=FakeLootGame(code,full);g.hero.type='Ulic';g.my_heroes=lambda:[g.hero]
        events=[];b=TrainingController(g,lambda e,**k:events.append(e),2)
        b.loot=Loot({code:{'powerup':False}},b.log)
        return b,g,events

    def test_opening_potion_pickup_requires_real_inventory_confirmation(self):
        b,g,events=self.scene()
        self.assertEqual(b.collect_start_potion(1,[g.hero],[]),{g.hero.handle})
        self.assertEqual(g.pickups,['phea']);self.assertNotIn('loot_confirmed',events)
        g.ground=[];g.inv[0]='phea'
        self.assertFalse(b.collect_start_potion(2,[g.hero],[]))
        self.assertIn('loot_confirmed',events)

    def test_opening_rule_ignores_other_items_full_bags_and_danger(self):
        for why in ('other','full','enemy','blocked','timeout','unreachable'):
            b,g,events=self.scene('ratf' if why=='other' else 'phea',why=='full')
            foes=[unit('otbk',8,300)] if why=='enemy' else []
            if why=='unreachable':g.path_distance=lambda *a:None
            b.start_potion_since=0
            self.assertFalse(b.collect_start_potion(21 if why=='timeout' else 1,[g.hero],foes,
                {g.hero.handle} if why=='blocked' else ()))
            self.assertFalse(g.pickups)

    def test_countdown_reserves_picker_but_still_places_other_units(self):
        b,g,events=self.scene();g.hero.alive=True
        ally=unit('ucry',2,0);ally.alive=True
        g.my_units=lambda:[g.hero,ally];g.enemies=lambda:[]
        b.prepare_battle=Mock()
        b.prepare(1)
        self.assertEqual(b.prepare_battle.call_args.kwargs['blocked'],{g.hero.handle})
        self.assertEqual(b.prepare_battle.call_args.kwargs['army'],[g.hero,ally])


if __name__=='__main__':unittest.main()
