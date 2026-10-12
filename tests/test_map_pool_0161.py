import json,re,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import bootstrap,session
from w3mpq import Mpq
from extract_map_pool import placements,clusters
from undead.maps import pool,resolve_map,catalog_for_path
from undead.start_search import StartSearch
from undead.creeping import Creeping
from undead.controller import Controller
from test_micro_loot import unit,dist

class CatalogTests(unittest.TestCase):
    def test_all_eight_catalogs_match_literal_neutral_creations(self):
        for alias,data in pool().items():
            path,_=resolve_map(alias);mpq=Mpq(path.read_bytes());script=mpq.read('war3map.j').decode('utf8')
            body=re.search(r'function CreateNeutralHostile takes nothing returns nothing(.*?)endfunction',script,re.S).group(1)
            expected=[(code,float(x.replace(' ','')),float(y.replace(' ',''))) for code,x,y in re.findall(
                r"(?:CreateUnit|BlzCreateUnitWithSkin)\(\s*p\s*,\s*'(\w{4})'\s*,\s*([- \d.]+)\s*,\s*([- \d.]+)\s*,",body)]
            actual=[(u['code'],u['x'],u['y']) for c in data['camps'] for u in c['spawns']]
            self.assertCountEqual(actual,expected,alias)
            self.assertEqual(catalog_for_path(path)['alias'],alias)
            for c in data['camps']:
                self.assertEqual(c['hp'],sum(u['hp'] for u in c['spawns']))
                self.assertEqual(c['difficulty'],sum(u['level']+2*bool(u['poison_abilities']) for u in c['spawns']))
    def test_nonliteral_coordinates_are_rejected_not_silently_skipped(self):
        s="function CreateNeutralPassive takes nothing returns nothing\ncall CreateUnit(p, 'nshe', GetRandomReal(0,1), 10, 0)\nendfunction"
        with self.assertRaisesRegex(ValueError,'Nonliteral'):placements(s,'CreateNeutralPassive')
    def test_changed_map_cannot_load_another_maps_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'LR.w3x';p.write_bytes(b'changed')
            self.assertIsNone(catalog_for_path(p))
    def test_connected_camp_grouping_is_order_independent(self):
        points=[dict(x=0,y=0),dict(x=1000,y=0),dict(x=500,y=0),dict(x=3000,y=0)]
        for rows in (points,list(reversed(points))):
            self.assertEqual(sorted(len(g) for g in clusters(rows)),[1,3])
    def test_lr_critter_coordinates_are_from_passive_units(self):
        path,d=resolve_map('LR');s=Mpq(path.read_bytes()).read('war3map.j').decode('utf8')
        expected=placements(s,'CreateNeutralPassive')
        self.assertCountEqual(d['critters'],expected)
        self.assertTrue(any(p['code']=='nshe' and p['x']==-1259 for p in d['critters']))
        self.assertFalse(pool()['TR']['critters'])

class ReconTests(unittest.TestCase):
    def make(self):
        self.foes=[];self.visible=False;self.events=[]
        g=N(map=lambda:N(starts=[(-3000,-3000),(3000,-3000),(-3000,3000),(3000,3000)]),
            dist=dist,path_distance=dist,visible=lambda *p:self.visible,enemies=lambda:self.foes,me=lambda:0)
        return g,StartSearch(lambda e,**kw:self.events.append((e,kw))),N(x=-3000,y=-3000)
    def test_nearest_candidate_is_scouted_not_declared_enemy(self):
        g,s,home=self.make();self.assertIsNone(s.update(g,home,1))
        first=s.choose(g,home,1);self.assertIsNotNone(first);self.assertIsNone(s.confirmed)
        self.visible=True;scout=N(x=first[0],y=first[1]);second=s.choose(g,scout,10)
        self.assertNotEqual(first,second);self.assertIsNone(s.update(g,home,10))
    def test_hidden_building_cannot_confirm_but_visible_one_can(self):
        g,s,home=self.make();u=unit('htow',99,3000);u.y=3000;u.owner=1;u.alive=True;u.visible_to=lambda me:False
        self.foes.append(u);self.assertIsNone(s.update(g,home,1))
        u.visible_to=lambda me:True;self.assertEqual(s.update(g,home,2),(3000,3000))
        self.foes.clear();self.assertEqual(s.update(g,home,3),(3000,3000))
    def test_blocked_candidate_is_deferred_and_other_start_remains_reachable(self):
        g,s,home=self.make();s.update(g,home,1);first=s.choose(g,home,1)
        g.path_distance=lambda a,b:None if b==first else dist(a,b)
        self.assertNotEqual(s.choose(g,home,2),first)
    def test_north_south_map_uses_starts_not_echo_x_axis(self):
        g=N(map=lambda:N(starts=[(0,-4000),(0,4000)]),dist=dist);home=N(x=0,y=4000)
        self.assertTrue(Creeping.own_side(g,dict(x=-100,y=3000),home))
        self.assertFalse(Creeping.own_side(g,dict(x=-100,y=-3000),home))
    def test_random_race_not_revealed_until_visible_enemy(self):
        g=N(me=lambda:0);events=[]
        b=Controller.__new__(Controller);b.g=g;b.enemy_race=0;b.third_hero='Nbrn';b.tavern_mission=None
        b.economy=N(ever_heroes=set(),third_hero='Nbrn');b.log=lambda e,**kw:events.append(e)
        u=unit('ewsp',90,100);u.owner=1;u.alive=True;u.visible_to=lambda me:False
        b.observe_race([u],1);self.assertEqual(b.third_hero,'Nbrn');self.assertEqual(b.enemy_race,0)
        u.visible_to=lambda me:True;b.observe_race([u],2)
        self.assertEqual(b.third_hero,'Nngs');self.assertEqual(b.economy.third_hero,'Nngs')
        self.assertEqual(events,['enemy_race_observed'])

