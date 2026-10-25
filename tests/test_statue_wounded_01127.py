import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_support_fan_01122 as prior
from test_micro_loot import unit,dist


class WoundedStatueAnchorTests(unittest.TestCase):
    def test_recorded_ch_wounded_majority_receives_safe_reinforcement(self):
        b,g,events=prior.StatueTests().scene()
        row=json.loads((Path(__file__).parent/'fixtures/ch-wounded-statue-anchor-01127.json').read_text(encoding='utf-8'))['sample']
        g.army=[N(**{**u,'handle':tuple(u['handle'])}) for u in row['army']]
        hostiles=[N(**{**u,'handle':tuple(u['handle'])}) for u in row['enemies']]
        b.micro.pulling={u.handle for u in g.army if u.pulling}
        b.statue_support.tick(b,g.army,hostiles,row['clock'])
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual(len(moves),2)
        wounded=[u for u in g.army if u.pulling]
        for _,h,point in moves:
            self.assertEqual(g.unit(h).type,'uobs')
            self.assertGreaterEqual(sum(dist(u,point)<=700 for u in wounded),4)
            self.assertIsNotNone(b.army_recovery.safe_path(b,(g.unit(h).x,g.unit(h).y),point,hostiles))

    def test_all_combat_units_pulling_still_receive_supply(self):
        b,g,events=prior.StatueTests().scene()
        b.micro.pulling={u.handle for u in g.fiends+g.heroes}
        for u in g.statues:u.x=-1100
        b.statue_support.tick(b,g.army,[],10)
        self.assertEqual(len([o for o in g.orders if o[0]=='move']),2)

    def test_lone_wounded_straggler_does_not_drag_stationed_pair(self):
        b,g,events=prior.StatueTests().scene()
        for u in g.fiends+g.heroes:u.hp=u.hp_max;u.mana=u.mana_max
        far=unit('ucry',101,3000,100);g.army.append(far);b.micro.pulling.add(far.handle)
        b.statue_support.tick(b,g.army,[],10)
        self.assertEqual(g.orders,[('hold',u.handle) for u in g.statues])


if __name__=='__main__':unittest.main()
