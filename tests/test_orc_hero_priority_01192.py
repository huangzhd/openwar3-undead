"""Orc attack and silence priorities shared by training and ordinary matches."""
import unittest
from unittest.mock import Mock

import test_battle_focus_01191 as fixture
from test_baseline import unit
from undead.battle_spells import silence_key_hero
from undead.controller import Controller
from training import TrainingController


class OrcHeroPriorityTests(unittest.TestCase):
    def scene(self, kind):
        b,g,army,foes,orders,events,effects,dk,tc,fs,kodo=fixture.BattleFocusTests().scene(kind)
        heroes={'Otch':tc,'Ofar':fs}
        for code,handle in (('Obla',61),('Oshd',62)):
            hero=unit(code,handle,owner=1,x=400)
            hero.hp=hero.hp_max=1000;hero.has_detail=True;hero.mana=300
            heroes[code]=hero;foes.append(hero)
        return b,g,army,foes,orders,effects,heroes

    def test_all_four_heroes_precede_low_hp_units_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,army,foes,orders,effects,heroes=self.scene(kind)
            for tick,code in enumerate(('Obla','Otch','Ofar','Oshd')):
                now=10+tick*2;orders.clear()
                b.nc_combo.pending=dict(target=foes[0].handle,clock=now)
                self.assertIs(b.hero_pressure.choose(g,army,foes,now),heroes[code])
                b.focus_ranged(army,foes,now)
                shots=[o[2] for o in orders if o[0]=='attack']
                self.assertTrue(shots);self.assertEqual(set(shots),{heroes[code].handle})
                foes.remove(heroes[code])
            b.focus_ranged(army,foes,20)
            self.assertEqual(b.ranged_focus,foes[0].handle)

    def test_unavailable_blademaster_releases_then_reclaims_focus(self):
        for kind in (Controller,TrainingController):
            for reason in ('dead','hidden','no_detail','invulnerable','withdrawn'):
                with self.subTest(kind=kind.__name__,reason=reason):
                    b,g,army,foes,orders,effects,h=self.scene(kind);bm=h['Obla']
                    b.focus_ranged(army,foes,10)
                    if reason=='dead':bm.hp=0;bm.alive=False
                    if reason=='hidden':foes.remove(bm)
                    if reason=='no_detail':bm.has_detail=False
                    if reason=='invulnerable':effects[bm.handle]=['Bvul']
                    if reason=='withdrawn':bm.x=2000
                    orders.clear();b.focus_ranged(army,foes,12)
                    self.assertEqual(b.ranged_focus,h['Otch'].handle)
                    self.assertFalse(any(o[0]=='attack' and o[2]==bm.handle for o in orders))
                    bm.hp=1000;bm.alive=True;bm.has_detail=True;bm.x=400;effects[bm.handle]=[]
                    if reason=='hidden':foes.append(bm)
                    b.focus_ranged(army,foes,14)
                    self.assertEqual(b.ranged_focus,bm.handle)

    def test_farseer_and_shadow_hunter_do_not_require_a_previously_seen_tc(self):
        for kind in (Controller,TrainingController):
            for code in ('Ofar','Oshd'):
                b,g,army,foes,orders,effects,h=self.scene(kind)
                foes[:]=[e for e in foes if not e.is_hero or e is h[code]]
                b.focus_ranged(army,foes,10)
                self.assertEqual(b.ranged_focus,h[code].handle)
                h[code].x=2000;b.focus_ranged(army,foes,12)
                self.assertEqual(b.ranged_focus,foes[0].handle)

    def test_fight_overrides_old_tc_combo_with_blademaster(self):
        for kind in (Controller,TrainingController):
            b,g,army,foes,orders,effects,h=self.scene(kind)
            b.nc_combo.pending=dict(target=h['Otch'].handle,clock=10)
            b.battle_formation.step=Mock(return_value=set())
            b.fight(army,foes,10)
            shots=[o[2] for o in orders if o[0]=='attack']
            self.assertTrue(shots);self.assertEqual(set(shots),{h['Obla'].handle})

    def test_damage_targets_follow_focus_while_silence_targets_tc(self):
        for kind in (Controller,TrainingController):
            for code in ('Obla','Ofar','Oshd'):
                b,g,army,foes,orders,effects,h=self.scene(kind)
                if code!='Obla':
                    foes[:]=[e for e in foes if not e.is_hero or e is h[code]]
                b.combat_spells(army,foes,10)
                novas=[o[3]['target'] for o in orders if o[0]=='cast' and o[2]=='frostnova']
                self.assertEqual(novas,[h[code]])
                if code=='Obla':
                    silence=[o[3]['target'] for o in orders if o[0]=='cast' and o[2]=='silence']
                    self.assertEqual(silence,[h['Otch']])

    def test_blademaster_spell_immunity_does_not_block_physical_focus(self):
        for kind in (Controller,TrainingController):
            b,g,army,foes,orders,effects,h=self.scene(kind)
            effects[h['Obla'].handle]=['Bams']
            b.combat_spells(army,foes,10);b.fight(army,foes,10)
            self.assertFalse(any(o[0]=='cast' and o[2] in {'deathcoil','frostnova'}
                                 and o[3].get('target') is h['Obla'] for o in orders))
            self.assertTrue(any(o[0]=='attack' and o[2]==h['Obla'].handle for o in orders))

    def test_silence_tc_then_shadow_hunter_over_closer_damage_heroes(self):
        for kind in (Controller,TrainingController):
            for reason in ('silenced','immune','hidden','out_of_range'):
                b,g,army,foes,orders,effects,h=self.scene(kind)
                h['Obla'].x=h['Ofar'].x=100;h['Oshd'].x=450
                silence_key_hero(b,army,foes,10)
                self.assertIs(orders[-1][3]['target'],h['Otch'])
                if reason=='silenced':effects[h['Otch'].handle]=['BNsi']
                if reason=='immune':effects[h['Otch'].handle]=['Bams']
                if reason=='hidden':foes.remove(h['Otch'])
                if reason=='out_of_range':h['Otch'].x=2000
                orders.clear();silence_key_hero(b,army,foes,12)
                self.assertIs(orders[-1][3]['target'],h['Oshd'])
                self.assertGreater(b.silence_protected_until[h['Oshd'].handle],12)

    def test_rejected_priority_nova_cannot_bypass_shared_retry_budget(self):
        for kind in (Controller,TrainingController):
            b,g,army,foes,orders,effects,h=self.scene(kind)
            def cast(u,spell,**kwargs):
                orders.append((spell,kwargs.get('target')))
                return spell!='frostnova'
            g.cast=cast
            for now in (10,10.1,12,14,16,100):b.combat_spells(army,foes,now)
            novas=[target for spell,target in orders if spell=='frostnova']
            self.assertEqual(novas,[h['Obla']]*3)
            self.assertTrue(all(target is not h['Otch'] for target in novas))


if __name__=='__main__':unittest.main()
