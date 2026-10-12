import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_scout_opening as opening
from undead.scouting import CritterSearch

class CritterSearchTests(unittest.TestCase):
    def make(self):
        scout=unit('uaco',1,0,220);home=N(x=0,y=0);visible=[];events=[];queries=[]
        def vision(x,y):queries.append((x,y));return dist(home,(x,y))<=1200
        g=N(dist=dist,path_distance=dist,visible=vision,units=lambda side:visible)
        search=CritterSearch(lambda e,**kw:events.append(dict(event=e,**kw)),spawns=[])
        return search,g,scout,home,visible,events,queries

    def test_visible_inner_ring_is_skipped_for_unseen_outer_ground(self):
        s,g,u,h,v,e,q=self.make();point=s.choose(g,u,h,65)
        self.assertGreater(dist(h,point),1200)
        self.assertTrue(any(dist(h,p)>2400 for p in s.points))
        self.assertLessEqual(len(q),12)
        s.choose(g,u,h,65.2);self.assertLessEqual(len(q),12)

    def test_unknown_visibility_is_not_counted_as_searched(self):
        s,g,u,h,v,e,q=self.make();g.visible=lambda *p:None
        point=s.choose(g,u,h,65);u.x,u.y=point;s.choose(g,u,h,66)
        self.assertNotIn(point,s.checked)

    def test_temporarily_unknown_path_can_recover_without_false_coverage(self):
        s,g,u,h,v,e,q=self.make();g.path_distance=lambda *p:None
        self.assertIsNone(s.choose(g,u,h,65));self.assertFalse(s.failed)
        g.path_distance=dist
        self.assertIsNotNone(s.choose(g,u,h,71))
        self.assertFalse(s.failed)

    def test_all_blocked_routes_are_bounded_and_not_claimed_visible(self):
        s,g,u,h,v,e,q=self.make();g.visible=lambda *p:False;g.path_distance=lambda *p:None
        for t in range(65,105):s.choose(g,u,h,t)
        self.assertEqual(len(s.failed),36);self.assertFalse(s.checked)
        self.assertTrue(all(attempts==2 for attempts in s.route_attempts.values()))
        self.assertEqual(sum(r['event']=='scout_search_exhausted' for r in e),1)

    def test_ground_route_progress_survives_temporary_euclidean_detour(self):
        s,g,u,h,v,e,q=self.make();g.visible=lambda *p:False
        p=s.choose(g,u,h,65);route=[800]
        g.path_distance=lambda *args:route[0]
        # Walking around an obstacle can initially increase straight-line distance.
        u.x,u.y=-p[0],-p[1]
        self.assertEqual(s.choose(g,u,h,72),p)
        route[0]=600
        self.assertEqual(s.choose(g,u,h,79),p)
        self.assertNotIn(p,s.failed)

    def test_time_budget_and_enemy_route_guard_exclude_bad_destinations(self):
        s,g,u,h,v,e,q=self.make()
        self.assertIsNone(s.choose(g,u,h,148))
        self.assertIsNone(s.choose(g,u,h,150))
        s,g,u,h,v,e,q=self.make()
        for t in range(65,75):
            point=s.choose(g,u,h,t,safe_route=lambda a,b:b[0]<=0)
            if point:self.assertLessEqual(point[0],0);break
        self.assertIsNotNone(point)

    def test_ground_critter_types_and_neutral_owners_only(self):
        s,g,u,h,v,e,q=self.make()
        for code,owner in (('nalb',15),('hfoo',15),('nshe',1)):
            animal=unit(code,10,100,15);animal.owner=owner;v[:]=[animal]
            self.assertIsNone(s.target(g,u,h,65))
        animal=unit('nshe',11,2500,15);animal.owner=14;v[:]=[animal]
        self.assertIs(s.target(g,u,h,66),animal)

    def test_reachable_critter_beats_nearer_one_across_obstacle(self):
        s,g,u,h,v,e,q=self.make()
        close=unit('nshe',10,100,15);far=unit('nrat',11,300,15)
        close.owner=far.owner=15;v[:]=[close,far]
        g.path_distance=lambda a,b:None if b is close else dist(a,b)
        self.assertIs(s.target(g,u,h,65),far)

    def test_visible_critter_does_not_bypass_enemy_route_guard(self):
        s,g,u,h,v,e,q=self.make();animal=unit('nshe',10,300,15);animal.owner=15;v.append(animal)
        self.assertIsNone(s.target(g,u,h,65,safe_route=lambda a,b:False))
        self.assertIs(s.target(g,u,h,66,safe_route=lambda a,b:True),animal)
        self.assertIsNone(s.target(g,u,h,67,safe_route=lambda a,b:False))

    def test_stalled_critter_is_abandoned_and_another_can_be_hunted(self):
        s,g,u,h,v,e,q=self.make();animal=unit('nshe',10,300,15);animal.owner=15;v.append(animal)
        self.assertIs(s.target(g,u,h,65),animal)
        self.assertIsNone(s.target(g,u,h,73))
        other=unit('nrat',11,400,15);other.owner=15;v.append(other)
        self.assertIs(s.target(g,u,h,74),other)
        self.assertIn(animal.handle,s.hunt_failed)

    def test_damage_progress_keeps_hunt_but_total_budget_is_finite(self):
        s,g,u,h,v,e,q=self.make();animal=unit('nshe',10,100,15);animal.owner=15;v.append(animal)
        self.assertIs(s.target(g,u,h,65),animal)
        animal.hp=10;self.assertIs(s.target(g,u,h,72),animal)
        animal.hp=5;self.assertIs(s.target(g,u,h,79),animal)
        animal.hp=1;self.assertIsNone(s.target(g,u,h,85))

    def test_controller_attacks_new_outer_critter_and_never_infers_hidden_death(self):
        b,g,d,c,own,units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        b.scout_critter=None;c.x=500;c.hp=15;c.alive=True
        b.scout(100);self.assertEqual(orders[-1][0],'attack')
        units.remove(c);b.scout(104)
        self.assertIsNone(b.scout_corpse);self.assertEqual(orders[-1][2],(500,0))

    def test_empty_search_leaves_for_enemy_without_waiting_until_deadline(self):
        b,g,d,c,own,units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        units.remove(c);b.scout_critter=None
        for now in range(100,106):b.scout(now)
        self.assertEqual(orders[-1][2],b.enemy_main)
        b.scout(150);self.assertEqual(orders[-1][2],b.enemy_main)

    def test_low_health_scout_retreats_before_search_or_hunt(self):
        b,g,d,c,own,units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        own[1].hp=50;c.hp=15;c.alive=True;b.scout_critter=None
        b.scout(100)
        self.assertEqual(orders[-1][2],(b.home.x,b.home.y));self.assertIsNone(b.critter_search.hunt)

if __name__=='__main__':unittest.main()
