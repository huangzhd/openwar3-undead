import unittest
import test_opening_safety_0131 as tick_tests
from undead.policy import Action
from types import SimpleNamespace as N
from test_micro_loot import unit
import test_creeping as creeping_tests
import test_creep_support_01132 as support_tests
from undead.creeping import Creeping


class ShopResummonTests(unittest.TestCase):
    def scene(self):
        b,s,dk,own,orders,events=support_tests.CHResummonTests().scene()
        s.done=True
        b.creeping.cleared={'turtle','ogre'}
        b.creeping.active={'id':'shop','kind':'shop'}
        return b,s,dk,own,orders,events

    def test_shop_departure_waits_for_graveyard_cast_and_two_observed_skeletons(self):
        b,s,dk,own,orders,events=self.scene()
        self.assertTrue(s.tick(b,own,262))
        self.assertEqual(orders,[('move',(0,0))])
        dk.x=0;s.tick(b,own,266)
        self.assertEqual(orders[-1],('rod',))
        self.assertTrue(s.tick(b,own,267))
        own.extend([unit('uske',3,0),unit('uske',4,0)])
        self.assertFalse(s.tick(b,own,268))
        self.assertEqual(events[-1]['reason'],'two_new_skeletons_observed')
        self.assertEqual(events[-1]['next_camp'],'shop')
        before=list(orders);s.tick(b,own,280)
        self.assertEqual(orders,before)

    def test_shop_stop_not_repeated_for_cleared_camp_or_other_map(self):
        for change in ('cleared','map','threat'):
            b,s,dk,own,orders,events=self.scene()
            if change=='cleared':b.creeping.cleared.add('shop')
            if change=='map':b.creeping.map_alias='TM'
            if change=='threat':b.battle_enemies=[unit('hfoo',99,100)]
            self.assertFalse(s.tick(b,own,262));self.assertFalse(orders)

    def test_shop_cast_without_effect_times_out_and_does_not_claim_summons(self):
        b,s,dk,own,orders,events=self.scene();dk.x=0
        for now in (262,266,270,274):s.tick(b,own,now)
        self.assertEqual(len([o for o in orders if o[0]=='rod']),3)
        self.assertEqual(events[-1]['reason'],'bounded_timeout')
        self.assertFalse(s.tick(b,own,300))


class CampCompletionTests(unittest.TestCase):
    def test_full_tick_records_empty_camp_before_shopping_dispatch(self):
        g,b,dk,allies,orders,clock=tick_tests.EmergencyTests().controller()
        g.enemies=lambda:[];g.visible=lambda *p:True
        dk.hp=dk.hp_max
        for u in allies:u.hp=u.hp_max
        b.creeping.active=dict(id='finished-ogre',x=0,y=0,kind='ogre',hp=500,max_level=3)
        b.creeping.catalog=[b.creeping.active]
        class ShoppingReached(Exception):pass
        def shopping(*args):
            self.assertIn('finished-ogre',b.creeping.cleared)
            self.assertIsNone(b.creeping.active)
            raise ShoppingReached
        b.items=shopping
        with self.assertRaises(ShoppingReached):b.tick(forced=Action.CREEP)

    def scene(self):
        f=creeping_tests.CreepTests();g=f.game();camp=f.camps()[0];events=[]
        c=Creeping(lambda e,**k:events.append(dict(event=e,**k)),[camp]);c.active=camp
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        return c,g,camp,army,home,events

    def test_visible_clear_recorded_before_shopping_and_not_revisited_after_return(self):
        c,g,camp,army,home,events=self.scene();point=(camp['x'],camp['y'])
        self.assertTrue(c.observe_clear(g,point,237.48,[]))
        c.pause(237.48,'shopping')
        g.visible=lambda *p:False
        self.assertIsNone(c.choose(g,army,(home.x,home.y),home,249.43)[0])
        self.assertIsNone(c.choose(g,army,(home.x,home.y),home,400)[0])
        self.assertEqual([e['camp'] for e in events if e['event']=='creep_area_cleared'],['ogre'])

    def test_last_kill_below_health_threshold_is_clear_not_temporary_deferral(self):
        c,g,camp,army,home,events=self.scene()
        for u in army:u.hp=40
        c.choose(g,army,(camp['x'],camp['y']),home,240)
        self.assertIn('ogre',c.cleared)
        for u in army:u.hp=u.hp_max
        self.assertIsNone(c.choose(g,army,(home.x,home.y),home,400)[0])

    def test_hidden_distant_or_still_occupied_camp_is_not_declared_clear(self):
        for mode in ('hidden','distant','occupied'):
            c,g,camp,army,home,events=self.scene();point=(camp['x'],camp['y']);foes=[]
            if mode=='hidden':g.visible=lambda *p:False
            if mode=='distant':point=(home.x,home.y)
            if mode=='occupied':
                e=unit('nogr',9,camp['x']);e.y=camp['y'];foes=[e]
            self.assertFalse(c.observe_clear(g,point,240,foes))
            self.assertNotIn('ogre',c.cleared)
            self.assertIsNotNone(c.active)


if __name__=='__main__':unittest.main()
