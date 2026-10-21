import unittest
from unittest.mock import Mock
import test_tc_pressure_01186 as pressure
import test_equipment as equipment
import test_rear_support_01184 as rear
from undead.consumables import Consumables
from undead.controller import Controller
from training import TrainingController


class PotionTests(unittest.TestCase):
    def test_health_potion_handoff_and_actual_inventory_confirmation(self):
        for code in ('phea','pghe'):
            old=equipment.EquipmentTests();g,e,events=old.setup_game()
            g.inv[g.dk.handle][0]=code
            self.assertTrue(e.tick(g,g.heroes,[],1,{},potions_only=True))
            self.assertFalse(any(n=='equipment_transfer_confirmed' for n,_ in events))
            old.observed_transfer(g);e.tick(g,g.heroes,[],4,{},potions_only=True)
            self.assertIn(code,g.inv[g.lich.handle]);self.assertNotIn(code,g.inv[g.dk.handle])
            self.assertTrue(any(n=='equipment_transfer_confirmed' for n,_ in events))

    def test_potion_handoff_does_not_approach_through_fire_or_displace_full_inventory(self):
        for why in ('far','full','busy','danger'):
            g,e,_=equipment.EquipmentTests().setup_game();g.inv[g.dk.handle][0]='pghe';locks={};foes=[]
            if why=='far':g.lich.x=1000
            if why=='full':g.inv[g.lich.handle]=['ocor']*6
            if why=='busy':locks[g.dk.handle]=20
            if why=='danger':foes=[g.dk]
            self.assertFalse(e.tick(g,g.heroes,foes,10,locks,potions_only=True));self.assertFalse(g.transfers)

    def test_lich_uses_invul_before_health_below_thirty_percent_then_heals_under_invul(self):
        g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();lich.hp=170;g.bs[dk.handle]=['BOhx']
        g.effect=True;g.bags[lich.handle][:2]=['phea','pnvl'];locks={}
        c=Consumables(lambda *a,**kw:None)
        c.tick(g,g.army,[foe],10,locks)
        self.assertEqual(g.orders,[('use','Ulic','pnvl')])
        c.tick(g,g.army,[foe],10.25,locks)
        self.assertEqual(g.orders[-1],('use','Ulic','phea'))
        self.assertGreater(lich.hp,300)

    def test_lich_waits_for_available_dk_instead_of_spending_either_potion(self):
        g,dk,lich,foe=rear.LichInvulnerabilityTests().scene()
        c=Consumables(lambda *a,**kw:None);c.tick(g,g.army,[foe],10,{})
        self.assertFalse(g.orders)

    def test_lich_uses_health_if_invul_missing_or_on_cooldown(self):
        for why in ('missing','cooldown'):
            g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();g.bs[dk.handle]=['BOhx']
            if why=='missing':g.bags[lich.handle][1]=None
            else:g.cd[(lich.handle,'AIvl')]=3
            Consumables(lambda *a,**kw:None).tick(g,g.army,[foe],10,{})
            self.assertEqual(g.orders,[('use','Ulic','pghe')])

    def test_dk_drinks_blue_below_75_even_during_coil_cooldown_without_target(self):
        for mana in (0,74,75):
            g,dk,lich,foe=rear.LichInvulnerabilityTests().scene();g.bags[lich.handle]=[None]*6
            g.bags[dk.handle][0]='pman';dk.mana=mana;g.cd[(dk.handle,'AUdc')]=4
            Consumables(lambda *a,**kw:None).tick(g,g.army,[],10,{})
            self.assertEqual(('use','Udea','pman') in g.orders,mana<75)


class BurrowTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene(kind)
        fiend=own[0];fiend.hp=200;dk.mana=0
        old=g.abilities;g.abilities=lambda u:([dict(code='Abur',level=1)] if u.type in ('ucry','ucrm') else old(u))
        g.tech_many=lambda codes:{c:1 for c in codes}
        return b,g,own,foes,orders,events,effects,dk,fiend

    def step(self,scene,now):
        b,g,own,foes,orders,events,effects,dk,fiend=scene
        return b.fiend_burrow.tick(b,[u for u in own if u.type in ('ucry','ucrm')],[u for u in own if u.is_hero],foes,now)

    def test_both_controllers_burrow_when_dk_has_no_mana_or_coil_cooldown(self):
        for kind in (Controller,TrainingController):
            for why in ('mana','cooldown'):
                s=self.scene(kind);b,g,own,foes,orders,events,effects,dk,f=s
                if why=='cooldown':dk.mana=300;g.cooldown=lambda u,c:3 if c=='AUdc' else 0
                reserved=self.step(s,10)
                self.assertIn(f.handle,reserved)
                self.assertTrue(any(o[:3]==('cast',f.handle,'burrow') for o in orders))
                self.assertFalse(any(e=='fiend_burrow_observed' for e,_ in events))

    def test_ready_coil_precedes_burrow_and_unknown_research_or_ability_does_not_fake_it(self):
        for why in ('coil','research','unknown','ability','cooldown','controlled'):
            s=self.scene();b,g,own,foes,orders,events,effects,dk,f=s
            if why=='coil':dk.mana=300
            if why=='research':g.tech_many=lambda codes:{'Rubu':0}
            if why=='unknown':g.tech_many=lambda codes:{'Rubu':None}
            if why=='ability':g.abilities=lambda u:[]
            if why=='cooldown':g.cooldown=lambda u,c:None
            if why=='controlled':effects[f.handle]=['BPSE']
            self.assertNotIn(f.handle,self.step(s,10));self.assertFalse(orders)

    def test_actual_morph_stays_protected_until_70_percent_then_surfaces(self):
        s=self.scene();b,g,own,foes,orders,events,effects,dk,f=s
        self.step(s,10);f.type='ucrm';self.assertIn(f.handle,self.step(s,12))
        self.assertTrue(any(e=='fiend_burrow_observed' and k['type']=='ucrm' for e,k in events))
        orders.clear();f.hp=410;self.step(s,13);self.assertFalse(orders)
        f.hp=420;self.assertIn(f.handle,self.step(s,14))
        self.assertEqual(orders[-1][:3],('cast',f.handle,'unburrow'))
        f.type='ucry';self.assertNotIn(f.handle,self.step(s,16))
        self.assertTrue(any(e=='fiend_burrow_observed' and k['type']=='ucry' for e,k in events))

    def test_rejected_or_unobserved_burrows_stop_after_three_attempts(self):
        s=self.scene();b,g,own,foes,orders,events,effects,dk,f=s
        for t in (10,13,16,19,22):self.step(s,t)
        self.assertEqual(len(orders),3)
        self.assertFalse(any(e=='fiend_burrow_observed' for e,_ in events))

    def test_taking_damage_underground_surfaces_for_escape_without_immediate_reburrow(self):
        s=self.scene();b,g,own,foes,orders,events,effects,dk,f=s
        f.type='ucrm';self.step(s,10);f.hp=160;self.step(s,11)
        self.assertEqual(orders[-1][:3],('cast',f.handle,'unburrow'))
        f.type='ucry';orders.clear();self.step(s,13);self.assertFalse(orders)


class OpeningNCTests(unittest.TestCase):
    def test_waits_briefly_for_coil_range_then_casts_nc_not_heal_on_injured_fiend(self):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene()
        dk.x=-600;own[0].hp=200
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertTrue(b.opening_nc_waiting)
        self.assertFalse(any(o[0]=='cast' and o[2] in ('frostnova','deathcoil') for o in orders))
        tc.x=100;orders.clear();b.combat_spells(own,foes,11)
        casts=[o for o in orders if o[0]=='cast' and o[2] in ('frostnova','deathcoil')]
        self.assertEqual([o[2] for o in casts],['frostnova','deathcoil'])
        self.assertTrue(all(o[3]['target'] is tc for o in casts))

    def test_unreachable_pair_does_not_wait_forever_or_move_dk_into_fire(self):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene();dk.x=-600
        b.combat_spells(own,foes,10);orders.clear();pulls={}
        b.rear_dk(own,foes,11,pulls)
        self.assertFalse(pulls);self.assertIn(('hold',dk.handle),orders)
        b.combat_spells(own,foes,13.1)
        self.assertFalse(b.opening_nc_waiting)
        self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' for o in orders))

    def test_lich_rescue_preempts_opening_wait(self):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene();dk.x=-600;lich=own[6];lich.hp=100
        b.combat_spells(own,foes,10)
        self.assertFalse(b.opening_nc_waiting)
        self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target'] is lich for o in orders))


if __name__=='__main__':unittest.main()
