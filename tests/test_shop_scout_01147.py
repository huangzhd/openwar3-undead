import unittest
from types import SimpleNamespace as N
from undead.economy import Economy
from undead.controller import Controller
from test_micro_loot import unit
import test_foundation_owner_01124 as foundation


class ShopScoutTests(unittest.TestCase):
    def scene(self):
        workers=[unit('uaco',i+1,0) for i in range(6)]
        buildings=[];events=[]
        g=N(my_buildings=lambda codes:buildings,is_constructing=lambda w:False,
            order_of=lambda w:0 if w is workers[-1] else 851216)
        e=Economy(lambda event,**kw:events.append(dict(event=event,**kw)))
        return g,e,workers,buildings,events

    def test_six_workers_and_accepted_shop_order_do_not_release_scout(self):
        g,e,workers,buildings,events=self.scene()
        e.home_layout.pending['utom']=dict(worker=workers[-1].handle)
        e.assign_scout(g,workers,59.73)
        self.assertIsNone(e.scout);self.assertFalse(events)

    def test_actual_shop_foundation_and_released_builder_allow_scout(self):
        g,e,workers,buildings,events=self.scene()
        shop=unit('utom',20,0,1);buildings.append(shop)
        e.assign_scout(g,workers,62)
        self.assertEqual(e.scout,workers[-1].handle)
        self.assertTrue(events[-1]['shop_foundation'])

    def test_foundation_does_not_steal_other_pending_builder_or_five_miners(self):
        g,e,workers,buildings,events=self.scene();buildings.append(unit('utom',20,0))
        e.home_layout.pending['ugrv']=dict(worker=workers[-1].handle)
        e.assign_scout(g,workers,80)
        self.assertIsNone(e.scout)
        extra=unit('uaco',30,10);workers.append(extra)
        e.assign_scout(g,workers,81)
        self.assertNotEqual(e.scout,workers[-2].handle)
        self.assertIsNotNone(e.scout)

    def test_constructing_worker_is_excluded_even_without_layout_pending(self):
        g,e,workers,buildings,events=self.scene();buildings.append(unit('utom',20,0))
        g.is_constructing=lambda w:w is workers[-1]
        e.assign_scout(g,workers,80);self.assertIsNone(e.scout)

    def test_shop_failed_order_relocates_without_24_second_wait_and_logs_builder(self):
        layout,g,home,worker,buildings,workers,orders,events,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True
        first=layout.build(g,worker,'utom',home,57.375)
        self.assertEqual(events[-2]['event'],'home_build_order_pending')
        self.assertEqual(events[-2]['worker'],worker.handle)
        layout.observe(g,59.73)
        self.assertNotEqual(layout.pending['utom']['point'],first)
        self.assertEqual(layout.reserved,{worker.handle})
        self.assertEqual(sum(o[0]=='utom' for o in orders),2)

    def test_scout_orders_cannot_override_active_building_reservation(self):
        worker=unit('uaco',1,0)
        g=N(unit=lambda h:worker)
        b=Controller(g,lambda *a,**kw:None);b.economy.scout=worker.handle
        b.economy.home_layout.pending['utom']=dict(worker=worker.handle)
        # The minimal game intentionally cannot issue movement or combat commands.
        b.scout(59.73)


if __name__=='__main__':unittest.main()
