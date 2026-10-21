import unittest
from unittest.mock import Mock
from types import SimpleNamespace as N
import test_shared_battle_01181 as shared
import test_support_fan_01122 as support
import test_consumables as items
from test_baseline import unit
from test_micro_loot import dist
from undead.controller import Controller
from undead.consumables import Consumables


class RearDkTests(unittest.TestCase):
    def scene(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        dk=unit('Udea',40,owner=0,x=150);dk.hp=dk.hp_max=800;dk.mana=300;dk.has_detail=True
        own.append(dk)
        return b,g,own,foes,orders,dk

    def test_full_health_dk_moves_behind_main_and_does_not_melee(self):
        b,g,own,foes,orders,dk=self.scene();pulls={}
        b.rear_dk(own,foes,10,pulls)
        point=pulls[dk.handle]
        self.assertLess(point[0],-140)
        self.assertLess(dist(point,own[6]),750)
        self.assertGreater(dist(point,own[6]),700)
        dk.x,dk.y=point;b.rear_dk(own,foes,12,{})
        self.assertIn(('hold',dk.handle),orders)
        orders.clear();b.engage_battle(own,foes,13)
        self.assertFalse(any(o[1]==dk.handle for o in orders))

    def test_cast_lock_emergency_pull_and_blocked_path_are_preserved(self):
        for why in ('cast','pull','terrain'):
            b,g,own,foes,orders,dk=self.scene();pulls={}
            if why=='cast':b.cast_until[dk.handle]=20
            if why=='pull':pulls[dk.handle]=(-900,0)
            if why=='terrain':b.army_recovery.safe_path=Mock(return_value=None)
            b.rear_dk(own,foes,10,pulls)
            if why=='cast':self.assertFalse(pulls)
            if why=='pull':self.assertEqual(pulls[dk.handle],(-900,0))
            if why=='terrain':self.assertEqual(pulls[dk.handle],(dk.x,dk.y))
            self.assertFalse(orders)

    def test_prebattle_dk_behind_damage_heroes_and_can_still_heal(self):
        b,g,own,foes,orders,dk=self.scene()
        b.prepare_battle(1,army=own,target=(2000,0))
        self.assertLess(b.prep_points[dk.handle][0],b.prep_points[own[6].handle][0])
        orders.clear();own[6].hp=own[6].hp_max*.5;b.rear_dk(own,foes,10,{})
        b.heal_allies(own,10,[own[6]])
        self.assertTrue(any(o[0]=='cast' and o[1]==dk.handle and o[2]=='deathcoil' for o in orders))


class CloseStatueTests(unittest.TestCase):
    def test_safe_far_statues_rejoin_close_rear_points(self):
        b,g,events=support.StatueTests().scene()
        for u in g.fiends+g.heroes:u.hp=u.hp_max;u.mana=u.mana_max
        for u in g.statues:u.x=-700
        foe=g.foes[0];foe.type='otbk';foe.x=500
        b.statue_support.tick(b,g.army,[foe],10)
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual(len(moves),2)
        for _,h,p in moves:
            self.assertLessEqual(dist(p,g.fiends[0]),350)
            self.assertGreaterEqual(dist(p,foe)-450,120)

    def test_life_statue_moves_to_injured_group_instead_of_copying_mana_partner(self):
        b,g,events=support.StatueTests().scene();b.army_recovery.statues(b,1);g.orders.clear()
        for u in g.fiends:u.x=0;u.hp=200
        for h in g.heroes:h.x=-200;h.hp=h.hp_max;h.mana=100
        for u in g.statues:u.x=-350
        foe=g.foes[0];foe.type='otbk';foe.x=650
        b.statue_support.tick(b,g.army,[foe],10)
        first=g.statues[0]
        self.assertFalse(any(o[:3]==('cast',first.handle,'replenishmana') for o in g.orders))
        self.assertTrue(any(o[0]=='move' and o[1]==first.handle for o in g.orders))


class LichInvulnerabilityTests(unittest.TestCase):
    def scene(self):
        g=items.Game();dk,lich,_=g.heroes;lich.hp=180
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is dk else []
        g.bags[lich.handle][:2]=['pghe','pnvl']
        foe=unit('otbk',80,owner=1,x=300)
        return g,dk,lich,foe

    def test_unavailable_dk_cannot_block_invulnerability(self):
        for why in ('hex','silence','stun','range','cooldown','unknown','mana','cast','unlearned'):
            g,dk,lich,foe=self.scene();locks={}
            if why in ('hex','silence','stun'):g.bs[dk.handle]=[{'hex':'BOhx','silence':'BNsi','stun':'BPSE'}[why]]
            if why=='range':dk.x=-900
            if why=='cooldown':g.cd[(dk.handle,'AUdc')]=5
            if why=='unknown':g.cd[(dk.handle,'AUdc')]=None
            if why=='mana':dk.mana=74
            if why=='cast':locks[dk.handle]=20
            if why=='unlearned':g.abilities=lambda u:[]
            Consumables(lambda *a,**k:None).tick(g,g.army,[foe],10,locks)
            self.assertIn(('use','Ulic','pnvl'),g.orders,why)
            self.assertNotIn(('use','Ulic','pghe'),g.orders,why)

    def test_ready_coil_precedes_invulnerability_even_when_critical_or_focused(self):
        for why in ('ready','critical','focus'):
            g,dk,lich,foe=self.scene()
            if why=='critical':lich.hp=120
            if why=='focus':lich.hp=280;g.current_target=lambda e:lich
            foes=[foe,unit('otbk',81,owner=1,x=350)] if why=='focus' else [foe]
            Consumables(lambda *a,**k:None).tick(g,g.army,foes,10,{})
            self.assertNotIn(('use','Ulic','pnvl'),g.orders)

    def test_hexed_dk_is_not_reported_ready_and_does_not_attempt_healing(self):
        g,dk,lich,foe=self.scene();g.bs[dk.handle]=['BOhx'];g.cast=Mock()
        b=Controller(g,lambda *a,**k:None);b.player_contact=[foe]
        self.assertFalse(b.rescue_coil_ready(dk,10))
        b.heal_allies(g.army,10,[lich]);g.cast.assert_not_called()


if __name__=='__main__':unittest.main()
