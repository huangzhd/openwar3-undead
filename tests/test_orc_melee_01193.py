"""Shared answers to FS/TC melee armies: focused damage and melee protection."""
import unittest
from unittest.mock import Mock
import test_battle_focus_01191 as focus
import test_hero_rules as armor
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController


class OrcMeleeTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=focus.BattleFocusTests().scene(kind)
        foes[:]=[tc,fs]
        troops=[]
        for i,code in enumerate(('ogru','ogru','orai','orai')):
            u=unit(code,80+i,owner=1,x=300+i*20);u.hp=u.hp_max=600;u.mana=0;u.has_detail=True
            troops.append(u);foes.append(u)
        car=own[8];car.x=0
        return b,g,own,foes,orders,events,effects,car,troops,tc,fs

    def test_shared_group_grunts_then_raiders_before_heroes_and_old_combo(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=self.scene(kind)
            b.nc_combo.pending=dict(target=tc.handle,clock=10)
            for tick,victim in enumerate(troops):
                orders.clear();now=10+2*tick
                b.focus_ranged(own,foes,now);b.attack_destroyers(own,foes,now)
                shots=[o for o in orders if o[0]=='attack']
                self.assertTrue(shots);self.assertEqual({o[2] for o in shots},{victim.handle})
                self.assertIn(car.handle,{o[1] for o in shots})
                foes.remove(victim)
            b.focus_ranged(own,foes,20);self.assertEqual(b.ranged_focus,tc.handle)

    def test_healthy_destroyer_is_not_recalled_by_generic_pullback(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,*_=self.scene(kind)
            car.hp=car.hp_max*.46;b.micro.pulling.add(car.handle);pulls={car.handle:(-900,0)}
            b.rear_destroyers(own,foes,10,pulls,None);b.attack_destroyers(own,foes,10,pulls)
            self.assertNotIn(car.handle,pulls);self.assertNotIn(car.handle,b.micro.pulling)
            self.assertTrue(any(o[0]=='attack' and o[1]==car.handle for o in orders))

    def test_low_destroyer_retreats_and_does_not_receive_attack(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,*_=self.scene(kind)
            car.hp=car.hp_max*.45;car.x=200;pulls={}
            b.rear_destroyers(own,foes,10,pulls,None);b.attack_destroyers(own,foes,10,pulls)
            self.assertIn(car.handle,pulls)
            b.go_raw([car],pulls[car.handle],10)
            self.assertTrue(any(o[0]=='move' and o[1]==car.handle for o in orders))
            self.assertFalse(any(o[0]=='attack' and o[1]==car.handle for o in orders))

    def test_dispel_wolf_precedes_attack_and_preserves_cast_window(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=self.scene(kind)
            wolf=unit('osw1',99,owner=1,x=-200);wolf.has_detail=True;wolf.mana=0;foes.append(wolf)
            # Isolate the dispel window; TC control ordering is checked separately.
            own[7].mana=0;b.combat_spells=Mock();b.frost_armor=Mock();b.heal_allies=Mock()
            b.battle_actions(own,foes,10,{})
            self.assertTrue(any(o[:3]==('cast',car.handle,'devourmagic') for o in orders))
            self.assertFalse(any(o[0]=='attack' and o[1]==car.handle for o in orders))
            b.attack_destroyers(own,foes,11.3)
            self.assertTrue(any(o[0]=='attack' and o[1]==car.handle for o in orders))
            self.assertTrue(any(e=='destroyer_dispel_attempt' and d['reason']=='enemy_summon' for e,d in events))

    def test_silence_tc_and_buff_dispel_remain_available(self):
        b,g,own,foes,orders,events,effects,car,troops,tc,fs=self.scene()
        tc.x=450;troops[0].x=-200;effects[troops[0].handle]=['Broa']
        b.battle_actions(own,foes,10,{})
        self.assertTrue(any(o[0]=='cast' and o[2]=='silence' and o[3]['target'] is tc for o in orders))
        self.assertTrue(any(e=='destroyer_dispel_attempt' and d['reason']=='enemy_buff' for e,d in events))

    def test_cast_exclusive_and_retreat_locks_prevent_destroyer_attacks(self):
        from undead.policy import Action
        for reason in ('cast','blocked','shopping','teleport','retreat'):
            b,g,own,foes,orders,events,effects,car,*_=self.scene();blocked=set()
            if reason=='cast':b.cast_until[car.handle]=20
            if reason=='blocked':blocked.add(car.handle)
            if reason=='shopping':b.shopping.add(car.handle)
            if reason=='teleport':b.teleport={'hero':own[6].handle}
            if reason=='retreat':b.action=Action.RETREAT
            b.attack_destroyers(own,foes,10,blocked)
            self.assertFalse(any(o[0]=='attack' for o in orders),reason)

    def test_small_melee_or_different_heroes_keep_existing_hero_focus(self):
        for reason in ('few','other_heroes','ranged_majority'):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=self.scene()
            if reason=='few':foes[:]=[tc,fs,troops[0]]
            if reason=='other_heroes':fs.type='Hpal'
            if reason=='ranged_majority':
                for i in range(5):
                    head=unit('otbk',110+i,owner=1,x=300);head.has_detail=True;head.mana=0;foes.append(head)
            b.focus_ranged(own,foes,10);self.assertEqual(b.ranged_focus,tc.handle)
            self.assertFalse(b.hero_pressure.orc_melee_active)

    def test_no_long_distance_destroyer_chase(self):
        b,g,own,foes,orders,events,effects,car,troops,*_=self.scene()
        for u in troops:u.x=2000
        b.attack_destroyers(own,foes,10)
        self.assertFalse(orders)

    def test_melee_targeted_fiend_gets_armor_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=self.scene(kind)
            old=g.abilities
            g.abilities=lambda u:old(u)+([dict(code='AUfu',level=1)] if u.type=='Ulic' else [])
            troops[0].x=100;g.current_target=lambda e:own[0] if e is troops[0] else None
            b.battle_actions(own,foes,10,{})
            casts=[o for o in orders if o[0]=='cast' and o[2]=='frostarmor']
            self.assertEqual([o[3]['target'] for o in casts],[own[0]])

    def test_armor_ignores_ranged_attack_burrow_transition_and_existing_buff(self):
        for reason in ('ranged','pending','buried','armored','controlled'):
            b,l,d,e,own,casts,buffs,events=armor.HeroRuleTests().armor_game()
            d.type='ucry';d.is_hero=False
            if reason=='ranged':e.type='otbk'
            if reason=='pending':b.fiend_burrow.pending[d.handle]=dict(action='burrowing')
            if reason=='buried':d.type='ucrm'
            if reason=='armored':buffs[d.handle]=['BUfa']
            if reason=='controlled':buffs[l.handle]=['BOhx']
            b.frost_armor(own,[e],10);self.assertFalse(casts,reason)


if __name__=='__main__':unittest.main()