class LaunchTests(unittest.TestCase):
    def test_random_draw_verified_against_engine_and_wrong_race_rejected(self):
        for draw in range(4):
            with patch('session.secrets.randbelow',return_value=draw):
                s=session.Session(400,0,4)
            race=[draw+1];closed=[]
            audit=N(jass=N(Player=lambda i:i,GetPlayerController=lambda _:1,
                           GetPlayerRace=lambda _:race[0],GetAIDifficulty=lambda _:2),close=lambda:closed.append(True))
            with patch('session.Game',return_value=audit):
                self.assertEqual(s.verify_opponent(N(pid=1,me=lambda:0))['race'],draw+1)
                race[0]=1 if draw!=0 else 2
                with self.assertRaisesRegex(RuntimeError,'Actual opponent'):s.verify_opponent(N(pid=1,me=lambda:0))
            self.assertEqual(closed,[True,True]);self.assertEqual(s.requested_race,0)
    def test_wrong_live_map_geometry_rejected(self):
        path,data=resolve_map('LR');s=session.Session();s.map_path=path;s.map_catalog=data
        with self.assertRaisesRegex(RuntimeError,'Live start'):
            s.verify_map(N(map=lambda:N(starts=[(-1,-1),(1,1)])))
        s.verify_map(N(map=lambda:N(starts=[(p['x'],p['y']) for p in data['starts']])))
        self.assertEqual(len(s.settings['verified_map_starts']),2)
    def test_extra_players_on_four_start_map_rejected_before_policy(self):
        s=session.Session(400,1,4);s.map_catalog=pool()['TR']
        audit=N(jass=N(Player=lambda i:i,GetPlayerSlotState=lambda i:1 if i<4 else 0),close=lambda:None)
        with patch('session.Game',return_value=audit):
            with self.assertRaisesRegex(RuntimeError,'exactly two'):s.verify_opponent(N(pid=1,me=lambda:0))

class SpawnCoverageTests(unittest.TestCase):
    def test_lr_both_starts_select_their_own_critter_region(self):
        from undead.scouting import CritterSearch
        d=pool()['LR']
        for start,expected in zip(d['starts'],[(-1259.0,-4038.1),(1017.1,3502.2)]):
            home=N(x=start['x'],y=start['y'])
            g=N(dist=dist,path_distance=dist,visible=lambda *p:False,map=lambda:None)
            search=CritterSearch(lambda *a,**k:None,d['critters'])
            self.assertEqual(search.choose(g,home,home,60),expected)
            self.assertEqual(search.spawn_center,expected)
    def test_each_maps_each_start_owns_its_nearby_camps(self):
        for d in pool().values():
            starts=[(p['x'],p['y']) for p in d['starts']]
            g=N(map=lambda:N(starts=starts),dist=dist)
            for x,y in starts:
                home=N(x=x,y=y)
                local=[c for c in d['camps'] if Creeping.own_side(g,c,home)]
                self.assertTrue(local,(d['alias'],x,y))
                for c in local:
                    point=(c['x'],c['y'])
                    self.assertLessEqual(dist(home,point),min(dist(point,other) for other in starts if other!=(x,y)))
    def test_four_start_recon_resets_for_every_actual_home(self):
        d=pool()['TM'];starts=[(p['x'],p['y']) for p in d['starts']]
        g=N(map=lambda:N(starts=starts),dist=dist,path_distance=dist,enemies=lambda:[],me=lambda:0,visible=lambda *p:False)
        for x,y in starts:
            home=N(x=x,y=y);search=StartSearch(lambda *a,**k:None)
            self.assertIsNone(search.update(g,home,1));point=search.choose(g,home,2)
            self.assertNotEqual(point,(x,y));self.assertIn(point,starts);self.assertIsNone(search.confirmed)
