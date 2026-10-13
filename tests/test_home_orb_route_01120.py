import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_battle_shop_0163 as shopping
import test_tempo_01115 as tempo
from test_micro_loot import unit
from undead.home_layout import HomeLayout,ENVELOPES,clear_of_buildings


class HomeLayoutTests(unittest.TestCase):
    def test_buildings_keep_gaps_and_outward_corridor(self):
        home=N(type='unpl',x=-4672,y=-3840)
        buildings=[home];layout=HomeLayout()
        for code in ('uaod','uzig','usep','utom','ugrv','uzig','uslh','uzig','uzig'):
            point=next(layout.candidates(code,home,buildings))
            self.assertTrue(clear_of_buildings(point,buildings,128,ENVELOPES[code]))
            dx,dy=point[0]-home.x,point[1]-home.y
            length=(home.x**2+home.y**2)**.5
            along=(-home.x*dx-home.y*dy)/length
            across=abs(-home.y*dx+home.x*dy)/length
            self.assertTrue(along<=0 or across>=ENVELOPES[code]+128)
            buildings.append(N(type=code,x=point[0],y=point[1]))

    def test_layout_skips_rejected_candidate_and_keeps_sdk_pending_tracking(self):
        home=N(type='unpl',x=-4672,y=-3840);calls=[]
        def build(worker,code,x,y,**kwargs):
            calls.append((x,y,kwargs));return None if len(calls)==1 else (x,y)
        g=N(my_buildings=lambda:[home],build_near=build)
        point=HomeLayout().build(g,None,'utom',home)
        self.assertEqual(point,calls[-1][:2]);self.assertEqual(len(calls),2)
        self.assertEqual(calls[-1][2],dict(min_r=0,max_r=0,max_tries=1))


class OrbMeetingTests(unittest.TestCase):
    def test_actual_blocked_pair_moves_both_heroes_to_open_ground_and_confirms_bags(self):
        g,b,s,events=shopping.ShoppingTests().make()
        fixture=json.loads((Path(__file__).parent/'fixtures/tm-orb-blocked-01119.json').read_text())
        buildings=[]
        for row in fixture['own']:
            if row['type'] in ('Udea','Ulic'):
                h=g.dk if row['type']=='Udea' else g.lich
                h.x,h.y=row['x'],row['y'];g.bags[h.handle]=row['inventory']
            else:buildings.append(N(**row))
        g.my_buildings=lambda:buildings
        s.orb_tick(b,g.heroes,[],700,3)
        reserved=s.orb_tick(b,g.heroes,[],708,3)
        self.assertEqual(reserved,{g.dk.handle,g.lich.handle})
        self.assertTrue(clear_of_buildings(s.orb['meeting'],buildings))
        self.assertEqual({o[1] for o in g.orders[-2:]},{'Udea','Ulic'})
        self.assertIn('ocor',g.inventory(g.dk));self.assertNotIn('ocor',g.inventory(g.lich))
        for hero in (g.dk,g.lich):hero.x,hero.y=s.orb['meeting']
        s.orb_tick(b,g.heroes,[],710,3);s.observe(g,711)
        self.assertFalse(s.orb_tick(b,g.heroes,[],714,3))
        self.assertTrue(any(e['event']=='shop_transaction_confirmed' and e['kind']=='give' for e in events))
        self.assertIn('ocor',g.inventory(g.lich))

    def test_unreachable_meeting_is_not_issued_or_reported_delivered(self):
        g,b,s,events=shopping.ShoppingTests().make();g.bags[g.dk.handle][1]='ocor'
        g.dk.x=0;g.lich.x=700;g.path_distance=lambda *a:None
        self.assertFalse(s.orb_tick(b,g.heroes,[],700,3))
        self.assertFalse(g.orders);self.assertIn('ocor',g.inventory(g.dk))
        self.assertNotEqual(events[-1].get('reason'),'delivered')


class TMStagingTests(unittest.TestCase):
    def scene(self):
        c,g,home,dk,skels=tempo.TMCreepTests().scene()
        c.tier=3;c.resupply_home=True
        army=[dk,unit('Ulic',20,dk.x),unit('uobs',21,dk.x),
              *[unit('ucry',i,dk.x) for i in range(30,36)]]
        return c,g,home,army,dk

    def test_orb_window_prefers_near_shop_or_mercenary_and_excludes_expansions(self):
        c,g,home,army,dk=self.scene()
        options=c.candidates(g,army,home,530)
        self.assertTrue(any(x['kind']=='shop' for x in options))
        self.assertTrue(any(x['kind']=='mercenary' for x in options))
        self.assertFalse(any(x['kind']=='expansion' for x in options))
        goal,_=c.choose(g,army,(dk.x,dk.y),home,530)
        self.assertIsNotNone(goal);self.assertTrue(c.tm_staging_camp(c.active,home))

    def test_far_expansion_goal_is_replaced_on_entering_orb_window(self):
        c,g,home,army,dk=self.scene()
        c.active=next(x for x in c.catalog if x['id']=='tm-24')
        c.choose(g,army,(dk.x,dk.y),home,530)
        self.assertNotEqual(c.active['id'],'tm-24')
        self.assertIn('tm-24',c.deferred)

    def test_other_map_and_post_attack_are_not_restricted_to_tm_staging(self):
        c,g,home,army,dk=self.scene();far=next(x for x in c.catalog if x['id']=='tm-24')
        c.map_alias='TR';self.assertTrue(c.tm_staging_allows(far,home))
        c.map_alias='TM';c.home_only=False;self.assertTrue(c.tm_staging_allows(far,home))
