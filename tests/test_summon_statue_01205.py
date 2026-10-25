import unittest
import test_battle_focus_01191 as focus
import test_support_fan_01122 as support
from test_micro_loot import unit
from undead.controller import Controller
from training import TrainingController


class SummonOrdersTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc,fs,kodo=focus.BattleFocusTests().scene(kind)
        sk=focus.BattleFocusTests().skeleton(own)
        return b,g,own,foes,orders,sk

    def test_one_attack_ground_survives_target_loss_and_retreat_orders(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,sk=self.scene(kind)
            b.attack_skeletons([sk],foes,10)
            self.assertEqual(len(orders),1);self.assertEqual(orders[0][0],'attack_move')
            b.battle_enemies=[]
            for now in (11,13,20):
                b.go([sk],(-1000,0),now);b.go_raw([sk],(-1000,0),now)
            self.assertEqual(len(orders),1)

    def test_engine_target_changes_do_not_trigger_new_orders(self):
        b,g,own,foes,orders,sk=self.scene()
        b.attack_skeletons([sk],foes,10)
        for now,target in ((12,foes[0]),(20,foes[2]),(30,foes[1])):
            g.current_target=lambda u:target
            b.attack_skeletons([sk],foes,now)
        self.assertEqual(len(orders),1)

    def test_new_summon_gets_order_without_interrupting_old_one(self):
        b,g,own,foes,orders,sk=self.scene()
        b.attack_skeletons([sk],foes,10)
        new=unit('uske',100,0);new.owner=0;own.append(new)
        b.attack_skeletons([sk,new],foes,12)
        self.assertEqual([o[1] for o in orders],[sk.handle,new.handle])

    def test_failed_order_retries_are_bounded_and_exclusive_scout_is_untouched(self):
        b,g,own,foes,orders,sk=self.scene()
        g.attack_move=lambda u,x,y:orders.append(('attack_move',u.handle,(x,y))) or False
        for now in (10,10.5,12,14,16,20):b.attack_skeletons([sk],foes,now)
        self.assertEqual(len(orders),3)
        b.skeleton_assaults.clear();orders.clear();b.skeleton_scouts.assignments[sk.handle]={}
        b.attack_skeletons([sk],foes,22);self.assertFalse(orders)


class StatuePersistenceTests(unittest.TestCase):
    def scene(self):
        b,g,events=support.StatueTests().scene();car=g.statues[0];hero=g.heroes[0]
        g.army=[car,hero];car.x=hero.x=0;hero.hp=hero.hp_max*.5
        foe=unit('hfoo',90,100);foe.owner=1
        b.army_recovery.statue_modes[car.handle]={'mode':'life'}
        return b,g,events,car,hero,foe

    def test_healthy_unfocused_statue_keeps_healing_under_fire(self):
        for ratio in (1,.8,.7,.601):
            b,g,events,car,hero,foe=self.scene();car.hp=car.hp_max*ratio
            b.micro.hit[car.handle]=9.9
            b.statue_support.tick(b,g.army,[foe],10)
            self.assertIn(('cast',car.handle,'replenishlife'),g.orders)
            self.assertFalse(any(o[0]=='move' for o in g.orders),ratio)
            g.buffs=lambda u:['Brpl'] if u==hero else []
            b.statue_support.tick(b,g.army,[foe],12.1)
            self.assertEqual(sum(o[0]=='cast' and o[1]==car.handle and o[2] in {'replenishlife','replenishmana'} for o in g.orders),2)

    def test_forty_percent_retreat_then_safe_supply_without_forward_oscillation(self):
        b,g,events,car,hero,foe=self.scene();car.hp=car.hp_max*.4
        b.statue_support.tick(b,g.army,[foe],10)
        moves=[o for o in g.orders if o[0]=='move'];self.assertTrue(moves)
        car.x,car.y=moves[-1][2];g.orders.clear()
        car.hp=car.hp_max*.5
        b.statue_support.tick(b,g.army,[],13)
        self.assertIn(car.handle,b.statue_support.retreating)
        self.assertFalse(any(o[0]=='move' for o in g.orders))
        car.hp=car.hp_max*.75;b.statue_support.tick(b,g.army,[],16)
        self.assertNotIn(car.handle,b.statue_support.retreating)

    def test_ghouls_and_destroyers_can_be_supply_recipients(self):
        for code in ('ugho','ubsp'):
            b,g,events,car,hero,foe=self.scene();hero.type=code;hero.is_hero=False
            b.statue_support.tick(b,g.army,[foe],10)
            self.assertIn(('cast',car.handle,'replenishlife'),g.orders)


if __name__=='__main__':unittest.main()
