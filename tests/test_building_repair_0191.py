import unittest
from types import SimpleNamespace as N
import bootstrap
from openwar3.orders import ORDER
from undead.economy import Economy
from test_baseline import FakeGame,unit
from test_micro_loot import dist


class RepairTests(unittest.TestCase):
    def make(self):
        g=FakeGame(tier=3,gold=246);e=Economy(lambda *a,**kw:None)
        home=g.my_buildings({'unp2'})[0];mine=g.my_buildings({'ugol'})[0]
        mine.hp_max=950;mine.hp=350;mine.x=200
        workers=g.units('me',{'uaco'});e.scout=workers[-1].handle
        for u in g.own:u.has_task=True
        e.complete={home.handle,mine.handle};orders=[];current={}
        g.dist=dist;g.path_distance=dist;g.enemies=lambda:[];g.is_constructing=lambda u:False
        g.order_of=lambda u:current.get(u.handle,0)
        g.cast=lambda w,spell,target:orders.append((w.handle,spell,target.handle)) or True
        g.stop=lambda w:current.pop(w.handle,None)
        return g,e,home,mine,workers,orders,current

    def test_critical_mine_assigns_only_two_restoration_workers_and_preserves_budget(self):
        g,e,home,mine,workers,orders,current=self.make()
        self.assertTrue(e.repairs.tick(g,e,home,100))
        self.assertEqual(len(orders),2)
        self.assertEqual({o[1] for o in orders},{'restoration'})
        self.assertEqual({o[2] for o in orders},{mine.handle})
        self.assertNotIn(e.scout,e.repairs.reserved)

    def test_construction_and_unseen_completion_are_not_repaired(self):
        for mode in ('construction','unseen','full'):
            g,e,home,mine,workers,orders,current=self.make()
            if mode=='construction':g.busy[mine.handle]=N(kind='construction')
            elif mode=='unseen':e.complete.remove(mine.handle)
            else:mine.hp=mine.hp_max
            self.assertFalse(e.repairs.tick(g,e,home,100));self.assertFalse(orders)

    def test_real_order_and_hp_growth_keep_job_then_full_health_releases(self):
        g,e,home,mine,workers,orders,current=self.make();events=[]
        e.repairs.log=lambda event,**kw:events.append(event)
        e.repairs.tick(g,e,home,100)
        for h in e.repairs.reserved:current[h]=ORDER('restoration')
        mine.hp+=30;e.repairs.tick(g,e,home,110)
        self.assertIn('building_repair_progress',events);self.assertEqual(len(orders),2)
        mine.hp=mine.hp_max;e.repairs.tick(g,e,home,111)
        self.assertFalse(e.repairs.reserved)

    def test_accepted_but_unchanged_order_retries_are_bounded(self):
        g,e,home,mine,workers,orders,current=self.make()
        for now in range(100,125):e.repairs.tick(g,e,home,now)
        self.assertEqual(len(orders),6);self.assertFalse(e.repairs.reserved)

    def test_no_progress_despite_repair_order_is_bounded(self):
        g,e,home,mine,workers,orders,current=self.make()
        e.repairs.tick(g,e,home,100)
        for h in e.repairs.reserved:current[h]=ORDER('restoration')
        e.repairs.tick(g,e,home,116)
        self.assertFalse(e.repairs.reserved)

    def test_workers_in_enemy_range_or_without_money_are_not_sent(self):
        for mode in ('danger','money','route','reserved'):
            g,e,home,mine,workers,orders,current=self.make()
            if mode=='danger':g.enemies=lambda:[unit('ogru',99,x=30)]
            elif mode=='money':g.gold=0
            elif mode=='route':g.path_distance=lambda *a:None
            else:e.expansion.miners={u.handle for u in workers}
            self.assertFalse(e.repairs.tick(g,e,home,100));self.assertFalse(orders)

    def test_full_economy_does_not_interrupt_repair_with_gather_or_buy(self):
        g,e,home,mine,workers,orders,current=self.make();g.gathers=[]
        g.gold_mines=lambda:[mine];g.idle_workers=lambda:workers
        g.gather=lambda w,m:g.gathers.append(w.handle)
        e.tick(g,100)
        self.assertEqual(len(e.repairs.reserved),2)
        self.assertFalse(set(g.gathers)&e.repairs.reserved)
        self.assertFalse(g.commands)


if __name__=='__main__':unittest.main()
