import unittest
from types import SimpleNamespace as N
from test_micro_loot import dist
from undead.attack_search import AttackSearch

class SearchTests(unittest.TestCase):
    def game(self):
        return N(dist=dist,path_distance=dist,visible=lambda *p:True,map=lambda:None)

    def test_expansions_then_map_areas_and_observed_arrival(self):
        g=self.game();events=[]
        g.map=lambda:N(cols=80,rows=20,cell=100,min_x=0,min_y=-1000,walkable=lambda *p:True)
        search=AttackSearch(lambda event,**kw:events.append(event))
        first=search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0)],1)
        self.assertEqual(first,(7000,0))
        second=search.choose(g,first,(0,0),(5000,0),[(7000,0)],3)
        self.assertNotEqual(second,first)
        self.assertEqual(search.goal['kind'],'area')
        self.assertIn('attack_search_checked',events)

    def test_invisible_location_is_not_marked_checked(self):
        g=self.game();g.visible=lambda *p:False;events=[]
        search=AttackSearch(lambda event,**kw:events.append(event))
        search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0)],1)
        search.choose(g,(7000,0),(0,0),(5000,0),[(7000,0)],3)
        self.assertNotIn('attack_search_checked',events)

    def test_stalled_location_advances_and_search_rounds_are_bounded(self):
        g=self.game();g.visible=lambda *p:False;events=[]
        search=AttackSearch(lambda event,**kw:events.append(event))
        for now in range(0,110,2):
            search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0)],now)
        self.assertIn('attack_search_deferred',events)
        self.assertIn('attack_search_exhausted',events)
        self.assertIsNone(search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0)],120))
        self.assertEqual(search.rounds,2)

    def test_ground_route_beats_short_straight_line_across_obstacle(self):
        g=self.game();g.visible=lambda *p:False
        g.path_distance=lambda a,b:6000 if b==(7000,0) else dist(a,b)
        search=AttackSearch(lambda *a,**kw:None)
        self.assertEqual(search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0),(8000,0)],0),(8000,0))

    def test_visible_nearby_points_are_skipped_without_visiting_each_one(self):
        g=self.game();events=[]
        search=AttackSearch(lambda event,**kw:events.append((event,kw)))
        search.rounds=1
        search.pending=[dict(point=(x,0),kind='area') for x in (5500,6000,7500)]
        g.visible=lambda x,y:x==5500
        point=search.choose(g,(5000,0),(0,0),(5000,0),[],0)
        self.assertEqual(point,(6000,0))
        checked=[kw for event,kw in events if event=='attack_search_checked']
        self.assertEqual([kw['point'] for kw in checked],[(5500,0)])
        self.assertEqual(checked[0]['evidence'],'visible_point')
        self.assertTrue(checked[0]['opportunistic'])

    def test_unknown_visibility_is_not_coverage_and_goal_is_kept(self):
        g=self.game();g.visible=lambda *p:None;events=[]
        search=AttackSearch(lambda event,**kw:events.append(event))
        search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0)],0)
        self.assertEqual(search.choose(g,(6000,0),(0,0),(5000,0),[],2),(7000,0))
        self.assertNotIn('attack_search_checked',events)

    def test_visible_goal_can_finish_before_center_reaches_old_arrival_radius(self):
        g=self.game();search=AttackSearch(lambda *a,**kw:None)
        first=search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0),(9000,0)],0)
        self.assertEqual(first,(7000,0))
        self.assertEqual(search.choose(g,(6000,0),(0,0),(5000,0),[],2),(9000,0))

    def test_unreachable_candidate_does_not_block_reachable_expansion(self):
        g=self.game();g.path_distance=lambda a,b:None if b==(7000,0) else dist(a,b)
        search=AttackSearch(lambda *a,**kw:None)
        self.assertEqual(search.choose(g,(5000,0),(0,0),(5000,0),[(7000,0),(8000,0)],0),(8000,0))

if __name__=='__main__':unittest.main()
