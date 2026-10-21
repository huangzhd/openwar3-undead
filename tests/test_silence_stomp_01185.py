"""Moving silence protection, anti-stomp spacing, and persistent item rescue."""
import unittest
from unittest.mock import Mock
import test_rear_support_01184 as rear
import test_battle_dispel_01182 as dispel
import test_shared_battle_01181 as shared
from test_baseline import unit
from test_micro_loot import dist
from undead.battle_spells import silence_key_hero
from undead.consumables import Consumables
from training import unit_row


class PersistentInvulTests(unittest.TestCase):
    def scene(self):
        g,dk,lich,foe=rear.LichInvulnerabilityTests().scene()
        g.bags[lich.handle]=['pnvl',None,None,None,None,None]
        g.bs[dk.handle]=['BOhx']
        events=[];locks={}
        c=Consumables(lambda event,**kw:events.append(dict(event=event,**kw)))
        return g,dk,lich,foe,c,locks,events

    def test_retry_through_stun_and_use_on_first_release_tick(self):
        g,dk,lich,foe,c,locks,events=self.scene();g.bs[lich.handle]=['BPSE']
        for t in (10,10.25,10.5,10.75,11,11.25):c.tick(g,g.army,[foe],t,locks)
        self.assertEqual(len(g.orders),6) # stun cannot consume a finite failure budget
        self.assertFalse(any(e['event']=='consumable_effect_observed' for e in events))
        g.bs[lich.handle]=[];g.effect=True
        c.tick(g,g.army,[foe],11.5,locks)
        self.assertIn('Bvul',g.bs[lich.handle]);self.assertNotIn('pnvl',g.bags[lich.handle])
        c.tick(g,g.army,[foe],11.75,locks)
        self.assertEqual(len(g.orders),7)
        self.assertTrue(any(e['event']=='consumable_effect_observed' and e['consumed'] for e in events))

    def test_requests_are_rate_limited_and_override_nova_lock(self):
        g,dk,lich,foe,c,locks,events=self.scene();locks[lich.handle]=20
        for t in (10,10.05,10.1,10.2,10.25):c.tick(g,g.army,[foe],t,locks)
        self.assertEqual(len(g.orders),2)
        self.assertTrue(events[0]['overrode_cast_lock'])

    def test_dk_recovery_takes_priority_and_cooldown_resumes_item(self):
        g,dk,lich,foe,c,locks,events=self.scene()
        c.tick(g,g.army,[foe],10,locks)
        g.bs[dk.handle]=[]
        c.tick(g,g.army,[foe],10.25,locks,urgent={lich.handle})
        self.assertEqual(len(g.orders),1)
        g.cd[(dk.handle,'AUdc')]=4
        c.tick(g,g.army,[foe],10.5,locks)
        self.assertEqual(len(g.orders),2)

    def test_end_of_threat_death_existing_buff_and_blocked_owner_stop_retry(self):
        for why in ('safe','healed','dead','buff','blocked','cooldown','unknown'):
            with self.subTest(why=why):
                g,dk,lich,foe,c,locks,events=self.scene()
                c.tick(g,g.army,[foe],10,locks)
                if why=='safe':foe.x=2000
                if why=='healed':lich.hp=lich.hp_max
                if why=='dead':lich.hp=0
                if why=='buff':g.bs[lich.handle]=['Bvul']
                if why=='cooldown':g.cd[(lich.handle,'AIvl')]=3
                if why=='unknown':g.cd[(lich.handle,'AIvl')]=None
                c.tick(g,g.army,[foe],11,locks,blocked={lich.handle} if why=='blocked' else ())
                self.assertEqual(len(g.orders),1)

    def test_group_scroll_iteration_does_not_erase_urgent_item_priority(self):
        g,dk,lich,foe,c,locks,events=self.scene()
        lich.hp=170;g.bags[lich.handle][:2]=['shea','pnvl']
        c.tick(g,g.army,[foe],10,locks,urgent={lich.handle})
        self.assertEqual(g.orders,[('use','Ulic','pnvl')])

    def test_approaching_tc_does_not_bypass_thirty_percent_gate(self):
        for ready in (True,False):
            g,dk,lich,foe,c,locks,events=self.scene();lich.hp=350;foe.type='Otch'
            if ready:g.bs[dk.handle]=[]
            c.tick(g,g.army,[foe],10,locks)
            self.assertFalse(g.orders)


