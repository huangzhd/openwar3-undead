"""TC priority and rear-position casts covering clustered enemy buffs."""
import unittest
from math import hypot

import test_destroyer_01139 as old
import test_shared_battle_01181 as shared
from test_baseline import unit
from undead.battle_spells import silence_key_hero


class BattleDispelTests(unittest.TestCase):
    def scene(self,points):
        g,b,d,own,foes,orders,events,cd,res=old.DestroyerTests().scene()
        own[0].type='ubsp'
        foes[:]=[unit('otbk',20+i,owner=1,x=x) for i,(x,y) in enumerate(points)]
        for u,(_,y) in zip(foes,points):u.has_detail=True;u.y=y
        effects={u.handle:['Broa'] for u in foes}
        g.buffs=lambda u:effects.get(u.handle,[])
        return g,b,d,own,foes,orders,events,cd,effects

    def test_midpoint_clears_more_roars_than_any_unit_centre(self):
        g,b,d,own,foes,orders,events,cd,effects=self.scene([(300,-140),(300,140),(620,0)])
        d.tick(b,own,foes,10)
        self.assertEqual(orders[-1][2],dict(x=300,y=0))
        self.assertEqual(events[-1]['covered_count'],2)
        self.assertEqual(set(events[-1]['covered_handles']),{u.handle for u in foes[:2]})
        cd[(own[0].handle,'Advm')]=7
        for u in foes[:2]:effects[u.handle]=[]
        d.observe(b,11)
        self.assertEqual([e['absent'] for e in events[-1]['effects']],[['Broa'],['Broa']])

    def test_rear_cast_reaches_roar_group_with_area_without_moving_forward(self):
        g,b,d,own,foes,orders,events,cd,effects=self.scene([(700,-80),(700,80),(740,0)])
        d.tick(b,own,foes,10)
        self.assertEqual(len(orders),1)
        self.assertEqual(orders[0][1],'devourmagic')
        point=orders[0][2]
        self.assertLessEqual(hypot(point['x'],point['y']),600)
        self.assertEqual(events[-1]['covered_count'],3)
        self.assertEqual((own[0].x,own[0].y),(0,0))

    def test_new_midpoint_cannot_strip_a_protected_hero(self):
        for friendly in (False,True):
            with self.subTest(friendly=friendly):
                g,b,d,own,foes,orders,events,cd,effects=self.scene([(300,-130),(300,130)])
                hero=unit('Ulic' if friendly else 'Otch',40,owner=0 if friendly else 1,x=480)
                hero.has_detail=True
                (own if friendly else foes).append(hero)
                effects[hero.handle]=['BUfa' if friendly else 'BNsi']
                d.tick(b,own,foes,10)
                # A static 200-radius miss is no longer safe: the protected
                # hero can move into the blast before the cast lands.
                self.assertFalse(orders)

    def test_group_outside_area_envelope_does_not_trigger_chase(self):
        g,b,d,own,foes,orders,events,cd,effects=self.scene([(850,-80),(850,80)])
        d.tick(b,own,foes,10)
        self.assertFalse(orders)

    def test_pending_group_is_not_dispelled_twice_by_two_destroyers(self):
        g,b,d,own,foes,orders,events,cd,effects=self.scene([(700,-80),(700,80)])
        own[1].type='ubsp'
        d.tick(b,own,foes,10)
        self.assertEqual(len(orders),1)

    def test_three_unconfirmed_edge_casts_exhaust_the_same_target(self):
        g,b,d,own,foes,orders,events,cd,effects=self.scene([(700,0)])
        for now in (10,14,18,22,26):d.tick(b,own,foes,now)
        self.assertEqual(len(orders),3)


class SilencePriorityTests(unittest.TestCase):
    def scene(self):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene()
        tc=foes[2];tc.x=450
        sh=unit('Oshd',40,owner=1,x=200);sh.has_detail=True
        far=unit('Ofar',41,owner=1,x=150);far.has_detail=True
        foes.extend([sh,far])
        return b,g,own,foes,orders,effects,tc,sh,far

    def test_tc_beats_closer_shadow_hunter_and_farseer(self):
        b,g,own,foes,orders,effects,tc,sh,far=self.scene()
        silence_key_hero(b,own,foes,10)
        self.assertIs(orders[-1][3]['target'],tc)

    def test_buffed_tc_is_silenced_immediately_instead_of_waiting_for_dispel(self):
        b,g,own,foes,orders,effects,tc,sh,far=self.scene()
        effects[tc.handle]=['Broa','Bspe']
        silence_key_hero(b,own,foes,10)
        self.assertIs(orders[-1][3]['target'],tc)
        self.assertGreater(b.silence_protected_until[tc.handle],10)
        orders.clear();effects[tc.handle]=['Bspe','BNsi']
        silence_key_hero(b,own,foes,11)
        self.assertFalse(any(o[3]['target'] is tc for o in orders))

    def test_unactionable_tc_does_not_prevent_silencing_another_hero(self):
        for reason in ('silenced','immune','out_of_range','hidden'):
            with self.subTest(reason=reason):
                b,g,own,foes,orders,effects,tc,sh,far=self.scene()
                if reason=='silenced':effects[tc.handle]=['BNsi']
                if reason=='immune':effects[tc.handle]=['Bams']
                if reason=='out_of_range':tc.x=2000
                if reason=='hidden':tc.has_detail=False
                silence_key_hero(b,own,foes,10)
                self.assertTrue(orders)
                self.assertIsNot(orders[-1][3]['target'],tc)


if __name__=='__main__':unittest.main()
