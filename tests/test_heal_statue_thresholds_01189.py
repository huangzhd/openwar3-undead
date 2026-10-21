import unittest
from unittest.mock import Mock
import test_coil as coil_cases
import test_rear_support_01184 as rear
import test_support_fan_01122 as support
from test_micro_loot import unit,dist
from undead.consumables import Consumables
from undead.controller import Controller
from training import TrainingController


class HealingThresholdTests(unittest.TestCase):
    def test_hero_coil_half_health_boundary_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            for code in ('Ulic','Nbrn'):
                for hp,expected in ((420,False),(301,False),(300,True),(299,True)):
                    dk=unit('Udea',1,0,600);hero=unit(code,2,100,hp)
                    old,casts,_=coil_cases.CoilTests().game([dk,hero])
                    b=kind(old.g,lambda *a,**k:None,2);b.player_contact=[unit('ogru',3,200)]
                    b.heal_allies([dk,hero],10)
                    self.assertEqual(bool(casts),expected,(kind,code,hp))

    def test_explicit_rescue_list_and_damage_trend_cannot_bypass_half_health(self):
        dk=unit('Udea',1,0,600);hero=unit('Ulic',2,100,450)
        b,casts,_=coil_cases.CoilTests().game([dk,hero]);b.micro.damage.rates[hero.handle]=500
        b.player_contact=[unit('ogru',3,200)];b.heal_allies([dk,hero],10,[hero])
        self.assertFalse(casts)

    def test_ghoul_missing_health_rule_is_unchanged(self):
        dk=unit('Udea',1,0,600);fiend=unit('ugho',2,100,450)
        b,casts,_=coil_cases.CoilTests().game([dk,fiend]);b.player_contact=[unit('ogru',3,200)]
        b.heal_allies([dk,fiend],10)
        self.assertEqual(casts,[('deathcoil','ugho')])

    def test_fiend_coil_strict_forty_percent_boundary_and_explicit_lists(self):
        for kind in (Controller,TrainingController):
            for hp,want in ((450,False),(241,False),(240,False),(239,True)):
                for explicit in (False,True):
                    dk=unit('Udea',1,0,600);fiend=unit('ucry',2,100,hp)
                    old,casts,_=coil_cases.CoilTests().game([dk,fiend])
                    b=kind(old.g,lambda *a,**k:None,2);b.player_contact=[unit('ogru',3,200)]
                    b.heal_allies([dk,fiend],10,[fiend] if explicit else None)
                    self.assertEqual(bool(casts),want,(kind,hp,explicit))

    def test_invulnerability_boundary_even_under_stomp_focus_and_urgent(self):
        for hp,want in ((181,False),(180,True),(179,True),(350,False)):
            g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();lich.hp=hp
            g.bags[lich.handle]=['pnvl']+[None]*5;g.bs[dk.handle]=['BOhx']
            foe.type='Otch';g.current_target=lambda u:lich
            Consumables(lambda *a,**k:None).tick(g,g.army,[foe,unit('otbk',91,200)],10,{},urgent={lich.handle})
            self.assertEqual(('use','Ulic','pnvl') in g.orders,want,hp)

    def test_ready_dk_still_precedes_item_at_thirty_percent(self):
        g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();lich.hp=180
        Consumables(lambda *a,**k:None).tick(g,g.army,[foe],10,{})
        self.assertNotIn(('use','Ulic','pnvl'),g.orders)

    def test_healing_above_thirty_percent_stops_stunned_invul_retry(self):
        g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();lich.hp=179
        g.bags[lich.handle]=['pnvl']+[None]*5;g.bs[dk.handle]=['BOhx'];g.bs[lich.handle]=['BPSE']
        c=Consumables(lambda *a,**k:None);locks={}
        c.tick(g,g.army,[foe],10,locks);lich.hp=181
        c.tick(g,g.army,[foe],10.25,locks,urgent={lich.handle})
        self.assertEqual(g.orders,[('use','Ulic','pnvl')])


class StatueReturnTests(unittest.TestCase):
    def scene(self):
        b,g,events=support.StatueTests().scene()
        foe=g.foes[0];foe.type='otbk';foe.x=500
        for u in g.fiends:u.hp=200
        for h in g.heroes:h.mana=100
        return b,g,events,foe

    def test_low_statue_bypasses_generic_retreat_then_returns_and_supplies(self):
        for training in (True,False):
            b,g,events,foe=self.scene();car=g.statues[0];car.hp=150;car.x=-900
            b.micro.pulling.add(car.handle)
            pulls=b.micro.plan(g.army,[foe],10,lambda _:car.handle,dist,lambda *p:True,(-2000,0),
                               aggressive_training=training,aggressive_battle=not training)
            self.assertNotIn(car.handle,pulls);self.assertNotIn(car.handle,b.micro.pulling)
            b.statue_support.tick(b,g.army,[foe],10,set(pulls))
            moves=[o for o in g.orders if o[0]=='move' and o[1]==car.handle]
            self.assertTrue(moves);car.x,car.y=moves[-1][2]
            self.assertLessEqual(dist(car,g.fiends[0]),350)
            g.orders.clear();b.statue_support.tick(b,g.army,[foe],13)
            self.assertIn(('cast',car.handle,'replenishlife'),g.orders)

    def test_recent_damage_does_not_send_safe_in_range_car_away_again(self):
        b,g,events,foe=self.scene();car=g.statues[0];car.x=-180
        b.micro.hit[car.handle]=9.9
        b.statue_support.tick(b,g.army,[foe],10)
        self.assertIn(('cast',car.handle,'replenishlife'),g.orders)
        self.assertFalse(any(o[0]=='move' and o[1]==car.handle for o in g.orders))

    def test_opposite_rear_flank_is_used_before_long_escape(self):
        b,g,events,foe=self.scene();car=g.statues[0];car.x=100
        original=b.army_recovery.safe_path
        b.army_recovery.safe_path=lambda bot,a,z,enemies,**kw:original(bot,a,z,enemies,**kw) if z[1]>20 else None
        b.statue_support.tick(b,g.army,[foe],10)
        points=[o[2] for o in g.orders if o[0]=='move' and o[1]==car.handle]
        self.assertTrue(points);self.assertLessEqual(dist(points[0],g.fiends[0]),350)
        self.assertGreater(points[0][1],20)

    def test_no_safe_route_and_exclusive_protection_are_respected(self):
        for protected in (True,False):
            b,g,events,foe=self.scene();car=g.statues[0];car.x=100
            if not protected:b.army_recovery.safe_path=Mock(return_value=None)
            b.statue_support.tick(b,g.army,[foe],10,{car.handle} if protected else ())
            self.assertFalse(any(o[0]=='move' and o[1]==car.handle for o in g.orders))


if __name__=='__main__':unittest.main()
