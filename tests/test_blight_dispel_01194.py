import unittest
import test_orc_melee_01193 as melee
from undead.controller import Controller
from training import TrainingController


class BlightDispelTests(unittest.TestCase):
    def scene(self,kind):
        b,g,own,foes,orders,events,effects,car,troops,tc,fs=melee.OrcMeleeTests().scene(kind)
        dk=next(u for u in own if u.type=='Udea');bag=['skul'];uses=[]
        g.inventory=lambda u:bag if u is dk else []
        g.use_item=lambda u,slot,**kw:uses.append((u.handle,slot,kw)) or True
        for e in foes:e.x=2000
        return b,g,own,foes,orders,events,effects,car,dk,bag,uses

    def test_training_skull_is_cast_at_feet_and_waits_for_enemy(self):
        for kind in (TrainingController,):
            b,g,own,foes,orders,events,effects,car,dk,bag,uses=self.scene(kind)
            b.prepare_battle(10,army=own,foes=foes)
            self.assertEqual(uses,[(dk.handle,0,dict(x=dk.x,y=dk.y))])
            bag.clear();b.battle_actions(own,foes,11,{})
            b.engage_battle(own,foes,11);b.go(own,(2000,0),11,attack=True)
            self.assertTrue(b.blight_waiting)
            self.assertTrue(any(o[0]=='move' for o in orders)) # Spread at home, then wait.
            self.assertFalse(any(o[0] in {'attack_move','attack'} for o in orders))
            self.assertTrue(any(e=='battle_skull_consumption_observed' for e,_ in events))
            for e in foes:e.x=300
            b.battle_actions(own,foes,13,{});b.engage_battle(own,foes,13)
            self.assertFalse(b.blight_waiting)
            self.assertTrue(any(o[0]=='attack' for o in orders))
            self.assertEqual(len(uses),1)

    def test_skull_receipt_is_not_consumption_and_retries_are_bounded(self):
        b,g,own,foes,orders,events,effects,car,dk,bag,uses=self.scene(TrainingController)
        for now in (10,10.5,13,16,19,100):b.prepare_blight(own,foes,now)
        self.assertEqual(len(uses),3)
        self.assertFalse(any(e=='battle_skull_consumption_observed' for e,_ in events))
        self.assertFalse(b.blight_item['consumed'])

    def test_skull_cooldown_control_and_exclusive_actions_are_respected(self):
        for why in ('cooldown','controlled','blocked','cast','teleport'):
            b,g,own,foes,orders,events,effects,car,dk,bag,uses=self.scene(TrainingController);blocked=set()
            if why=='cooldown':g.cooldown=lambda *a:None
            if why=='controlled':effects[dk.handle]=['BOhx']
            if why=='blocked':blocked.add(dk.handle)
            if why=='cast':b.cast_until[dk.handle]=20
            if why=='teleport':b.teleport={'hero':dk.handle}
            b.prepare_blight(own,foes,10,blocked);self.assertFalse(uses,why)

    def test_no_skull_keeps_existing_behavior_and_contact_never_waits_for_item(self):
        for why in ('missing','already_fighting'):
            b,g,own,foes,orders,events,effects,car,dk,bag,uses=self.scene(TrainingController)
            if why=='missing':bag.clear()
            else:foes[0].x=300
            b.prepare_blight(own,foes,10)
            self.assertFalse(b.blight_waiting);self.assertFalse(uses)

    def test_safe_dispel_shift_then_cast_and_does_not_cross_frontline(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=melee.OrcMeleeTests().scene(kind)
            car.x=-300;troops[0].x=650;fs.x=2000;effects[troops[0].handle]=['Broa','Bspe']
            b.hero_pressure.melee_orc(g,foes)
            b.destroyer.tick(b,own,foes,10)
            moves=[o for o in orders if o[0]=='move' and o[1]==car.handle]
            self.assertTrue(moves);point=moves[-1][2];self.assertLessEqual(point[0],0)
            b.attack_destroyers(own,foes,10)
            self.assertFalse(any(o[0]=='attack' and o[1]==car.handle for o in orders))
            car.x,car.y=point;orders.clear();b.destroyer.tick(b,own,foes,11)
            self.assertTrue(any(o[:3]==('cast',car.handle,'devourmagic') for o in orders))

    def test_dispel_shift_stops_for_low_hp_waiting_and_failed_movement_budget(self):
        for why in ('wounded','waiting','failed'):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs=melee.OrcMeleeTests().scene()
            car.x=-300;troops[0].x=650;fs.x=2000;effects[troops[0].handle]=['Broa','Bspe']
            b.hero_pressure.melee_orc(g,foes)
            if why=='wounded':car.hp=car.hp_max*.45
            if why=='waiting':b.blight_waiting=True
            if why=='failed':g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or False
            for now in (10,10.5,12,14,16,100):b.destroyer.tick(b,own,foes,now)
            self.assertEqual(len([o for o in orders if o[0]=='move']),3 if why=='failed' else 0)


if __name__=='__main__':unittest.main()
