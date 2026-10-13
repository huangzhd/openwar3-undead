import unittest
from types import SimpleNamespace as N
import test_creep_tempo_01101 as tempo
import test_map_pool_0161 as recon
import test_scout_opening as opening
from test_micro_loot import unit,dist
from undead.start_search import StartSearch

class ScoutSafetyTests(unittest.TestCase):
    def game(self,creep_x=1000):
        foe=unit('ntrt',99,creep_x);foe.visible_to=lambda me:True
        scout=N(x=0,y=0)
        g=N(creeps=lambda:[foe],dist=dist,walk_path=lambda a,b:[b],me=lambda:0)
        return g,scout,foe,StartSearch(lambda *a,**kw:None)

    def test_visible_guard_switches_start_before_arrival_without_claiming_enemy(self):
        fixture=recon.ReconTests();g,s,home=fixture.make();s.update(g,home,1)
        first=s.choose(g,home,1);scout=N(x=first[0],y=first[1]-1100)
        foe=unit('ntrt',99,first[0]);foe.y=first[1];foe.visible_to=lambda me:True
        g.creeps=lambda:[foe]
        self.assertNotEqual(s.choose(g,scout,2),first)
        self.assertGreater(dist(scout,first),550);self.assertIn(first,s.checked)
        self.assertIsNone(s.confirmed)

    def test_hidden_guard_does_not_complete_start(self):
        fixture=recon.ReconTests();g,s,home=fixture.make();s.update(g,home,1)
        first=s.choose(g,home,1);scout=N(x=first[0],y=first[1]-1100)
        foe=unit('ntrt',99,first[0]);foe.y=first[1];foe.visible_to=lambda me:False;g.creeps=lambda:[foe]
        self.assertEqual(s.choose(g,scout,2),first);self.assertNotIn(first,s.checked)

    def test_detour_keeps_entire_step_outside_neutral_margin(self):
        g,scout,foe,s=self.game();goal=(2500,0);p=s.safe_step(g,scout,goal,1)
        self.assertNotEqual(p,goal);self.assertNotEqual(p,(0,0))
        for i in range(101):self.assertGreaterEqual(dist((p[0]*i/100,p[1]*i/100),foe),799)

    def test_inside_margin_steps_outward_and_blocked_path_never_moves_into_creep(self):
        g,scout,foe,s=self.game(400);p=s.safe_step(g,scout,(2500,0),1)
        self.assertGreater(dist(p,foe),dist(scout,foe))
        g.walk_path=lambda a,b:[(foe.x,foe.y),b]
        self.assertEqual(s.safe_step(g,scout,(2500,0),2),(0,0))

    def test_controller_uses_detour_for_start_orders(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        b.enemy_main=None;b.start_search.points=[(2000,0),(5000,0)]
        scout=own[1];scout.x=0
        foe=unit('ntrt',99,1000);foe.visible_to=lambda me:True;g.creeps=lambda:[foe]
        b.scout(200)
        point=orders[-1][2];self.assertNotEqual(point,(2000,0))
        for i in range(101):self.assertGreaterEqual(dist((point[0]*i/100,point[1]*i/100),foe),799)

class HomeHalfTests(unittest.TestCase):
    def army(self):
        b,g,army,orders=tempo.TempoTests().opening()
        b.creeping.enemy_main=(5376,-2112);b.creeping.tier=3;b.creeping.home_only=True
        army=[unit('Ulic',30,284,600),unit('uobs',31,284,600)]+[unit('ucry',i,284,550) for i in range(40,45)]
        for u in army:u.y=2072.6
        return b,g,army,orders

    def test_real_tr_first_744_continues_left_not_enemy_shop(self):
        b,g,army,_=self.army();c=b.creeping
        c.cleared={'tr-9','tr-4','tr-13','tr-11'}
        goal,_=c.choose(g,army,(284.13,2072.6),b.home,454.505)
        self.assertEqual(c.active['id'],'tr-7');self.assertLess(goal[0],284.13)
        self.assertNotIn('tr-16',{p['id'] for p in c.candidates(g,army,b.home,455)})
        self.assertNotIn('tr-16',c.cleared)

    def test_orb_home_camp_over_2200_remains_active_and_army_moves(self):
        b,g,army,orders=self.army();c=b.creeping
        c.cleared={'tr-9','tr-4','tr-13','tr-11'}
        c.active=next(p for p in c.catalog if p['id']=='tr-7');c.progress_at=500
        b.battle_shop.orb={'hero':(1,0)}
        b.creep(army,(3135.92,2743.86),512.905)
        self.assertEqual(c.active['id'],'tr-7')
        self.assertIn(('move',[u.handle for u in army],(-2329.43,-722.47)),orders)
        b.creep(army,(2800,2600),514.38);self.assertEqual(c.active['id'],'tr-7')

    def test_exhausted_home_camps_move_to_dk_and_do_not_mark_enemy_camps_cleared(self):
        b,g,army,orders=self.army();c=b.creeping
        c.cleared={p['id'] for p in c.catalog if c.home_half(g,p,b.home)}
        dk=g.unit((1,0));dk.x=-1000;dk.y=3500
        b.battle_shop.orb={'hero':dk.handle}
        b.creep(army,(3100,2700),520)
        self.assertEqual(orders[-1][2],(-1000,3500));self.assertIsNone(c.active)
        self.assertNotIn('tr-16',c.cleared)

    def test_missing_or_unsafe_courier_falls_back_home(self):
        b,g,army,orders=self.army();c=b.creeping;c.cleared={p['id'] for p in c.catalog}
        b.battle_shop.orb={'hero':(999,999)}
        b.creep(army,(3100,2700),520)
        self.assertEqual(orders[-1][2],(b.home.x,b.home.y))

if __name__=='__main__':unittest.main()
