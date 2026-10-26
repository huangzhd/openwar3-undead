"""Adaptive shared Orc plans: composition, resources, coordinated fire and safety."""
import unittest
from unittest.mock import Mock
from test_baseline import unit
import test_tc_pressure_01186 as fixture
from undead.controller import Controller
from undead.battle_spells import burst_troops
from training import TrainingController


class BattleStrategyTests(unittest.TestCase):
    def scene(self,kind=Controller,tc_opening=False):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene(kind)
        if not tc_opening:tc.type='Ofar' # Generic dual-plan tests; TC sequence has dedicated V1.80 coverage.
        for u in own[:6]:u.type='ugho';u.hp=u.hp_max=340;u.mana=0
        ghoul=unit('ugho',60,owner=0);ghoul.hp=ghoul.hp_max=340;ghoul.has_detail=True
        own.append(ghoul)
        head=unit('otbk',61,owner=1,x=420);head.hp=head.hp_max=450;head.has_detail=True;foes.append(head)
        for e in foes:
            if e.type=='otbk':e.hp=e.hp_max=450
        foes[0].hp=300
        return b,g,own,foes,orders,events,effects,dk,tc

    def test_ghoul_army_clears_heads_and_shares_spells_in_both_modes(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            b.combat_spells(own,foes,10)
            self.assertEqual(b.hero_pressure.strategy,'army_first')
            spells=[o for o in orders if o[0]=='cast']
            self.assertEqual([o[2] for o in spells],['frostnova'])
            self.assertEqual({o[3]['target'].handle for o in spells},{foes[0].handle})
            b.focus_ghouls([u for u in own if u.type=='ugho'],foes,10)
            shots=[o for o in orders if o[0]=='attack']
            self.assertEqual(len(shots),7);self.assertEqual({o[2] for o in shots},{foes[0].handle})
            self.assertTrue(any(e=='battle_strategy_selected' and d['ghouls']==7 and d['visible_enemy_food']>0 for e,d in events))

    def test_fiend_burst_army_can_choose_hero_first(self):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene()
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,10),tc)
        self.assertEqual(b.hero_pressure.strategy,'hero_first')

    def test_enemy_inventory_and_hero_composition_change_plan(self):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene()
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,10),'hero_first')
        sh=unit('Oshd',88,owner=1,x=500);sh.has_detail=True;sh.mana=200;foes.append(sh)
        g.inventory=lambda u:['pnvl','phea'] if u==tc else []
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,12),'hero_first')
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,17),'army_first')
        reasons=b.hero_pressure.strategy_evidence['reasons']
        self.assertIn('enemy_hero_survival_resources',reasons);self.assertIn('enemy_healing_hero',reasons)

    def test_population_and_damage_shift_choice_without_map_or_level(self):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene()
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,10),'hero_first')
        for i in range(16):
            e=unit('otbk',100+i,owner=1,x=500);e.hp=e.hp_max=450;e.has_detail=True;foes.append(e)
        dk.mana=0
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,17),'army_first')
        self.assertIn('enemy_local_strength',b.hero_pressure.strategy_evidence['reasons'])

    def test_plan_uses_visible_units_not_enemy_resource_queries(self):
        b,g,own,foes,*_=self.scene();g.resources=Mock(side_effect=AssertionError('hidden resources'))
        b.hero_pressure.select_strategy(g,own,foes,10)
        self.assertFalse(g.resources.called)
        before=b.hero_pressure.strategy_evidence['visible_enemy_food']
        e=unit('otbk',99,owner=1,x=5000);foes.append(e)
        b.hero_pressure.select_strategy(g,own,foes,11)
        self.assertEqual(before,b.hero_pressure.strategy_evidence['visible_enemy_food'])

    def test_exposed_hero_interrupts_clear_without_chase_or_invulnerability(self):
        for reason in ('exposed','distant','invulnerable','potion'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene();tc.hp=1
            if reason=='distant':tc.x=1800
            if reason=='invulnerable':effects[tc.handle]=['Bvul']
            if reason=='potion':g.inventory=lambda u:['pnvl'] if u==tc else []
            focus=b.hero_pressure.orc_focus(g,own,foes,10)
            self.assertEqual(focus==tc,reason=='exposed',reason)
            self.assertEqual(b.hero_pressure.strategy,'army_first')

    def test_killing_heads_allows_return_to_heroes_without_six_second_wait(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.orc_focus(g,own,foes,10)
        foes[:]=[tc]
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,11),tc)
        self.assertEqual(b.hero_pressure.strategy,'hero_first')

    def test_healing_and_single_rescue_coil_are_preserved(self):
        for case in ('injured','low_mana'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            lich=next(u for u in own if u.type=='Ulic')
            if case=='injured':lich.hp=100
            else:dk.mana=75
            b.combat_spells(own,foes,10)
            damage=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil' and o[3]['target'] in foes]
            self.assertFalse(damage)
            if case=='injured':self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target']==lich for o in orders))

    def test_nova_alone_prevents_redundant_coil(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();foes[0].hp=100
        b.combat_spells(own,foes,10)
        self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' for o in orders))
        self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))

    def test_troop_spells_respect_immunity_locks_unknown_cooldown_and_range(self):
        for case in ('immune','locked','cooldown','range','silenced'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            if case=='immune':
                for e in foes:effects[e.handle]=['Bams']
            if case=='locked':b.cast_until={u.handle:11 for u in own}
            if case=='cooldown':g.cooldown=lambda *a:None
            if case=='range':
                for e in foes:e.x=2000
            if case=='silenced':
                for u in own:effects[u.handle]=['BNsi']
            burst_troops(b,own,foes,10)
            self.assertFalse(orders,case)

    def test_ghouls_respect_paths_and_protected_tasks(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        g.path_distance=lambda *a:None
        self.assertFalse(b.focus_ghouls(own[:6],foes,10));self.assertFalse(orders)
        g.path_distance=g.dist;b.micro.pulling.add(own[0].handle);b.shopping.add(own[1].handle)
        b.cast_until[own[2].handle]=11;effects[own[3].handle]=['BSTN']
        b.focus_ghouls(own[:6],foes,10)
        self.assertEqual({o[1] for o in orders},{own[4].handle,own[5].handle})

    def test_destroyer_retreats_when_focused_by_anti_air(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind);d=own[8];d.x=100
            g.current_target=lambda u:d if u.type in {'ohun','otbk'} else None
            b.hero_pressure.select_strategy(g,own,foes,10)
            pulls={};b.rear_destroyers(own,foes,10,pulls,None);b.attack_destroyers(own,foes,10,pulls)
            self.assertIn(d.handle,pulls)
            self.assertFalse(any(o[0]=='attack' and o[1]==d.handle for o in orders))

    def test_destroyer_safe_stationary_fire_does_not_chase(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();d=own[8];d.x=-360
        b.hero_pressure.select_strategy(g,own,foes,10)
        grunt=unit('ogru',99,owner=1,x=50);grunt.has_detail=True;foes.append(grunt)
        b.attack_destroyers(own,foes,10)
        self.assertTrue(any(o[0]=='attack' and o[1]==d.handle and o[2]==grunt.handle for o in orders))
        orders.clear();grunt.x=250
        b.attack_destroyers(own,foes,12)
        self.assertFalse(any(o[0]=='attack' and o[1]==d.handle for o in orders))

    def test_finite_hero_spell_finish_temporarily_coordinates_army(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();tc.hp=160
        b.combat_spells(own,foes,10)
        damage=[o for o in orders if o[0]=='cast' and o[2] in {'frostnova','deathcoil'}]
        self.assertTrue(damage);self.assertTrue(all(o[3]['target']==tc for o in damage))
        self.assertTrue(any(e=='battle_hero_opportunity' for e,_ in events))
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,10),tc)
        tc.x=1800
        self.assertIsNot(b.hero_pressure.orc_focus(g,own,foes,11),tc)

    def test_out_of_weapon_range_heads_do_not_restart_tc_pressure(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        for e in foes:
            if e.type=='otbk':e.x=650
        b.combat_spells(own,foes,10)
        damage=[o for o in orders if o[0]=='cast' and o[2] in {'frostnova','deathcoil'}]
        self.assertTrue(damage);self.assertTrue(all(o[3]['target'].type=='otbk' for o in damage))

    def test_rejected_troop_spells_have_a_finite_retry_budget(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();dk.mana=0
        g.cast=lambda u,s,**kw:orders.append(s) or False
        for now in (10,10.5,12,14,16,18):burst_troops(b,own,foes,now)
        self.assertEqual(orders,['frostnova']*3)

    def test_nova_never_adds_coil_after_damage_or_loss_of_visibility(self):
        for case in ('lost','landed'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene();head=foes[0]
            foes[:]=[tc,head]
            def cast(u,spell,**kw):
                orders.append((spell,kw['target'].handle))
                if spell=='frostnova':
                    if case=='lost':foes.remove(head)
                    else:head.hp-=150
                return True
            g.cast=cast
            burst_troops(b,own,foes,10)
            self.assertEqual([o[0] for o in orders],['frostnova'])

    def test_lone_raider_does_not_start_a_six_second_hero_plan(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();battle=list(foes)
        raider=unit('orai',90,owner=1,x=400);raider.has_detail=True
        foes[:]=[raider]
        self.assertIsNone(b.hero_pressure.select_strategy(g,own,foes,19))
        foes[:]=battle
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,20),'army_first')

    def test_new_overwhelming_headhunter_threat_bypasses_switch_delay(self):
        b,g,own,foes,orders,events,effects,dk,tc=fixture.TcFirstTests().scene()
        tc.type='Ofar'
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,10),'hero_first')
        for u in own[:6]:u.type='ugho'
        for i in range(5):
            e=unit('otbk',100+i,owner=1,x=500);e.hp=e.hp_max=450;e.has_detail=True;foes.append(e)
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,11),'army_first')

    def test_equal_scores_keep_existing_plan(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.select_strategy(g,own,foes,10)
        own[:]=[u for u in own if u.is_hero]
        dk.mana=0;foes[:]=[tc,foes[0]]
        self.assertEqual(b.hero_pressure.select_strategy(g,own,foes,20),'army_first')
        self.assertEqual(b.hero_pressure.strategy_evidence['hero_score'],b.hero_pressure.strategy_evidence['army_score'])


if __name__=='__main__':unittest.main()
