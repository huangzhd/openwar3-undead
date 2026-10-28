import unittest
from unittest.mock import patch
import test_training_orc_focus_01180 as fixture
from undead.controller import Controller
from training import TrainingController
from undead.targeting import nightelf_ground_target


class NightElfPriorityTests(unittest.TestCase):
    def scene(self,kind=TrainingController):
        b,g,army,foes,orders,events,effects=fixture.TrainingOrcFocusTests().scene()
        b.__class__=kind
        foes[0].type='ehip';foes[0].hp=500
        foes[1].type='edcm';foes[1].hp=600
        foes[2].type='Ekee';foes[2].hp=1
        army[8].x=0
        effects[foes[0].handle]=['Bweb']
        return b,g,army,foes,orders,events,effects

    def test_both_controllers_ignore_webbed_hippo_and_focus_bear(self):
        for kind in (Controller,TrainingController):
            b,g,a,e,orders,events,fx=self.scene(kind)
            b.focus_ranged(a,e,10)
            self.assertTrue(orders)
            self.assertEqual({o[2] for o in orders if o[0]=='attack'},{e[1].handle})
            orders.clear();b.attack_destroyers(a,e,10)
            self.assertIn(('attack',a[8].handle,e[1].handle),orders)
            orders.clear();b.attack_destroyers(a,e,12)
            self.assertFalse(orders) # Keep the current bear attack.

    def test_ground_priority_requires_visible_live_vulnerable_in_range_target(self):
        for reason in ('hidden','dead','immune','far'):
            b,g,a,e,orders,events,fx=self.scene()
            if reason=='hidden':e[1].visible_to=lambda _:False
            if reason=='dead':e[1].hp=0
            if reason=='immune':fx[e[1].handle]=['Bvul']
            if reason=='far':e[1].x=2000
            self.assertIsNone(nightelf_ground_target(g,a,e),reason)

    def test_exposed_dryad_overrides_bear_but_rear_dryad_does_not(self):
        b,g,a,e,orders,events,fx=self.scene()
        e[2].type='edry';e[2].is_hero=False;e[2].x=300
        b.focus_ranged(a,e,10)
        self.assertEqual({o[2] for o in orders if o[0]=='attack'},{e[2].handle})
        orders.clear();e[2].x=550
        b.focus_ranged(a,e,12)
        self.assertEqual({o[2] for o in orders if o[0]=='attack'},{e[1].handle})
        orders.clear();e[1].hp=0
        b.attack_destroyers(a,e,13)
        self.assertFalse(orders) # No magic attacks against dryads or chasing hippogryphs.

    def test_retreat_and_spell_locks_keep_ownership(self):
        b,g,a,e,orders,events,fx=self.scene()
        b.micro.pulling.add(a[0].handle)
        b.cast_until[a[6].handle]=12
        b.focus_ranged(a,e,10)
        self.assertFalse(any(o[1] in {a[0].handle,a[6].handle} for o in orders))
        for reason in ('wounded','blocked','casting','pulling'):
            b,g,a,e,orders,events,fx=self.scene();d=a[8]
            if reason=='wounded':d.hp=200
            if reason=='casting':b.cast_until[d.handle]=12
            if reason=='pulling':b.micro.pulling.add(d.handle)
            b.attack_destroyers(a,e,10,{d.handle} if reason=='blocked' else ())
            self.assertFalse(orders,reason)

    def test_bear_spell_branch_does_not_start_hero_nc(self):
        b,g,a,e,orders,events,fx=self.scene()
        with patch('undead.controller.nova_tc') as nova, patch.object(b.nc_combo,'try_cast') as combo:
            b.combat_spells(a,e,10)
            self.assertIs(nova.call_args.args[2],e[1])
            combo.assert_not_called()

    def test_dispel_treant_then_hero_rejuvenation_then_roar(self):
        for removed,expected in ((0,0),(1,2),(2,1)):
            b,g,a,e,orders,events,fx=self.scene()
            e[0].type='efon';e[0].x=500
            e[1].x=-500
            e[2].x=0;e[2].y=500
            fx.clear();fx[e[1].handle]=['Broa'];fx[e[2].handle]=['Brej']
            enemies=e[:]
            if removed>=1:enemies.remove(e[0])
            if removed>=2:fx[e[2].handle]=[]
            b.destroyer.tick(b,a,enemies,10)
            casts=[v for name,v in events if name=='destroyer_dispel_attempt']
            self.assertTrue(casts)
            self.assertEqual(casts[0]['target'],e[expected].handle)

    def test_nova_hits_bear_and_respects_caster_protection(self):
        for blocked in (False,True,'shopping'):
            b,g,a,e,orders,events,fx=self.scene()
            g.hero_spell_level=lambda u,c:1
            g.hero_spell_ready=lambda *args:True
            if blocked=='shopping':b.shopping.add(a[6].handle)
            b.combat_spells(a,e,10,{a[6].handle} if blocked is True else ())
            novas=[o for o in orders if o[0]=='cast' and o[2]=='frostnova']
            if blocked:self.assertFalse(novas)
            else:
                self.assertEqual(len(novas),1)
                self.assertIs(novas[0][3]['target'],e[1])

    def test_single_close_hippo_draws_destroyer_back_instead_of_attacking_it(self):
        b,g,a,e,orders,events,fx=self.scene();d=a[8]
        e[0].x=100
        g.current_target=lambda u:d if u is e[0] else None
        self.assertTrue(b.destroyer_focused(d,e))
        pulls={};b.rear_destroyers(a,e,10,pulls,None)
        self.assertIn(d.handle,pulls)
        self.assertLess(pulls[d.handle][0],d.x)
        b.attack_destroyers(a,e,10,set(pulls))
        self.assertFalse(any(o[0]=='attack' for o in orders))

    def test_altar_choice_is_bounded_and_requires_observed_naga(self):
        from test_baseline import unit
        b,g,a,e,orders,events,fx=self.scene()
        altar=unit('u003',90,owner=0,x=-1500);a.append(altar)
        g.train=lambda u,code:orders.append(('train',u.handle,code)) or True
        b.start_potion_since=1
        for now in (25,26,28,31,34):b.choose_opening_hero(now)
        self.assertEqual(orders,[('train',altar.handle,'N004')]*3)
        self.assertFalse(b.altar_choice['done'])
        self.assertEqual(b.start_potion_since,1)
        a.remove(altar);a.append(unit('Nngs',91,owner=0))
        b.choose_opening_hero(35)
        self.assertTrue(b.altar_choice['done'])
        self.assertEqual(b.start_potion_since,35)
        b.choose_opening_hero(40)
        self.assertEqual(len(orders),3)


if __name__=='__main__':unittest.main()
