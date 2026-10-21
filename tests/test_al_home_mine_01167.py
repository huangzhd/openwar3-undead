import json
import unittest
from pathlib import Path
import test_al_route_01166 as al
from test_micro_loot import unit


class ALHomeMineTests(unittest.TestCase):
    def test_after_skeletons_selects_nearest_home_blue_ogre_despite_enemy_mine_on_other_side(self):
        frame=json.loads((Path(__file__).parent/'fixtures/al_183918_mine_block.json').read_text(encoding='utf-8'))['frame']
        for north in (False,True):
            b,g,a,c=al.ALRouteTests().scene(north)
            route=c.al_route(b.home);c.cleared.update(route[:4])
            blue=[p for p in c.catalog if p['kind']=='expansion' and any(s['code']=='nomg' for s in p['spawns'])]
            nearest=min(blue,key=lambda p:g.dist((p['x'],p['y']),b.home))
            old_mine=frame['enemies'][0]
            sign=-1 if north else 1
            # Mirrored north case and straight test path are constructed, not recorded.
            mine=unit('ugol',90,sign*old_mine['x'],old_mine['hp']);mine.y=sign*old_mine['y'];mine.owner=1
            c.enemy_structures=[mine]
            skeletons=next(p for p in c.catalog if p['id']==route[3]);center=(skeletons['x'],skeletons['y'])
            g.visible=lambda *args:False
            for i in range(4,7):
                point,_=c.choose(g,a,center,b.home,400+i)
                self.assertIsNotNone(point)
                if i==4:
                    self.assertEqual(c.active['id'],nearest['id'])
                    self.assertLess(g.dist(point,b.home),g.dist(point,c.enemy_main))
                self.assertTrue(c.safe_route(g,center,point))
                g.visible=lambda *args:True
                self.assertTrue(c.observe_clear(g,point,410+i,[]));center=point
                g.visible=lambda *args:False
            self.assertFalse(c.prepare_al_route(b.home,430,False))

    def test_enemy_mine_or_tower_at_actual_objective_still_blocks_approach(self):
        for code in ('ugol','uzg1'):
            b,g,a,c=al.ALRouteTests().scene();c.cleared.update(c.al_route(b.home)[:4])
            camp=next(p for p in c.catalog if p['id']==c.al_route_stage(b.home))
            building=unit(code,90,camp['x']);building.y=camp['y'];building.owner=1
            c.enemy_structures=[building]
            self.assertIsNone(c.choose(g,a,(b.home.x,b.home.y),b.home,400)[0])
            self.assertNotIn(camp['id'],c.cleared)
            self.assertEqual(c.deferred_reasons[camp['id']],'enemy_main_route')


if __name__=='__main__':unittest.main()
