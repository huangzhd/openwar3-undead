import unittest
from unittest.mock import Mock
import test_rear_support_01184 as rear
import test_shared_battle_01181 as shared
from test_baseline import unit
from test_micro_loot import dist
from undead.controller import Controller
from training import TrainingController


class TcFirstTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene(kind)
        dk=unit('Udea',40,owner=0,x=-100);dk.hp=dk.hp_max=800;dk.mana=300;dk.has_detail=True
        own.append(dk);tc=foes[2];tc.hp=tc.hp_max=1000
        old=g.abilities
        g.abilities=lambda u:([dict(code='AUdc',level=1)] if u.type=='Udea' else old(u))
        g.current_target=lambda u:own[0] if u in foes[:2] else None
        return b,g,own,foes,orders,events,effects,dk,tc

    def test_healthy_tc_precedes_firing_headhunters_and_is_shared_by_the_ranged_group(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        self.assertIs(b.hero_pressure.choose(g,own,foes,10),tc)
        b.focus_ranged(own,foes,10)
        shots=[o for o in orders if o[0]=='attack']
        self.assertEqual(len(shots),8)
        self.assertEqual({o[2] for o in shots},{tc.handle})

    def test_silence_then_nonlethal_nc_before_cluster_nova_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            effects[tc.handle]=['Broa'];b.combat_spells(own,foes,10)
            spells=[o for o in orders if o[0]=='cast']
            self.assertEqual([o[2] for o in spells],['silence','frostnova','deathcoil'])
            self.assertTrue(all(o[3]['target'] is tc for o in spells))
            self.assertTrue(any(e=='nc_attempt' and data['intent']=='aoe_pressure' for e,data in events))

    def test_lich_heal_precedes_tc_nova_and_no_offensive_coil(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();lich=own[6];lich.hp=250
        b.combat_spells(own,foes,10)
        spells=[o for o in orders if o[0]=='cast']
        self.assertEqual([o[2] for o in spells],['silence','deathcoil','frostnova'])
        self.assertIs(spells[1][3]['target'],lich);self.assertIs(spells[2][3]['target'],tc)

    def test_invul_and_withdrawal_switch_to_heads_even_during_pending_nc_then_return(self):
        for why in ('invul','withdrawn','hidden'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            b.focus_ranged(own,foes,10);b.nc_combo.pending=dict(target=tc.handle,clock=10)
            if why=='invul':effects[tc.handle]=['Bvul']
            if why=='withdrawn':tc.x=1600
            if why=='hidden':foes.remove(tc)
            orders.clear();b.focus_ranged(own,foes,11.5)
            self.assertEqual(b.ranged_focus,foes[0].handle)
            self.assertFalse(any(o[0]=='attack' and o[2]==tc.handle for o in orders))
            effects[tc.handle]=[];tc.x=400
            if why=='hidden':foes.append(tc)
            orders.clear();b.focus_ranged(own,foes,13)
            self.assertEqual(b.ranged_focus,tc.handle)

    def test_invulnerable_tc_does_not_receive_nc_or_nova(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();effects[tc.handle]=['Bvul']
        b.combat_spells(own,foes,10)
        self.assertFalse(any(o[0]=='cast' and o[3].get('target') is tc for o in orders))
        self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' and o[3]['target'] in foes[:2] for o in orders))

    def test_blocked_healer_and_lich_item_lock_cannot_be_overwritten_by_pressure(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();lich=own[6]
        b.cast_until[lich.handle]=20;effects[dk.handle]=['BOhx']
        b.combat_spells(own,foes,10)
        b.fight(own,foes,10)
        self.assertFalse(any(o[0]=='cast' and o[2] in {'deathcoil','frostnova'} for o in orders))

    def test_generic_fight_does_not_bypass_tc_spell_immunity_after_pressure_declines(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();effects[tc.handle]=['Bams']
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertFalse(any(o[0]=='cast' and o[2] in {'deathcoil','frostnova'} and o[3]['target'] is tc for o in orders))
        self.assertTrue(any(o[0]=='attack' and o[2]==tc.handle for o in orders))

    def test_dk_move_queues_hold_and_failed_or_locked_move_does_not_queue(self):
        for why in ('ready','locked','failed'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            b.battle_dk_support={dk.handle}
            if why=='locked':b.cast_until[dk.handle]=20
            if why=='failed':g.move=Mock(return_value=False)
            b.go_raw([dk],(-700,400),10)
            self.assertEqual(('hold_after',dk.handle) in orders,why=='ready')
            if why=='ready':self.assertEqual(orders[:2],[('move',dk.handle,(-700,400)),('hold_after',dk.handle)])

    def test_level_two_stomp_goal_has_arrival_margin_without_losing_coil_range(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        dk.hp=dk.hp_max*.5
        old=g.abilities;g.abilities=lambda u:([dict(code='AOws',level=2)] if u is tc else old(u))
        pulls={};b.rear_dk(own,foes,10,pulls)
        self.assertGreaterEqual(dist(pulls[dk.handle],own[6]),730)
        self.assertLess(dist(pulls[dk.handle],own[6]),750)


if __name__=='__main__':unittest.main()
