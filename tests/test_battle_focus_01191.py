"""Shared focus transitions, buried healing and expendable summon output."""
import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock
import test_tc_pressure_01186 as fixture
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController
from undead.coil import heal_eligible
from undead.scouting import SKELETONS


class BattleFocusTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene(kind)
        fs=unit('Ofar',51,owner=1,x=400);fs.y=70;fs.hp=fs.hp_max=1000;fs.has_detail=True;fs.mana=300
        kodo=unit('okod',52,owner=1,x=350);kodo.hp=1;kodo.has_detail=True;kodo.mana=0
        foes.extend([fs,kodo])
        return b,g,own,foes,orders,events,effects,dk,tc,fs,kodo

    def kill_tc(self,b,g,own,foes,tc):
        b.hero_pressure.orc_focus(g,own,foes,10)
        b.hero_pressure.observe_events([N(kind='unit.died',handle=tc.handle,clock=11)])
        foes.remove(tc)

    def test_tc_then_farseer_then_headhunters_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene(kind)
            b.focus_ranged(own,foes,10);self.assertEqual(b.ranged_focus,tc.handle)
            self.kill_tc(b,g,own,foes,tc)
            b.nc_combo.pending=dict(target=kodo.handle,clock=11)
            b.focus_ranged(own,foes,12);self.assertEqual(b.ranged_focus,fs.handle)
            fs.x=1800
            b.focus_ranged(own,foes,14);self.assertEqual(b.ranged_focus,foes[0].handle)
            self.assertNotEqual(b.ranged_focus,kodo.handle)

    def test_missing_tc_is_not_death_but_releases_focus_to_farseer(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        b.focus_ranged(own,foes,10);foes.remove(tc)
        self.assertIs(b.hero_pressure.choose(g,own,foes,12),fs)
        self.assertFalse(b.hero_pressure.dead_chiefs)

    def test_visible_dead_tc_and_revival(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        tc.hp=0;tc.alive=False
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,12),fs)
        tc.hp=1000;tc.alive=True
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,14),tc)
        self.assertFalse(b.hero_pressure.dead_chiefs)

    def test_farseer_dead_hidden_or_invulnerable_releases_to_heads(self):
        for reason in ('dead','hidden','invul'):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
            self.kill_tc(b,g,own,foes,tc)
            if reason=='dead':fs.hp=0
            if reason=='hidden':foes.remove(fs)
            if reason=='invul':effects[fs.handle]=['Bvul']
            self.assertIs(b.hero_pressure.choose(g,own,foes,12),foes[0])

    def test_fight_ignores_old_kodo_nc_focus(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        self.kill_tc(b,g,own,foes,tc);b.nc_combo.pending=dict(target=kodo.handle,clock=11)
        b.battle_formation.step=Mock(return_value=set())
        b.fight(own,foes,12)
        shooters={u.handle for u in own if u.type in {'ucry','Ulic','Nbrn'}}
        self.assertEqual({o[2] for o in orders if o[0]=='attack' and o[1] in shooters},{fs.handle})

    def test_farseer_gets_nova_before_cluster_after_tc_death(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        self.kill_tc(b,g,own,foes,tc)
        b.combat_spells(own,foes,12)
        novas=[o for o in orders if o[0]=='cast' and o[2]=='frostnova']
        self.assertTrue(novas);self.assertIs(novas[0][3]['target'],fs)

    def test_coil_skips_buried_and_pending_even_in_explicit_rescue_lists(self):
        for kind in (Controller,TrainingController):
            for mode in ('buried','burrowing','unburrowing'):
                b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene(kind)
                fiend=own[0];fiend.hp=50
                if mode=='buried':fiend.type='ucrm'
                else:b.fiend_burrow.pending[fiend.handle]=dict(action=mode)
                self.assertNotIn(fiend,b.heal_candidates(dk))
                b.heal_allies(own,12,[fiend])
                self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))
                fiend.type='ucry';b.fiend_burrow.pending.clear();b.heal_allies(own,14,[fiend])
                self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))
        self.assertFalse(heal_eligible(N(type='ucrm',hp=1,hp_max=600)))

    def test_visible_corpse_can_confirm_death_without_event_but_hidden_cannot(self):
        for visible in (True,False):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
            b.hero_pressure.orc_focus(g,own,foes,10)
            foes.remove(tc);tc.hp=0;tc.alive=False;tc.visible_to=lambda _:visible
            old=g.unit;g.unit=lambda h:tc if h==tc.handle else old(h)
            self.assertIs(b.hero_pressure.orc_focus(g,own,foes,12),fs)
            self.assertEqual(tc.handle in b.hero_pressure.dead_chiefs,visible)

    def test_headhunter_nova_is_not_diverted_to_weak_kodo(self):
        from undead.battle_spells import nova_cluster
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        self.kill_tc(b,g,own,foes,tc);fs.x=1800
        nova_cluster(b,own,foes,12)
        self.assertIs(orders[0][3]['target'],foes[0])

    def test_generic_hero_chase_release_does_not_hold_skeleton(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        sk=self.skeleton(own);g.current_target=lambda u:tc if u is sk else None
        b.stop_hero_chases([sk],12)
        self.assertFalse(orders)

    def skeleton(self,own,code='ndr2'):
        sk=unit(code,60,owner=0,x=0);sk.hp=1;sk.hp_max=300;sk.mana=0;sk.has_detail=True
        own.append(sk);return sk

    def test_all_skeleton_types_keep_attacking_through_low_hp_and_regroup(self):
        for kind in (Controller,TrainingController):
            for code in SKELETONS:
                b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene(kind)
                sk=self.skeleton(own,code)
                b.engage_battle(own,foes,12)
                skorders=[o for o in orders if o[1]==sk.handle]
                self.assertTrue(skorders);self.assertTrue(all(o[0]=='attack' for o in skorders))
                victim=g.unit(skorders[0][2]);old=g.current_target
                g.current_target=lambda u:victim if u is sk else old(u)
                orders.clear();b.go([sk],(-1000,0),14);b.go_raw([sk],(-1000,0),16)
                self.assertFalse(orders) # Preserve approach and swing, no repeated attack/move.

    def test_skeletons_are_not_pulled_or_shield_moved(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        sk=self.skeleton(own);dk.mana=0;effects[sk.handle]=['Blsh']
        b.micro.pulling.add(sk.handle)
        moves=b.micro.plan(own,foes,12,lambda e:sk.handle,g.path_distance,g.map().walkable,(0,0),aggressive_battle=True)
        self.assertNotIn(sk.handle,moves);self.assertNotIn(sk.handle,b.micro.pulling)
        moves=b.shields.plan(own,foes,12,g.buffs,g.map().walkable,g.path_distance)
        self.assertNotIn(sk.handle,moves)

    def test_skeleton_does_not_chase_retreating_hero_when_heads_available(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        sk=self.skeleton(own);g.current_target=lambda u:tc if u is sk else None
        tc.x=900;b.attack_skeletons([sk],foes,12)
        self.assertTrue(orders);self.assertNotEqual(orders[0][2],tc.handle)


if __name__=='__main__':unittest.main()
