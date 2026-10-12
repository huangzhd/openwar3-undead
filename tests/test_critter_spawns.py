import unittest,tempfile,json,re
from pathlib import Path
from types import SimpleNamespace as N
import bootstrap
from w3mpq import Mpq
from test_micro_loot import unit,dist
import test_scout_opening as opening
from undead.scouting import CritterSearch,public_critter_spawns

class CritterSpawnTests(unittest.TestCase):
    def make(self,home=(-5184,2944)):
        u=unit('uaco',1,home[0],220);u.y=home[1]
        h=N(x=home[0],y=home[1]);events=[]
        g=N(dist=dist,path_distance=dist,visible=lambda *p:False)
        s=CritterSearch(lambda e,**kw:events.append(dict(event=e,**kw)))
        return s,g,u,h,events

    def test_two_nearest_regions_exhaust_without_visiting_third(self):
        s,g,u,h,e=self.make((0,0))
        s.spawns=[dict(code='nshe',x=x,y=0) for x in (1000,2000,4000)]
        first=s.choose(g,u,h,60);self.assertLessEqual(dist(first,(1000,0)),451)
        g.visible=lambda x,y:dist((x,y),(1000,0))<=451
        second=s.choose(g,u,h,61);self.assertLessEqual(dist(second,(2000,0)),451)
        g.visible=lambda *p:True
        self.assertIsNone(s.choose(g,u,h,62));self.assertTrue(s.reported)
        self.assertTrue(all(dist(p,(4000,0))>451 for p in s.points))

    def test_catalog_matches_actual_static_map_creation_function(self):
        cfg=json.loads((bootstrap.UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
        script=Mpq((Path(cfg['game_dir'])/'Maps'/cfg['default_map']).read_bytes()).read('war3map.j').decode('utf-8')
        body=re.search(r'function CreateNeutralPassive takes nothing returns nothing(.*?)endfunction',script,re.S).group(1)
        expected={(c,float(x),float(y)) for c,x,y in re.findall(r"CreateUnit\(\s*p,\s*'(\w{4})',\s*([-\d.]+),\s*([-\d.]+)",body)}
        actual={(s['code'],s['x'],s['y']) for s in public_critter_spawns()}
        self.assertEqual(actual,expected);self.assertNotIn('GetRandom',body)

    def test_changed_or_missing_map_falls_back_without_echo_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'different.w3x';path.write_bytes(b'different map')
            self.assertEqual(public_critter_spawns(path),[])
            self.assertEqual(public_critter_spawns(Path(directory)/'missing.w3x'),[])
            s,g,u,h,_=self.make();s.spawns=public_critter_spawns(path)
            point=s.choose(g,u,h,66)
            self.assertIsNone(s.spawn_center);self.assertAlmostEqual(dist(h,point),900,delta=1)

    def test_both_start_sides_go_to_their_own_nearest_sheep_first(self):
        for start,expected in (((-5184,2944),(-3372.9,2002.9)),((4672,2944),(3594.6,1095.9))):
            s,g,u,h,e=self.make(start)
            self.assertEqual(s.choose(g,u,h,66),expected)
            self.assertGreater(dist(h,expected),2000)
            self.assertEqual(e[-1]['search_kind'],'spawn_region')

    def test_seen_center_does_not_skip_unseen_wander_neighborhood(self):
        s,g,u,h,e=self.make();center=(-3372.9,2002.9)
        g.visible=lambda x,y:(x,y)==center
        point=s.choose(g,u,h,66)
        self.assertIn(center,s.checked)
        self.assertLessEqual(dist(point,center),451);self.assertNotEqual(point,center)
        self.assertEqual(e[-1]['search_kind'],'spawn_region')

    def test_seen_neighborhood_moves_to_second_nearby_region(self):
        s,g,u,h,e=self.make();center=(-3372.9,2002.9)
        g.visible=lambda x,y:dist((x,y),center)<=451
        point=s.choose(g,u,h,66)
        self.assertEqual(e[-1]['search_kind'],'spawn_region')
        self.assertGreater(dist(point,center),451)

    def test_blocked_exact_spawn_uses_nearby_walkable_point(self):
        s,g,u,h,e=self.make();center=(-3372.9,2002.9)
        g.map=lambda:N(walkable=lambda x,y:(x,y)!=center)
        point=s.choose(g,u,h,66)
        self.assertNotEqual(point,center);self.assertLessEqual(dist(point,center),451)

    def test_spawn_memory_never_fabricates_live_target_or_corpse(self):
        b,g,d,c,own,units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        units.remove(c);b.scout_critter=None;g.visible=lambda *p:False
        b.home=N(x=-5184,y=2944);own[1].x=-5184;own[1].y=2944
        b.scout(66)
        self.assertEqual(orders[-1][0],'move');self.assertEqual(orders[-1][2],(-3372.9,2002.9))
        self.assertIsNone(b.scout_critter);self.assertIsNone(b.scout_corpse)
        # Once actually seen away from its placement, attack the observed unit.
        c.hp=15;c.alive=True;c.x=-3500;c.y=2200;units.append(c)
        b.scout(67)
        self.assertEqual(orders[-1],('attack',[own[1].handle],[c.handle]))
        self.assertEqual(b.scout_critter_point,(-3500,2200))

    def test_unsafe_spawn_area_falls_back_to_second_region(self):
        s,g,u,h,e=self.make();center=(-3372.9,2002.9)
        point=None
        for now in range(66,70):
            point=s.choose(g,u,h,now,safe_route=lambda a,b:dist(b,center)>600)
            if point:break
        self.assertIsNotNone(point);self.assertGreater(dist(point,center),600)
        self.assertEqual(e[-1]['search_kind'],'spawn_region')

if __name__=='__main__':unittest.main()
