import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
import test_tavern_0145 as prior
from test_micro_loot import unit,dist
from undead.scouting import SkeletonScouts

class TavernLifetimeTests(unittest.TestCase):
    def game(self):return prior.TavernTests().setup_game()

    def test_longest_confirmed_lifetime_beats_nearer_old_skeleton_and_fiend(self):
        b,a,shops,m,buys,ev,res=self.game()
        old=unit('uske',70,-500);young=unit('uske',71,-3000);a.extend([old,young])
        b.skeleton_expiry={old.handle:50,young.handle:75}
        b.recruit_tavern(a,[],10,3,set())
        self.assertEqual(b.tavern_mission['courier'],young.handle)
        self.assertEqual(m,[(young.handle,(0,0))])
        young.x=0;b.recruit_tavern(a,[],22,3,set());self.assertEqual(buys,['Nbrn'])
        a.append(unit('Nbrn',80,0));b.recruit_tavern(a,[],23,3,set())
        self.assertIn(young.handle,b.tavern_joiners)
        self.assertIn(a[-1].handle,b.tavern_joiners)

    def test_old_unknown_or_insufficient_lifetime_uses_fiend(self):
        for reason in ['old','unknown','far','unreachable']:
            with self.subTest(reason=reason):
                b,a,s,m,buys,ev,res=self.game();sk=unit('uske',70,-100);a.append(sk)
                if reason=='old':b.skeleton_expiry[sk.handle]=39
                if reason=='far':sk.x=-10000;b.skeleton_expiry[sk.handle]=75
                if reason=='unreachable':
                    b.skeleton_expiry[sk.handle]=75
                    b.g.path_distance=lambda x,y:None if x==(sk.x,sk.y) else dist(x,y)
                b.recruit_tavern(a,[],10,3,set())
                selected=next(u for u in a if u.handle==b.tavern_mission['courier'])
                self.assertEqual(selected.type,'ucry')

    def test_unknown_tavern_requires_extra_search_time(self):
        b,a,s,m,buys,ev,res=self.game();s.clear();sk=unit('uske',70,-3000);a.append(sk)
        b.skeleton_expiry[sk.handle]=52 # 42 left: enough for known shop, not centre + search.
        b.recruit_tavern(a,[],10,3,set())
        self.assertNotEqual(b.tavern_mission['courier'],sk.handle)

    def test_route_delay_rechecks_lifetime_and_cancels_before_expiry(self):
        b,a,s,m,buys,ev,res=self.game();sk=unit('uske',70,-3000);a.append(sk);b.skeleton_expiry[sk.handle]=75
        b.recruit_tavern(a,[],10,3,set());self.assertEqual(b.tavern_mission['courier'],sk.handle)
        sk.x=-2500;b.recruit_tavern(a,[],30,3,set())
        self.assertIsNotNone(b.tavern_mission)
        sk.x=-2450;b.recruit_tavern(a,[],48,3,set())
        self.assertIsNone(b.tavern_mission);self.assertFalse(buys)
        self.assertIn('lifetime_insufficient',[r.get('reason') for r in ev])

    def test_skeleton_disappearance_requests_group_instead_of_another_solo_trip(self):
        b,a,s,m,buys,ev,res=self.game();sk=unit('uske',70,-3000);a.append(sk);b.skeleton_expiry[sk.handle]=75
        b.recruit_tavern(a,[],10,3,set());a.remove(sk)
        b.recruit_tavern(a,[],13,3,set());self.assertIsNone(b.tavern_mission)
        b.recruit_tavern(a,[],44,3,set())
        self.assertIsNone(b.tavern_mission)
        self.assertTrue(b.tavern_group_requested)

    def test_main_assault_keeps_two_skeletons_and_active_scout_is_not_reassigned(self):
        b,a,s,m,buys,ev,res=self.game();b.attacking_main=True
        skeletons=[unit('uske',70+i,-1000) for i in range(2)];a.extend(skeletons)
        b.skeleton_expiry={u.handle:75 for u in skeletons}
        b.recruit_tavern(a,[],10,3,set())
        self.assertNotIn(b.tavern_mission['courier'],{u.handle for u in skeletons})
        b,a,s,m,buys,ev,res=self.game();sk=unit('uske',70,-1000);a.append(sk)
        b.skeleton_expiry[sk.handle]=75;b.skeleton_scouts.assignments[sk.handle]=dict(point=(4000,0),started=0)
        b.recruit_tavern(a,[],10,3,set());self.assertNotEqual(b.tavern_mission['courier'],sk.handle)

    def test_expansion_scouting_cannot_overwrite_tavern_courier_or_returner(self):
        own=[unit('uske',70+i,100*i) for i in range(5)]
        g=N(units=lambda *args:own,dist=dist,path_distance=dist,visible=lambda *p:False)
        scouts=SkeletonScouts(lambda *args,**kw:None);reserved={own[3].handle,own[4].handle}
        orders=scouts.plan(g,(0,0),(-5000,0),(500,0),[(3000,0),(0,4000)],[],10,True,reserved)
        self.assertTrue(orders);self.assertFalse({u.handle for u,p in orders}&reserved)
        self.assertEqual({u.handle for u,p in orders},{own[2].handle})

    def rod_game(self):
        b,a,s,m,buys,ev,res=self.game();old=unit('uske',70,-2000);live=[old]
        b.g.units=lambda side,codes:live if codes=={'uske'} else s
        b.g.use_item=lambda *args:True
        return b,a[0],old,live,ev

    def test_only_new_actual_summons_get_cast_based_expiry_not_existing_units(self):
        b,dk,old,live,ev=self.rod_game()
        with patch('undead.controller.rod_skeleton_lifetime',return_value=65):
            b.use_rod(dk,0,10);b.observe_rod_skeletons(10.5)
            self.assertFalse(b.skeleton_expiry) # Accepted order does not prove a summon.
            fresh=unit('uske',71,-2100);live.append(fresh);b.observe_rod_skeletons(11)
            self.assertNotIn(old.handle,b.skeleton_expiry)
            remaining,required=b.tavern_lifetime_budget(fresh,20,3000,True)
            self.assertGreater(remaining,required)
            b.observe_rod_skeletons(12)
            self.assertEqual(b.tavern_lifetime_budget(fresh,25,3000,True)[0],remaining-5)
            b.use_rod(dk,0,30);b.observe_rod_skeletons(31)
            self.assertEqual(b.tavern_lifetime_budget(fresh,31,3000,True)[0],remaining-11)
            live.remove(fresh);b.observe_rod_skeletons(32);self.assertFalse(b.skeleton_expiry)

    def test_rejected_cast_or_stale_spawn_or_remote_unit_has_no_known_lifetime(self):
        for reason in ['rejected','stale','remote','no_data']:
            b,dk,old,live,ev=self.rod_game()
            b.g.use_item=lambda *args:reason!='rejected'
            with patch('undead.controller.rod_skeleton_lifetime',return_value=0 if reason=='no_data' else 65):
                b.use_rod(dk,0,10)
                live.append(unit('uske',71,5000 if reason=='remote' else -2100))
                b.observe_rod_skeletons(15 if reason=='stale' else 11)
                self.assertFalse(b.skeleton_expiry)
