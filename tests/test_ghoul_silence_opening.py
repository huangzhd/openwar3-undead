"""Observed Silence gates the ghoul charge and NC in both controllers."""
import unittest
import test_battle_strategy_01201 as fixture
from undead.controller import Controller
from training import TrainingController
from undead.ghoul_tc import opening_target, retreat_ghouls


class GhoulSilenceTests(unittest.TestCase):
    def scene(self, kind=Controller):
        scene = fixture.BattleStrategyTests().scene(kind, tc_opening=True)
        scene[0].hero_pressure.prefer_key_heroes = True
        return scene

    def test_retreat_then_observed_silence_nc_and_charge_in_both_modes(self):
        for kind in (Controller, TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc = self.scene(kind)
            dogs = [u for u in own if u.type == 'ugho']
            pulls = {};b.battle_actions(own,foes,10,pulls)
            self.assertTrue(all(u.handle in pulls for u in dogs))
            for u in dogs:
                self.assertGreater(g.dist(pulls[u.handle],tc),g.dist(u,tc))
                b.go_raw([u],pulls[u.handle],10)
            self.assertEqual(sum(o[0]=='hold_after' for o in orders),len(dogs))
            self.assertFalse(any(o[0]=='cast' and o[2] in {'deathcoil','frostnova'} for o in orders))
            # A successful receipt alone still cannot release the charge.
            orders.clear();pulls={};b.battle_actions(own,foes,10.5,pulls)
            self.assertTrue(all(u.handle in pulls for u in dogs))
            effects[tc.handle]=['BNsi'];orders.clear();pulls={}
            b.battle_actions(own,foes,11,pulls)
            self.assertTrue(all(u.handle not in pulls for u in dogs))
            casts=[o for o in orders if o[0]=='cast' and o[2] in {'frostnova','deathcoil'}]
            self.assertEqual([o[2] for o in casts],['frostnova','deathcoil'])
            self.assertTrue(all(o[3]['target']==tc for o in casts))
            orders.clear();b.engage_battle(own,foes,12)
            self.assertEqual({o[2] for o in orders if o[0]=='attack' and o[1] in {u.handle for u in dogs}}, {tc.handle})

    def test_failed_silence_and_expiry_keep_dogs_out(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        g.cast=lambda *a,**kw:False
        b.combat_spells(own,foes,10)
        b.silence_protected_until={tc.handle:100}
        pulls={};retreat_ghouls(b,own,foes,11,pulls)
        self.assertTrue(pulls)
        effects[tc.handle]=['BNsi'];pulls={};retreat_ghouls(b,own,foes,12,pulls)
        self.assertFalse(pulls)
        effects[tc.handle]=[];retreat_ghouls(b,own,foes,13,pulls)
        self.assertTrue(pulls)

    def test_blocked_path_holds_and_does_not_charge(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        g.path_distance=lambda *a:None
        pulls={};retreat_ghouls(b,own,foes,10,pulls)
        for u in own:
            if u.type=='ugho':
                self.assertEqual(pulls[u.handle],(u.x,u.y))
                b.go_raw([u],pulls[u.handle],10)
        b.focus_ghouls([u for u in own if u.type=='ugho'],foes,10)
        self.assertFalse(any(o[0]=='attack' for o in orders))
        self.assertTrue(any(o[0]=='hold_after' for o in orders))

    def test_safety_reservations_are_not_overwritten(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.micro.pulling.add(own[0].handle);b.shopping.add(own[1].handle)
        b.cast_until[own[2].handle]=20;effects[own[3].handle]=['BPSE']
        pulls={own[0].handle:(-900,0)}
        retreat_ghouls(b,own,foes,10,pulls,{own[4].handle})
        self.assertEqual(pulls[own[0].handle],(-900,0))
        self.assertTrue(all(u.handle not in pulls for u in own[1:5]))
        self.assertIn(own[5].handle,pulls)

    def test_dead_hidden_distant_and_invulnerable_tc_release_without_claiming_kill(self):
        for state in ('dead','hidden','distant','invulnerable'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            retreat_ghouls(b,own,foes,10,{})
            if state=='dead':tc.hp=0
            if state=='hidden':foes.remove(tc)
            if state=='distant':tc.x=2000
            if state=='invulnerable':effects[tc.handle]=['Bvul']
            pulls={};retreat_ghouls(b,own,foes,11,pulls)
            self.assertFalse(pulls);self.assertFalse(b.ghoul_tc_waiting)
            self.assertTrue(any(e=='battle_ghoul_tc_release' and d['reason']=='target_unavailable' for e,d in events))

    def test_after_tc_death_heads_are_focused_one_at_a_time(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.select_strategy(g,own,foes,10);tc.hp=0
        first=b.hero_pressure.orc_focus(g,own,foes,11)
        self.assertIn(first.type,{'ohun','otbk'})
        dogs=[u for u in own if u.type=='ugho']
        b.focus_ghouls(dogs,foes,11)
        self.assertEqual({o[2] for o in orders if o[0]=='attack'},{first.handle})
        other=next(e for e in foes if e.type=='otbk' and e!=first);other.hp=1
        self.assertEqual(b.hero_pressure.orc_focus(g,own,foes,12),first)
        first.hp=0
        self.assertNotEqual(b.hero_pressure.orc_focus(g,own,foes,13),first)

    def test_no_dark_or_fiend_army_does_not_wait_for_silence(self):
        for kind in ('no_dark','fiends','unlearned'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            if kind=='no_dark':own[:]=[u for u in own if u.type!='Nbrn']
            if kind=='fiends':
                for u in own:
                    if u.type=='ugho':u.type='ucry'
            if kind=='unlearned':
                old=g.abilities;g.abilities=lambda u:[] if u.type=='Nbrn' else old(u)
            self.assertIsNone(opening_target(g,own,foes))
            pulls={};retreat_ghouls(b,own,foes,10,pulls);self.assertFalse(pulls)

    def test_silence_casts_from_range_without_waiting_for_dogs_to_enter_stomp(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        tc.x=650
        for u in own:u.x=0
        b.combat_spells(own,foes,10)
        self.assertEqual([o[2] for o in orders if o[0]=='cast'],['silence'])

    def test_precontact_layout_cannot_send_dogs_forward_before_silence(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        for e in foes:e.x=750
        g.current_target=lambda u:None
        b.prepare_battle(10,own,(900,0),foes=foes)
        dogs={u.handle for u in own if u.type=='ugho'}
        self.assertFalse(any(o[0]=='move' and o[1] in dogs for o in orders))

    def test_new_wait_interrupts_old_march_and_respects_dk_reservation(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        u=own[0];b.last[('go',u.handle)]=((0,0,False),10)
        retreat_ghouls(b,own,foes,10,{})
        self.assertNotIn(('go',u.handle),b.last)
        own[6].hp=100
        b.combat_spells(own,foes,10,{dk.handle})
        self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))


if __name__=='__main__':unittest.main()