class SilenceProtectionTests(unittest.TestCase):
    def test_full_hero_duration_protects_missing_buff_snapshot_and_aoe_heroes(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        tc=foes[2];tc.x=300;effects[tc.handle]=['Broa']
        sh=unit('Oshd',99,owner=1,x=400);sh.has_detail=True;foes.append(sh)
        effects[sh.handle]=['Broa']
        silence_key_hero(b,own,foes,10)
        self.assertGreaterEqual(b.silence_protected_until[tc.handle],19.5)
        self.assertEqual(b.silence_protected_until[sh.handle],b.silence_protected_until[tc.handle])
        orders.clear();b.destroyer.tick(b,own,foes,17)
        self.assertFalse(orders)

    def test_moving_silenced_tc_blocks_dk_hex_dispel_outside_static_area(self):
        g,b,d,own,foes,orders,events,cd,effects=dispel.BattleDispelTests().scene([])
        dk=unit('Udea',70,owner=0,x=100);dk.has_detail=True;own.append(dk)
        tc=unit('Otch',71,owner=1,x=510);tc.has_detail=True;foes.append(tc)
        effects[dk.handle]=['BOhx'];effects[tc.handle]=['BNsi','Bspe']
        d.tick(b,own,foes,10)
        self.assertFalse(orders)
        tc.x=1000;d.tick(b,own,foes,11)
        self.assertTrue(orders)
        self.assertEqual(events[-1]['reason'],'ally_hex')


class HeroSpacingTests(unittest.TestCase):
    def test_stomp_level_and_unknown_level_separate_heroes_inside_coil_range(self):
        for level in (1,2,3,None):
            b,g,own,foes,orders,dk=rear.RearDkTests().scene();lich=own[6]
            old=g.abilities
            g.abilities=lambda u:([dict(code='AOws',level=level)] if level and u.type=='Otch' else old(u))
            pulls={};b.rear_dk(own,foes,10,pulls)
            p=pulls[dk.handle];minimum=2*({1:250,2:300,3:350}.get(level,350))+32
            self.assertGreaterEqual(dist(p,lich),minimum)
            self.assertLess(dist(p,lich),750)
            self.assertLess(p[0],-140)

    def test_prebattle_heroes_start_on_separate_flanks_in_coil_range(self):
        b,g,own,foes,orders,dk=rear.RearDkTests().scene();lich=own[6]
        b.prepare_battle(1,army=own,target=(2000,0))
        separation=dist(b.prep_points[dk.handle],b.prep_points[lich.handle])
        self.assertGreater(separation,732);self.assertLess(separation,750)

    def test_separation_does_not_override_emergency_escape_or_unreachable_path(self):
        b,g,own,foes,orders,dk=rear.RearDkTests().scene()
        pulls={dk.handle:(-1000,0)};b.rear_dk(own,foes,10,pulls)
        self.assertEqual(pulls[dk.handle],(-1000,0))
        b.army_recovery.safe_path=Mock(return_value=None);pulls={}
        b.rear_dk(own,foes,12,pulls)
        self.assertEqual(pulls[dk.handle],(dk.x,dk.y))

    def test_training_telemetry_logs_only_owned_inventory_and_visible_details(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        lich=own[6];effects[lich.handle]=['BPSE'];g.inventory=Mock(return_value=['pnvl'])
        row=unit_row(g,lich)
        self.assertEqual(row['buffs'],['BPSE']);self.assertEqual(row['inventory'],['pnvl'])
        g.inventory.reset_mock();tc=foes[2];tc.has_detail=False
        row=unit_row(g,tc)
        self.assertIsNone(row['buffs']);self.assertNotIn('inventory',row);g.inventory.assert_not_called()


if __name__=='__main__':unittest.main()
