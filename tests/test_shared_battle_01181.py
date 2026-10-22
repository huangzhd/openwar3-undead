"""Train/melee parity and evidence-based battlefield behavior."""
import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock

from training import TrainingController
from undead.controller import Controller
from undead.micro import Micro
from undead.battle_spells import nova_cluster
import test_training_orc_focus_01180 as arena
from test_training_orc_focus_01180 import distance


class SharedBattleTests(unittest.TestCase):
    def scene(self, kind=Controller):
        old,g,own,foes,orders,events,effects=arena.TrainingOrcFocusTests().scene()
        b=kind(None,lambda e,**kw:events.append((e,kw)),2)
        b.g=g;b.home=old.home;b.enemy_main=old.enemy_main
        b.action=old.action;b.attack_committed=True
        b.player_contact=foes;b.battle_enemies=foes
        g.walk_path=lambda a,c:[a,c]
        g.abilities=lambda u: ([dict(code='AUfn',level=1)] if u.type=='Ulic' else
                              [dict(code='ANsi',level=1)] if u.type=='Nbrn' else [])
        return b,g,own,foes,orders,events,effects

    def test_training_inherits_the_exact_melee_battle_implementations(self):
        for name in ('prepare_battle','battle_actions','engage_battle','rear_destroyers',
                     'focus_ranged','focus_ghouls','combat_spells','fight'):
            self.assertIs(getattr(TrainingController,name),getattr(Controller,name),name)

    def test_identical_fair_scene_produces_identical_train_and_melee_commands(self):
        runs=[]
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects=self.scene(kind)
            pulls={};b.battle_actions(own,foes,10,pulls)
            b.engage_battle([u for u in own if u.handle not in pulls],foes,10)
            self.assertTrue(any(o[0]=='cast' and o[2]=='silence' for o in orders))
            self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' for o in orders))
            self.assertFalse(any(o[0]=='attack' and o[1]==own[8].handle for o in orders))
            normalized=[o[:3]+({k:getattr(v,'handle',v) for k,v in o[3].items()},)
                        if o[0]=='cast' else o for o in orders]
            runs.append((normalized,pulls))
        self.assertEqual(*runs)

    def test_non_tc_pipeline_dispels_then_waits_for_buff_removal_before_silence(self):
        b,g,own,foes,orders,events,effects=self.scene()
        chief=foes[2];chief.type='Oshd';chief.x=300;effects[chief.handle]=['Broa']
        own[8].x,own[8].y=-420,-220 # Safe rear flank; the area still reaches SH.
        b.battle_actions(own,foes,10,{})
        spells=[o[2] for o in orders if o[0]=='cast']
        self.assertIn('devourmagic',spells);self.assertNotIn('silence',spells)
        effects[chief.handle]=[];orders.clear()
        g.cooldown=lambda u,code:5 if code in {'Advm','AUfn'} else 0
        b.battle_actions(own,foes,12,{})
        self.assertIn('silence',[o[2] for o in orders if o[0]=='cast'])
        effects[chief.handle]=['BNsi','Broa'];orders.clear()
        b.battle_actions(own,foes,14,{})
        self.assertFalse(any(o[0]=='cast' and o[2] in {'silence','devourmagic'} for o in orders))

    def test_cluster_nova_respects_immunity_isolation_and_finisher_reservation(self):
        for reason in ('isolated','immune','finisher','pulling','unknown_cooldown'):
            with self.subTest(reason=reason):
                b,g,own,foes,orders,events,effects=self.scene();blocked=set()
                if reason=='isolated':foes[1].x=900
                if reason=='immune':effects[foes[1].handle]=['Bams']
                if reason=='finisher':b.nc_combo.pending=dict(target=foes[2].handle,clock=10)
                if reason=='pulling':blocked.add(own[6].handle)
                if reason=='unknown_cooldown':g.cooldown=lambda *a:None
                nova_cluster(b,own,foes,10,blocked)
                self.assertFalse(orders)

    def test_live_ranged_threat_beats_low_hp_melee_until_hero_finisher(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes[2].type='Hpal' # Preserve the unchanged non-Orc targeting policy.
        melee=N(**vars(foes[0]));melee.type='ogru';melee.handle=(99,0);melee.hp=1
        foes.append(melee)
        g.current_target=lambda u:own[0] if u.handle==foes[0].handle else None
        b.focus_ranged(own,foes,10)
        self.assertEqual(b.ranged_focus,foes[0].handle)
        foes[2].hp=1;orders.clear();b.focus_ranged(own,foes,12)
        self.assertEqual(b.ranged_focus,foes[2].handle)

    def test_shared_group_releases_unreachable_hero_and_bounds_rejected_attacks(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes[2].hp=1;b.focus_ranged(own,foes,10)
        self.assertEqual(len(b.hero_attack_targets),8)
        foes[2].x=1800;orders.clear();b.engage_battle(own,[],12)
        self.assertEqual(len([o for o in orders if o[0]=='hold']),8)
        self.assertFalse(b.hero_attack_targets)
        g.attack=lambda *a,**kw:False
        for t in (14,16,18):b.focus_ranged(own,foes,t)
        self.assertFalse(b.combat_progress.allowed(foes[0],18))

    def test_precontact_layout_is_bounded_and_does_not_restart_during_fire(self):
        b,g,own,foes,orders,events,effects=self.scene(TrainingController)
        for e in foes:e.x=1000
        b.combat_spells=Mock();b.destroyer.tick=Mock()
        b.battle_actions(own,foes,10,{})
        self.assertLessEqual(len([o for o in orders if o[0]=='move']),2)
        self.assertTrue(any(e=='battle_prebattle_layout' for e,_ in events))
        for e in foes:e.x=400
        orders.clear();b.battle_actions(own,foes,11,{})
        self.assertFalse(any(o[0]=='move' and o[1]!=own[8].handle for o in orders))

    def test_real_battle_uses_training_risk_profile_but_creeping_does_not(self):
        for code in ('Ulic','Nbrn'):
            b,g,own,foes,orders,events,effects=self.scene()
            hero=next(u for u in own if u.type==code);hero.hp=300
            args=([hero,own[0]],[foes[0]],10,lambda _:hero.handle,distance,lambda *p:True,(-2000,0))
            battle=Micro(lambda *a,**kw:None)
            self.assertNotIn(hero.handle,battle.plan(*args,coil_ready=False,aggressive_battle=True))
            creep=Micro(lambda *a,**kw:None)
            self.assertIn(hero.handle,creep.plan(*args,coil_ready=False,creeping=True,aggressive_battle=True))
            hero.hp=100
            self.assertIn(hero.handle,battle.plan(*args,coil_ready=False,aggressive_battle=True))

    def test_extreme_profile_still_reacts_to_fatal_burst(self):
        b,g,own,foes,orders,events,effects=self.scene();hero=own[6]
        micro=Micro(lambda *a,**kw:None)
        def step(t):return micro.plan([hero,own[0]],[foes[0]],t,lambda _:hero.handle,
                                     distance,lambda *p:True,(-2000,0),coil_ready=False,aggressive_battle=True)
        hero.hp=500;step(10);hero.hp=300
        self.assertIn(hero.handle,step(10.5))


if __name__=='__main__':unittest.main()
