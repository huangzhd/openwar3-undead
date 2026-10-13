import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import dist,unit
from undead.siege import building_priority,weapon_range,fire_clearance
from undead.controller import ground_attack_range
from undead.targeting import unit_collision


class AncientReachTests(unittest.TestCase):
    def test_actual_az_ancient_targeting_dk_gets_attack_priority(self):
        sample=json.loads((Path(__file__).parent/'fixtures/az-ancient-reach-01125.json').read_text(encoding='utf-8'))['sample']
        own=[N(**{**r,'handle':tuple(r['handle'])}) for r in sample['own']]
        dk=next(u for u in own if u.type=='Udea')
        tree=N(**next(r for r in sample['enemies'] if r['type']=='eaoe' and r.get('target')==list(dk.handle)))
        g=N(me=lambda:0,dist=dist,current_target=lambda u:dk,production=lambda u:None)
        self.assertGreater(dist(tree,dk),128)
        self.assertLess(dist(tree,dk),weapon_range(tree,dk))
        self.assertEqual(building_priority(g,tree),-3)
        self.assertLess(fire_clearance(g,dk,(dk.x,dk.y),[tree]),0)

    def test_public_collision_data_expands_ancient_safety_envelope(self):
        self.assertEqual(unit_collision('eaom'),144)
        self.assertEqual(unit_collision('Udea'),32)
        self.assertEqual(ground_attack_range('eaom'),304)
        self.assertEqual(ground_attack_range('ucry'),550)

    def test_stale_distant_or_enemy_target_does_not_gain_attack_priority(self):
        tree=unit('eaom',1,0);tree.owner=1;dk=unit('Udea',2,1000);dk.owner=0
        g=N(me=lambda:0,dist=dist,current_target=lambda u:dk,production=lambda u:None)
        self.assertEqual(building_priority(g,tree),5)
        dk.x=200;dk.owner=1;self.assertEqual(building_priority(g,tree),5)
        dk.owner=0;self.assertEqual(building_priority(g,tree),-3)


if __name__=='__main__':unittest.main()
