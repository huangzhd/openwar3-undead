import unittest
import test_battle_focus_01191 as fixture
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController


class KeyHeroPlanTests(unittest.TestCase):
    def scene(self,kind=Controller):
        data=fixture.BattleFocusTests().scene(kind)
        data[0].hero_pressure.prefer_key_heroes=True
        return data

    def test_new_controllers_enable_default_pressure(self):
        for kind in (Controller,TrainingController):
            self.assertTrue(kind(None,lambda *a,**k:None,2).hero_pressure.prefer_key_heroes)

    def test_third_level_fiend_army_keeps_hero_plan_despite_troop_mass_items_and_low_mana(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene(kind)
            for i in range(8):
                e=unit('otbk',100+i,owner=1,x=410);e.hp=e.hp_max=450;e.has_detail=True;foes.append(e)
            g.inventory=lambda u:['pnvl','phea'] if u==tc else []
            self.assertIs(b.hero_pressure.orc_focus(g,own,foes,10),tc)
            dk.mana=0
            self.assertIs(b.hero_pressure.orc_focus(g,own,foes,20),tc)
            self.assertEqual(b.hero_pressure.strategy,'hero_first')
            orders.clear();b.focus_ranged(own,foes,20)
            self.assertEqual({o[2] for o in orders if o[0]=='attack'},{tc.handle})

    def test_blademaster_attacking_wounded_hero_can_outrank_tc(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        blade=unit('Obla',90,owner=1,x=250);blade.hp=blade.hp_max=1000;blade.has_detail=True;blade.mana=300;foes.append(blade)
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,10),tc)
        lich=own[6];lich.hp=lich.hp_max*.4;g.current_target=lambda u:lich if u==blade else None
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,12),blade)

    def test_key_heroes_depart_then_clear_heads_before_healthy_support_heroes(self):
        for reason in ('dead','fled','hidden','invulnerable'):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
            b.hero_pressure.orc_focus(g,own,foes,10)
            if reason=='dead':tc.hp=0
            if reason=='fled':tc.x=1800
            if reason=='hidden':foes.remove(tc)
            if reason=='invulnerable':effects[tc.handle]=['Bvul']
            target=b.hero_pressure.orc_focus(g,own,foes,12)
            self.assertEqual(target.type,'otbk',reason)
            self.assertEqual(b.hero_pressure.strategy,'army_first')
            if reason!='dead':self.assertNotIn(tc.handle,b.hero_pressure.dead_chiefs)

    def test_exposed_low_hero_gets_finished_during_cleanup_but_not_far_or_protected(self):
        for reason in ('exposed','far','invulnerable','potion'):
            b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
            b.hero_pressure.orc_focus(g,own,foes,10);tc.x=1800;fs.hp=1
            if reason=='far':fs.x=1800
            if reason=='invulnerable':effects[fs.handle]=['Bvul']
            if reason=='potion':g.inventory=lambda u:['pnvl'] if u==fs else []
            chosen=b.hero_pressure.orc_focus(g,own,foes,12)
            self.assertEqual(chosen==fs,reason=='exposed',reason)

    def test_spells_pressure_full_hp_key_hero_and_keep_healing_first(self):
        for kind in (Controller,TrainingController):
            for wounded in (False,True):
                b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene(kind)
                tc.type='Obla';tc.hp=tc.hp_max=1200
                if wounded:own[6].hp=200
                b.combat_spells(own,foes,10)
                coils=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil']
                self.assertTrue(coils)
                self.assertEqual(coils[0][3]['target'],own[6] if wounded else tc)
                self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' and o[3]['target']==tc for o in orders))
                self.assertFalse(any(o[0]=='cast' and o[2] in {'frostnova','deathcoil'} and not o[3]['target'].is_hero for o in orders))

    def test_non_orc_hero_pressure_uses_visible_threat_without_orc_type_order(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        tc.type='Hblm';fs.type='Hpal'
        target=b.hero_pressure.orc_focus(g,own,foes,10)
        self.assertTrue(target.is_hero)
        self.assertEqual(b.hero_pressure.strategy,'hero_first')
        self.assertFalse(b.hero_pressure.key_heroes_seen)

    def test_after_troops_are_gone_pressure_remaining_support_hero(self):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=self.scene()
        b.hero_pressure.orc_focus(g,own,foes,10)
        foes[:]=[fs]
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,12),fs)
        self.assertEqual(b.hero_pressure.strategy,'hero_first')


if __name__=='__main__':unittest.main()
