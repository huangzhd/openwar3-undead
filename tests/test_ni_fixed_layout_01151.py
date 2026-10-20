import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_ni_midgame_layout_01148 as previous
from test_micro_loot import unit


class FixedOpeningTests(unittest.TestCase):
    def scene(self):
        scene=previous.OpeningLayoutTests().scene()
        scene[0].map_alias='NI'
        fixture=json.loads((Path(__file__).parent/'fixtures/ni_184054_opening_layout.json').read_text(encoding='utf-8'))
        return scene,fixture['events']

    def test_real_successful_orders_land_without_replaying_failed_shop_points(self):
        (layout,g,home,worker,buildings,orders,events,order),recorded=self.scene()
        failed={tuple(r['point']) for r in recorded if r['event']=='home_foundation_unconfirmed'}
        for code,now in [('utom',57.5),('ugrv',80.15)]:
            foundation=next(r for r in recorded if r['event']=='home_foundation_observed' and r['code']==code)
            command=[r for r in recorded if r['event']=='home_build_order_pending' and r['code']==code][-1]
            count=len(orders)
            self.assertEqual(layout.build(g,worker,code,home,now),tuple(command['point']))
            self.assertEqual(len(orders),count+1)
            self.assertEqual(layout.build(g,worker,code,home,now+1),tuple(command['point']))
            self.assertEqual(len(orders),count+1) # pending travel does not duplicate
            actual=unit(code,100+count,foundation['point'][0]);actual.y=foundation['point'][1]
            buildings.append(actual);layout.observe(g,now+2)
            self.assertNotIn(code,layout.pending)
            self.assertEqual(events[-1]['event'],'home_foundation_observed')
            self.assertEqual(events[-1]['point'],tuple(foundation['point']))
        self.assertFalse(failed & {tuple(row[1:]) for row in orders})

    def test_occupied_fixed_slot_uses_safe_fallback(self):
        (layout,g,home,worker,buildings,orders,events,order),recorded=self.scene()
        occupied=unit('uslh',90,-2240);occupied.y=-3520;buildings.append(occupied)
        chosen=layout.build(g,worker,'utom',home,57)
        self.assertNotEqual(chosen,(-2272,-3520))
        self.assertTrue(previous.clear_of_buildings(chosen,buildings,128,128))

    def test_actual_failed_order_releases_builder_and_does_not_retry_same_slot(self):
        (layout,g,home,worker,buildings,orders,events,order),recorded=self.scene()
        first=layout.build(g,worker,'utom',home,57)
        self.assertTrue(layout.observe(g,60))
        self.assertNotEqual(layout.pending['utom']['point'],first)
        self.assertEqual(layout.pending['utom']['worker'],worker.handle)
        self.assertEqual(len(orders),2)

    def test_fixed_slot_still_checks_buildable_ground(self):
        (layout,g,home,worker,buildings,orders,events,order),recorded=self.scene()
        g.map=lambda:N(buildable=lambda x,y:(x,y)!=(-2272,-3520))
        chosen=layout.build(g,worker,'utom',home,57)
        self.assertNotEqual(chosen,(-2272,-3520))
        self.assertNotIn(('utom',-2272,-3520),orders)

    def test_other_map_or_unverified_spawn_does_not_use_ni_southwest_slot(self):
        for other in ('map','spawn'):
            (layout,g,home,worker,buildings,orders,events,order),recorded=self.scene()
            if other=='map':layout.map_alias='CH'
            else:home.x=6912;home.y=3264;buildings[:]=[home]
            chosen=layout.build(g,worker,'utom',home,57)
            self.assertNotEqual(chosen,(-2272,-3520))
            if other=='map':self.assertEqual(chosen[1],-2816)


if __name__=='__main__':unittest.main()
