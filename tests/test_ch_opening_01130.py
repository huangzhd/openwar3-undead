import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N

from test_micro_loot import unit,dist
import test_creep_tempo_01101 as tempo
import test_scout_opening as scout_fixture
import test_dark_ranger_tanking as tanking
import test_opening_safety_0131 as opening
import test_scout_regroup_01105 as scouting
from test_baseline import unit as base_unit
from undead.creeping import Creeping


class CHOpeningTests(unittest.TestCase):
    def scene(self,x=2176,y=4224):
        b,g,army,orders=tempo.TempoTests().opening(x,y)
        catalog=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['CH']
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in catalog['starts']])
        b.creeping=Creeping(b.log,catalog['camps']);b.creeping.map_alias='CH'
        b.creeping.enemy_main=(-2304,-4736) if y>0 else (2176,4224)
        return b,g,army,orders

    def test_both_spawns_first_summons_depart_without_fiends_then_chain_ogre(self):
        for x,y,turtle,ogre in [(2176,4224,'ch-9','ch-13'),(-2304,-4736,'ch-8','ch-3')]:
            with self.subTest(spawn=(x,y)):
                b,g,army,orders=self.scene(x,y)
                b.creep(army,(x,y),168)
                self.assertEqual(b.creeping.active['id'],turtle)
                point=(b.creeping.active['x'],b.creeping.active['y'])
                self.assertIn(('move',[u.handle for u in army],point),orders)
                fiend=unit('ucry',91,point[0],550);fiend.y=point[1];fiend.hp_max=550
                # One remaining skeleton and the arriving first fiend continue.
                army=[army[0],army[1],fiend]
                b.creeping.choose(g,army,point,b.home,220)
                self.assertIn(turtle,b.creeping.cleared)
                self.assertEqual(b.creeping.active['id'],ogre)

    def test_turtle_commitment_survives_summon_loss_but_not_critical_health(self):
        b,g,army,_=self.scene();b.creep(army,(2176,4224),168)
        point=(b.creeping.active['x'],b.creeping.active['y'])
        foe=unit('ntrt',98,point[0],200);foe.y=point[1];g.creeps=lambda:[foe]
        self.assertEqual(b.creeping.choose(g,army[:1],point,b.home,180)[0],point)
        army[0].hp=100
        self.assertIsNone(b.creeping.choose(g,army[:1],point,b.home,181)[0])
        self.assertNotIn('ch-9',b.creeping.cleared)

    def test_no_turtle_override_on_other_maps_or_without_initial_summons(self):
        b,g,army,_=self.scene();c=b.creeping
        for alias,units in [('TM',army),('TR',army),('CH',army[:1])]:
            c.map_alias=alias
            self.assertNotIn('ch-9',{p['id'] for p in c.candidates(g,units,b.home,168)})

    def test_poison_or_larger_turtles_do_not_get_ch_opening_exception(self):
        for change in ({'poison_units':1},{'difficulty':12},{'hp':1400}):
            b,g,army,_=self.scene();c=b.creeping
            c.catalog=[dict(p,**change) if p['kind']=='turtle' else p for p in c.catalog]
            self.assertNotIn('ch-9',{p['id'] for p in c.candidates(g,army,b.home,168)})


class OpeningCoordinationTests(unittest.TestCase):
    def test_scout_finishes_detour_waypoint_instead_of_reversing_next_tick(self):
        g,scout,foe,search=scouting.ScoutSafetyTests().game()
        goal=(2500,0)
        step=search.safe_step(g,scout,goal,1)
        waypoint=search.detour['point']
        scout.x,scout.y=step
        second=search.safe_step(g,scout,goal,2)
        self.assertEqual(search.detour['point'],waypoint)
        self.assertLess(dist(second,waypoint),dist(step,waypoint))
        for i in range(101):
            p=(step[0]+(second[0]-step[0])*i/100,step[1]+(second[1]-step[1])*i/100)
            self.assertGreaterEqual(dist(p,foe),799)

    def test_new_visible_threat_invalidates_committed_detour(self):
        g,scout,foe,search=scouting.ScoutSafetyTests().game()
        step=search.safe_step(g,scout,(2500,0),1)
        waypoint=search.detour['point'];scout.x,scout.y=step
        new_foe=unit('ntrt',100,waypoint[0]);new_foe.y=waypoint[1]
        new_foe.visible_to=lambda me:True;g.creeps=lambda:[foe,new_foe]
        second=search.safe_step(g,scout,(2500,0),2)
        self.assertGreaterEqual(dist(second,new_foe),dist(step,new_foe))
        self.assertNotEqual(second,waypoint)

    def test_wounded_lone_skeleton_does_not_park_main_army(self):
        b,dk,sk,e,attacks,holds,*_=tanking.SkeletonOpeningTests().setup_fight()
        sk.hp=86;sk.hp_max=180
        self.assertFalse(b.skeleton_opening([dk,sk],[e],359.18))
        self.assertFalse(attacks);self.assertFalse(holds)

    def test_distant_fiend_follows_healthy_tank_without_dk_overtaking(self):
        b,dk,sk,e,attacks,holds,*_=tanking.SkeletonOpeningTests().setup_fight()
        fiend=unit('ucry',10,-1200,550);moves=[]
        b.go_raw=lambda us,p,t:moves.append(([u.handle for u in us],p))
        self.assertTrue(b.skeleton_opening([dk,sk,fiend],[e],1))
        self.assertEqual(moves,[([fiend.handle],(-120.0,0.0))])
        self.assertEqual(attacks,[(sk.handle,e.handle)])

    def test_supply_follows_tech_before_first_fiend_and_is_not_duplicated(self):
        g,e=opening.OpeningTests().game()
        g.own.extend([base_unit('ugho',101,owner=0),base_unit('ugho',102,owner=0),g.opening_dk])
        g.inventory=lambda u:['rnec'];g.busy.clear()
        e.tick(g,155)
        self.assertEqual(g.commands,['unp1'])
        home=g.my_buildings({'unpl'})[0]
        g.busy[home.handle]=N(kind='upgrade',queue=['unp1'])
        e.tick(g,158)
        self.assertEqual(g.commands,['unp1','uzig'])
        zig=base_unit('uzig',103,owner=0);g.own.append(zig)
        zig.hp=10;g.busy[zig.handle]=N(kind='construction',queue=[])
        e.tick(g,170)
        self.assertEqual(g.commands,['unp1','uzig','ucry'])

    def test_visible_spawn_latches_scout_discovery_and_never_detours_home(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=scout_fixture.ScoutCorpseTests().make()
        scout=own[1];scout.x=4500;scout.hp=30
        b.start_search.safe_step=lambda *a:(_ for _ in ()).throw(AssertionError('unneeded survival detour'))
        b.scout(180)
        self.assertEqual(orders[-1][2],b.enemy_main)
        self.assertTrue(b.economy.enemy_start_known)
        g.visible=lambda *a:False;scout.x=3500
        b.scout(190)
        self.assertEqual(orders[-1][2],b.enemy_main)
        self.assertEqual(sum(x['event']=='scout_discovery_complete' for x in events),1)

    def test_unseen_public_start_alone_does_not_release_scout_survival(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=scout_fixture.ScoutCorpseTests().make()
        own[1].hp=30;g.visible=lambda *a:False
        b.scout(180)
        self.assertEqual(orders[-1][2],(b.home.x,b.home.y))
        self.assertIsNone(getattr(b,'scout_discovered_start',None))


if __name__=='__main__':unittest.main()
