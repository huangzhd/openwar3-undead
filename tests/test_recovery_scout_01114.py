import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_late_defense_0164 as recovery
import test_scout_opening as opening
import test_scout_regroup_01105 as scouting
import test_rescue_web_march_0144 as portal
from test_micro_loot import dist


class RecoveryDepartureTests(unittest.TestCase):
    def scene(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/tm-recovery-01113.json').read_text(encoding='utf-8'))
        g,b,_,_,_,moves=recovery.RecoveryTests().make()
        own=[]
        for row in fixture['own']:
            u=N(**row);u.handle=tuple(u.handle);u.alive=u.hp>0;own.append(u)
        g.army=own;g.heroes=[u for u in own if u.is_hero]
        g.my_heroes=lambda:g.heroes
        g.units=lambda side,codes:[u for u in own if u.type in codes and u.hp>0]
        g.abilities=lambda u:u.abilities
        g.cooldown=lambda u,code:u.cooldowns.get(code)
        g.buffs=lambda u:u.buffs
        g.bags={u.handle:u.inventory for u in g.heroes}
        b.home=N(x=fixture['home'][0],y=fixture['home'][1]);b.recovery_pending=True
        anchor=min(own,key=lambda u:sum(dist(u,v) for v in own))
        b.creep_strength=[u for u in own if dist(u,anchor)<1200]
        return g,b,own,moves,fixture['clock']

    def test_paused_tm_snapshot_can_depart_without_waiting_for_minor_health_gap(self):
        g,b,army,moves,now=self.scene()
        self.assertTrue(b.prepare_recovery(army,now))
        self.assertFalse(moves);self.assertFalse(b.recovery_pending)

    def test_distant_owned_reinforcement_is_not_a_missing_fiend(self):
        g,b,army,moves,now=self.scene()
        for h in g.heroes:h.hp=h.hp_max
        self.assertLess(sum(u.type=='ucry' for u in b.creep_strength),6)
        self.assertGreaterEqual(sum(u.type=='ucry' for u in army),6)
        self.assertTrue(b.prepare_recovery(army,now));self.assertFalse(moves)

    def test_badly_hurt_or_unrescuable_hero_still_waits(self):
        for case in ('badly_hurt','dk_far','unknown_cooldown','disabled','low_mana'):
            with self.subTest(case=case):
                g,b,army,moves,now=self.scene()
                dk=next(h for h in g.heroes if h.type=='Udea')
                ranger=next(h for h in g.heroes if h.type=='Nbrn')
                if case=='badly_hurt':ranger.hp=ranger.hp_max*.5
                if case=='dk_far':dk.x+=2000
                if case=='unknown_cooldown':g.cooldown=lambda *a:None
                if case=='disabled':dk.buffs=['BPSE']
                if case=='low_mana':dk.mana=74
                self.assertFalse(b.prepare_recovery(army,now))


class ScoutSurvivalTests(unittest.TestCase):
    def test_unseen_public_camp_is_a_route_risk_not_an_observed_guard(self):
        g,scout,foe,s=scouting.ScoutSafetyTests().game()
        g.creeps=lambda:[];g.visible=lambda *p:False
        s.camps=[dict(id='public',spawns=[dict(x=1000,y=0,code='ntrt')])]
        p=s.safe_step(g,scout,(2500,0),1)
        self.assertNotEqual(p,(2500,0));self.assertFalse(s.checked);self.assertFalse(s.neutral_memory)
        for i in range(101):self.assertGreaterEqual(dist((p[0]*i/100,p[1]*i/100),foe),799)

    def test_fairly_visible_empty_static_spawn_does_not_block_scout(self):
        g,scout,_,s=scouting.ScoutSafetyTests().game()
        g.creeps=lambda:[];g.visible=lambda *p:True
        s.camps=[dict(id='public',spawns=[dict(x=1000,y=0,code='ntrt')])]
        self.assertEqual(s.safe_step(g,scout,(2500,0),1),(2500,0))

    def test_confirmed_enemy_start_keeps_scout_forward_even_when_hurt(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        scout=g.unit(b.economy.scout);scout.x=4000;scout.hp=30
        b.start_search.confirmed=b.enemy_main
        b.scout(180)
        self.assertEqual(orders[-1][2],b.enemy_main)
        self.assertIsNotNone(b.economy.scout)


class PortalCoverageTests(unittest.TestCase):
    def test_distant_dk_cannot_rescue_ranger_outside_transport_radius(self):
        g,b,dk,ranger,army,bags,orders,given,events,enemy=portal.EmergencyHandoffTests().make('Nbrn')
        dk.x=-2102;dk.y=-2545;ranger.x=5634;ranger.y=-1895;enemy.x=ranger.x+100;enemy.y=ranger.y
        self.assertFalse(b.emergency_portal(army,603.705))
        self.assertFalse(orders);self.assertFalse(given)

    def test_carrier_can_still_save_itself_when_other_hero_is_remote(self):
        g,b,dk,ranger,army,bags,orders,given,events,enemy=portal.EmergencyHandoffTests().make('Nbrn')
        dk.hp=50;ranger.x=8000;enemy.x=dk.x+50;g.current_target=lambda u:dk if u is enemy else None
        self.assertTrue(b.emergency_portal(army,604))
        self.assertTrue(orders)


if __name__=='__main__':unittest.main()
