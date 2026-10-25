import unittest
import test_summon_statue_01205 as support
import test_tc_pressure_01186 as battle
import test_consumables as consumables
import test_equipment as equipment
from test_micro_loot import unit
from undead.consumables import Consumables
from undead.controller import Controller
from undead.equipment import can_receive,gear_owner
from undead.nc_combo import spell_data
from training import TrainingController


class EarlyStatueTests(unittest.TestCase):
    def test_focus_fire_preempts_only_its_own_supply_lock_before_damage(self):
        for foreign in (False,True):
            b,g,events,car,hero,foe=support.StatuePersistenceTests().scene()
            car.hp=car.hp_max
            b.statue_support.tick(b,g.army,[],10)
            self.assertIn(('cast',car.handle,'replenishlife'),g.orders)
            if foreign:b.cast_until[car.handle]=20
            foes=[foe,unit('owyv',91,100)];g.current_target=lambda _:car
            g.orders.clear();b.statue_support.tick(b,g.army,foes,10.2)
            self.assertEqual(any(o[0]=='move' and o[1]==car.handle for o in g.orders),not foreign)
            self.assertFalse(any(o[0]=='cast' for o in g.orders))
            if foreign:self.assertEqual(b.cast_until[car.handle],20)

    def test_single_target_and_unfocused_health_thresholds(self):
        for hp,focused,want in ((.6,False,True),(.61,False,False),(.75,True,True),(.76,True,False)):
            b,g,events,car,hero,foe=support.StatuePersistenceTests().scene()
            car.hp=car.hp_max*hp;g.current_target=lambda _:car if focused else None
            b.statue_support.tick(b,g.army,[foe],10)
            self.assertEqual(any(o[0]=='move' and o[1]==car.handle for o in g.orders),want,(hp,focused))

    def test_rapid_damage_retreats_above_regular_threshold_without_repeated_casts(self):
        b,g,events,car,hero,foe=support.StatuePersistenceTests().scene()
        car.hp=car.hp_max;b.statue_support.tick(b,g.army,[foe],10)
        car.hp=car.hp_max*.84;g.orders.clear()
        b.statue_support.tick(b,g.army,[foe],10.5)
        self.assertTrue(any(o[0]=='move' and o[1]==car.handle for o in g.orders))
        self.assertFalse(any(o[0]=='cast' for o in g.orders))

    def test_disabled_and_protected_statues_are_not_given_move_orders(self):
        for why in ('stun','protected','path'):
            b,g,events,car,hero,foe=support.StatuePersistenceTests().scene();car.hp=car.hp_max*.55
            if why=='stun':g.buffs=lambda _:['BSTN']
            if why=='path':b.army_recovery.safe_path=lambda *a,**kw:None
            b.statue_support.tick(b,g.army,[foe],10,{car.handle} if why=='protected' else ())
            self.assertFalse(any(o[0]=='move' for o in g.orders),why)


class RoarAndSpreadTests(unittest.TestCase):
    def test_full_real_bags_keep_roar_and_consume_to_free_orb_slot(self):
        fixture=equipment.EquipmentTests();g,e,events=fixture.setup_game()
        g.inv[g.dk.handle]=['phea','rnec','shea','cnob','cnob',None]
        g.inv[g.lich.handle]=['shea','pnvl','sror','rde2','rde1',None]
        before=sorted(c for bag in g.inv.values() for c in bag if c)
        for now in range(1,50,3):
            if e.tick(g,g.heroes,[],now,{}):fixture.observed_transfer(g)
        bag=g.inv[g.lich.handle]
        self.assertIn('sror',bag);self.assertEqual(bag.count('cnob'),2);self.assertNotIn(None,bag)
        self.assertEqual(gear_owner('sror'),'Ulic')
        self.assertEqual(before,sorted(c for bag in g.inv.values() for c in bag if c))
        self.assertFalse(e.tick(g,g.heroes,[],60,{}))
        bag[bag.index('sror')]=None
        self.assertTrue(can_receive(g.lich,bag,'ocor'));self.assertFalse(can_receive(g.lich,bag,'rat6'))

    def test_roar_does_not_wait_for_700_range_or_three_units_and_respects_control(self):
        for why in ('visible','absent','stun','cooldown','buff','cast'):
            g=consumables.Game();h=g.heroes[1];g.army=[h];h.hp=h.hp_max;g.bags[h.handle][0]='sror'
            foe=unit('ogru',90,1000);foe.owner=1;locks={}
            if why=='stun':g.bs[h.handle]=['BSTN']
            if why=='buff':g.bs[h.handle]=['Broa']
            if why=='cooldown':g.cd[(h.handle,'AIrr')]=2
            if why=='cast':locks[h.handle]=15
            Consumables(lambda *a,**kw:None).tick(g,g.army,[] if why=='absent' else [foe],10,locks)
            self.assertEqual(g.orders==[('use','Ulic','sror')],why=='visible',why)

    def test_wider_layout_limits_single_stomp_coverage_and_never_reforms_in_combat(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=battle.TcFirstTests().scene(kind)
            foes.clear();g.current_target=lambda _:None
            b.prepare_battle(1,own,target=(2000,0))
            points=[b.prep_points[u.handle] for u in own if u.type=='ucry']
            self.assertEqual(len(points),6)
            self.assertGreaterEqual(min(g.dist(p,q) for i,p in enumerate(points) for q in points[i+1:]),239.9)
            radius=max(float(spell_data()[0]['AOws']['Area'+str(i)]) for i in (1,2,3))
            # Six fiends are on one line: any stomp spans at most one diameter.
            self.assertLessEqual(int(2*radius/240)+1,3)
            orders.clear();b.battle_started=True;b.battle_last_enemy=10
            b.prepare_battle(10,own,target=(2000,0))
            self.assertFalse(orders)


if __name__=='__main__':unittest.main()
