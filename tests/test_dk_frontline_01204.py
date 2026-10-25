import unittest
import test_battle_strategy_01201 as battle
from undead.controller import Controller
from undead.coil import can_damage
from undead.policy import Action
from training import TrainingController


class DkFrontlineTests(unittest.TestCase):
    def scene(self,kind=Controller):
        return battle.BattleStrategyTests().scene(kind,tc_opening=True)

    def test_healthy_dk_stays_support_during_main_fight_in_both_modes(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            pulls={};b.rear_dk(own,foes,10,pulls)
            self.assertIn(dk.handle,pulls)
            b.attack_dk(own,foes,10)
            self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))
            g.current_target=lambda u:tc if u==dk else None
            orders.clear();b.stop_hero_chases([dk],11)
            self.assertIn(('hold',dk.handle),orders)

    def test_half_health_retreat_holds_until_recovered_not_threshold_oscillation(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        dk.hp=dk.hp_max*.5;pulls={};b.rear_dk(own,foes,10,pulls)
        self.assertIn(dk.handle,pulls)
        b.attack_dk(own,foes,10);self.assertFalse(orders)
        dk.hp=dk.hp_max*.55;b.rear_dk(own,foes,12,{})
        b.attack_dk(own,foes,12);self.assertFalse(any(o[0]=='attack' for o in orders))
        dk.hp=dk.hp_max*.61;b.rear_dk(own,foes,14,{})
        b.attack_dk(own,foes,14)
        self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))

    def test_lost_distant_or_unreachable_target_stops_advance(self):
        for why in ('far','path','hidden','invulnerable'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene();foes[:]=[tc]
            b.attack_dk(own,foes,10);orders.clear()
            g.current_target=lambda u:tc if u==dk else None
            if why=='far':tc.x=1800
            if why=='path':g.path_distance=lambda *a:None
            if why=='hidden':foes.clear()
            if why=='invulnerable':effects[tc.handle]=['Bvul']
            b.attack_dk(own,foes,12)
            self.assertIn(('hold',dk.handle),orders,why)
            self.assertFalse(any(o[0]=='attack' for o in orders),why)

    def test_half_health_dk_still_retreats_without_other_ranged_units(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        dk.hp=dk.hp_max*.5;pulls={}
        b.rear_dk([dk],foes,10,pulls)
        self.assertIn(dk.handle,pulls)
        self.assertLess(pulls[dk.handle][0],dk.x)

    def test_shared_pipeline_keeps_dk_support_after_spells_finish(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            g.cooldown=lambda *a:5
            pulls={};b.battle_actions(own,foes,10,pulls)
            b.engage_battle([u for u in own if u.handle not in pulls],foes,10)
            self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))
            self.assertIn(dk.handle,pulls)
            self.assertTrue(any(o[0]=='attack' and o[1]!=dk.handle for o in orders))
            self.assertFalse(any(o[0] in ('hold','move') and o[1]==dk.handle for o in orders))

    def test_dk_attack_preserves_healing_cast_and_safety_ownership(self):
        for why in ('cast','pull','shield','shop','blocked','stun','retreat','teleport'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene();blocked=set()
            if why=='cast':b.cast_until[dk.handle]=20
            if why=='pull':b.micro.pulling.add(dk.handle)
            if why=='shield':b.shield_moves[dk.handle]=(0,0)
            if why=='shop':b.shopping.add(dk.handle)
            if why=='blocked':blocked.add(dk.handle)
            if why=='stun':effects[dk.handle]=['BSTN']
            if why=='retreat':b.action=Action.RETREAT
            if why=='teleport':b.teleport={'hero':dk.handle}
            b.attack_dk(own,foes,10,blocked)
            self.assertFalse(orders,why)

    def test_heal_precedes_dk_support_and_healthy_allies_do_not_trigger_melee(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind);lich=own[6];lich.hp=200
            b.combat_spells(own,foes,10);b.attack_dk(own,foes,10)
            self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target']==lich for o in orders))
            self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))
            lich.hp=lich.hp_max;b.attack_dk(own,foes,12)
            self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))

    def test_all_damage_paths_exclude_both_headhunter_types_even_for_finish(self):
        for kind in (Controller,TrainingController):
            for code in ('ohun','otbk'):
                b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
                head=foes[0];head.type=code;head.hp=1;foes[:]=[head]
                self.assertFalse(can_damage(code));self.assertTrue(can_damage('Otch'))
                b.nc_combo.try_cast(g,own,foes,10,b.cast_until)
                b.combat_spells(own,foes,12);b.fight(own,foes,14)
                self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))


if __name__=='__main__':unittest.main()
