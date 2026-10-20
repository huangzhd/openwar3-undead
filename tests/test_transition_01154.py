import unittest
from types import SimpleNamespace as N
import test_economy_timing_01131 as timing
import test_tp_escort_01104 as tavern
from test_baseline import unit
from test_micro_loot import unit as fighter
from undead.policy import Action,choose_rule


class OrderedTransitionTests(unittest.TestCase):
    def scene(self):
        g,e=timing.TransitionBudgetTests().game(2)
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[2:]]
        g.own=[u for u in g.own if u.type not in {'uzig','ubsp'}]
        g.own += [unit('uzig',910+i,owner=0,x=1000+i*500) for i in range(2)]
        g.cap=30;g.food=22;g.gold=2000;g.lumber=1200
        events=[];e.log=lambda event,**kw:events.append(dict(event=event,**kw))
        return g,e,events

    def foundation(self,g,code,handle):
        b=unit(code,handle,owner=0);b.x,b.y=g.builds[-1][2:];b.hp=10;g.own.append(b)
        g.busy[b.handle]=N(kind='construction',queue=[code]);return b

    def pay_heroes(self,g,e):
        e.tick(g,300);self.assertEqual(g.commands,['unp2'])
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'],progress=.1)
        e.tick(g,304);self.assertEqual(g.commands,['unp2','Ulic']);g.food+=5

    def test_actual_full_chain_including_pending_builds_and_food_capacity(self):
        g,e,events=self.scene();self.pay_heroes(g,e)
        e.tick(g,308);self.assertEqual([x[1] for x in g.builds],['uslh'])
        crypt=g.my_buildings({'usep'})[0]
        self.assertFalse(e.train(g,crypt,'ucry',309))
        self.foundation(g,'uslh',920)
        e.tick(g,312);self.assertEqual([x[1] for x in g.builds],['uslh','uzig'])
        self.assertFalse(e.train(g,crypt,'ucry',313))
        tower=self.foundation(g,'uzig',921)
        # A real unfinished third foundation preserves order; engine food still decides training.
        g.food=28;self.assertFalse(e.train(g,crypt,'ucry',316));self.assertEqual(g.commands,['unp2','Ulic'])
        g.cap=40;tower.hp=tower.hp_max;g.busy.pop(tower.handle)
        e.tick(g,320)
        self.assertEqual(g.commands,['unp2','Ulic','ucry'])
        purchases=[r['code'] for r in events if r['event']=='purchase']
        self.assertEqual(purchases,['unp2','Ulic','uslh','uzig','ucry'])

    def test_house_placement_failure_cannot_train_third_fiend_or_build_tower(self):
        g,e,events=self.scene();self.pay_heroes(g,e)
        g.build_near=lambda *a,**kw:None
        for t in (308,320,340):e.tick(g,t)
        self.assertFalse(g.builds);self.assertEqual(g.commands,['unp2','Ulic'])

    def test_insufficient_house_funds_are_reserved_before_third_tower(self):
        g,e,events=self.scene();self.pay_heroes(g,e);g.gold=139
        for t in (308,312):e.tick(g,t)
        self.assertFalse(g.builds);self.assertEqual(g.commands,['unp2','Ulic']);self.assertEqual(g.gold,139)

    def test_third_tower_is_built_even_if_losses_leave_spare_population(self):
        g,e,events=self.scene();self.pay_heroes(g,e);g.food=20
        e.tick(g,308);self.foundation(g,'uslh',920);e.tick(g,312)
        self.assertEqual([x[1] for x in g.builds],['uslh','uzig'])
        self.assertNotIn('ucry',g.commands)

    def test_optional_worker_cannot_consume_lich_reserved_population(self):
        g,e,events=self.scene();g.own=[u for u in g.own if u.type!='uaco']+[unit('uaco',940+i,owner=0) for i in range(5)]
        g.food=25
        self.assertFalse(e.train(g,g.own[0],'uaco',290));self.assertFalse(g.commands)


class GroupTavernFallbackTests(unittest.TestCase):
    def test_first_stalled_trip_moves_group_then_observed_hero_unlocks_attack(self):
        b,a,shops,m,buys,ev,res=tavern.TavernEscortTests().make()
        b.recruit_tavern(a,[],505.555,3,set())
        b.recruit_tavern(a,[],531.505,3,set());m.clear()
        self.assertTrue(b.escort_tavern(a,[],531.505,3))
        self.assertEqual({h for h,p in m},{u.handle for u in a})
        self.assertFalse(buys);self.assertEqual(b.tavern_trips,1)
        b.recruit_tavern(a,[],570,3,set());self.assertIsNone(b.tavern_mission)
        for u in a:u.x=0
        b.escort_tavern(a,[],571,3);self.assertEqual(buys,['Nbrn'])
        self.assertFalse(b.situation.third_hero)
        a.append(fighter('Nbrn',77,0));b.recruit_tavern(a,[],572,3,set())
        self.assertFalse(b.escort_tavern(a,[],572,3))
        b.situation.third_hero=b.third_hero_ready([u for u in a if u.is_hero],(0,0))
        self.assertEqual(choose_rule(b.situation),Action.ATTACK)

    def test_no_available_solo_courier_triggers_group_after_bounded_wait(self):
        b,a,shops,m,buys,ev,res=tavern.TavernEscortTests().make()
        # No eligible solo unit; a healthy hero-led group can still move together.
        a[:]=[u for u in a if u.is_hero]
        b.recruit_tavern(a,[],500,3,set());self.assertFalse(b.escort_tavern(a,[],500,3))
        b.recruit_tavern(a,[],531,3,set());m.clear()
        self.assertTrue(b.escort_tavern(a,[],531,3))
        self.assertEqual({h for h,p in m},{u.handle for u in a})

    def test_returning_courier_does_not_hold_the_main_group_in_place(self):
        b,a,shops,m,buys,ev,res=tavern.TavernEscortTests().make()
        b.tavern_group_requested=True;b.tavern_joiners.add(a[-1].handle)
        main=a[:-1]
        self.assertTrue(b.escort_tavern(main,[],500,3))
        self.assertEqual({h for h,p in m},{u.handle for u in main})

    def test_player_threat_still_preempts_group_hire(self):
        b,a,shops,m,buys,ev,res=tavern.TavernEscortTests().make()
        b.tavern_group_requested=True;b.action=Action.DEFEND
        self.assertFalse(b.escort_tavern(a,[],500,3));self.assertFalse(m);self.assertFalse(buys)


if __name__=='__main__':unittest.main()
