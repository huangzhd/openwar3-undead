import unittest
import test_tp_escort_01104 as old
import test_opening_safety_0131 as ticks
from test_micro_loot import unit
from undead.policy import Action,choose_rule


class TavernPauseTests(unittest.TestCase):
    def scene(self):
        b,a,shops,m,buys,ev,res=old.TavernEscortTests().make()
        b.tavern_group_requested=True
        return b,a,shops,m,buys,ev,res

    def test_th_combat_interval_resumes_hire_and_actual_hero_allows_attack(self):
        b,a,shops,m,buys,ev,res=self.scene()
        self.assertTrue(b.escort_tavern(a,[],499.03,3))
        b.player_contact=[unit('earc',99,100)]
        self.assertFalse(b.escort_tavern(a,[],523.555,3))
        b.player_contact=[]
        self.assertTrue(b.escort_tavern(a,[],605.605,3))
        self.assertFalse(b.tavern_escort_done)
        for u in a:u.x=0
        self.assertTrue(b.escort_tavern(a,[],610,3))
        self.assertEqual(buys,['Nbrn']);self.assertFalse(b.situation.third_hero)
        a.append(unit('Nbrn',77,0))
        b.recruit_tavern(a,[],611,3,set())
        self.assertFalse(b.escort_tavern(a,[],611,3))
        b.situation.third_hero=b.third_hero_ready([u for u in a if u.is_hero],(0,0))
        self.assertEqual(choose_rule(b.situation),Action.ATTACK)

    def test_local_combat_exceeding_wall_timeout_does_not_consume_travel_budget(self):
        b,a,shops,m,buys,ev,res=self.scene()
        for u in a:u.x=0
        enemy=unit('ntrg',99,100);enemy.owner=12;fought=[]
        b.fight=lambda army,foes,now:fought.append(now)
        for now in (100,150,290,400):self.assertTrue(b.escort_tavern(a,[enemy],now,3))
        self.assertFalse(buys)
        self.assertTrue(b.escort_tavern(a,[],401,3))
        self.assertEqual(buys,['Nbrn']);self.assertEqual(fought,[100,150,290,400])
        self.assertEqual(b.tavern_escort_trips,1)

    def test_real_stall_retries_three_times_then_stops(self):
        b,a,shops,m,buys,ev,res=self.scene()
        for start in (100,140,180):
            self.assertTrue(b.escort_tavern(a,[],start,3))
            self.assertFalse(b.escort_tavern(a,[],start+31,3))
            self.assertFalse(b.escort_tavern(a,[],start+32,3))
        before=list(m)
        for now in (220,400,1000):self.assertFalse(b.escort_tavern(a,[],now,3))
        self.assertEqual(m,before);self.assertTrue(b.tavern_escort_done)
        self.assertFalse(buys)

    def test_combat_pause_preserves_three_purchase_limit_and_real_observation(self):
        b,a,shops,m,buys,ev,res=self.scene()
        for u in a:u.x=0
        b.escort_tavern(a,[],100,3)
        b.action=Action.DEFEND;b.escort_tavern(a,[],101,3)
        b.action=Action.CREEP;b.escort_tavern(a,[],300,3)
        b.escort_tavern(a,[],309,3)
        self.assertFalse(b.escort_tavern(a,[],318,3))
        self.assertEqual(buys,['Nbrn']*3);self.assertFalse(b.situation.third_hero)

    def test_full_tick_pauses_before_emergency_portal_early_return(self):
        g,b,dk,allies,orders,clock=ticks.EmergencyTests().controller()
        b.tavern_escort=dict(started=50,progress_at=90,best=1000,buys=0,buy_at=-100,accepted_at=None)
        b.tick()
        self.assertEqual(orders[0][0],'portal')
        self.assertEqual(b.tavern_escort['paused_at'],100)
        clock[0]=101;b.tick()
        self.assertEqual(b.tavern_escort['paused_at'],100)


if __name__=='__main__':unittest.main()
