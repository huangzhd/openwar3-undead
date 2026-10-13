import unittest
import test_building_repair_0191 as repair_tests
from test_baseline import unit
from openwar3.orders import ORDER

class RepairUnderFireTests(unittest.TestCase):
    def make(self):
        g,e,home,mine,workers,orders,current=repair_tests.RepairTests().make()
        mine.hp=mine.hp_max;home.hp=30;home.hp_max=100
        foe=unit('ogru',99,owner=1,x=30);target=[home]
        g.enemies=lambda:[foe];g.current_target=lambda _:target[0]
        g.current_order=lambda w:dict(target=home.handle,order=current.get(w.handle,0))
        return g,e,home,mine,workers,orders,current,foe,target

    def test_healthy_workers_repair_when_enemy_targets_hall_not_them(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make()
        self.assertTrue(e.repairs.tick(g,e,h,100))
        self.assertEqual({o[2] for o in orders},{h.handle})
        self.assertTrue(e.repairs.reserved)

    def test_actual_worker_focus_releases_that_worker(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();e.repairs.tick(g,e,h,100)
        handle=next(iter(e.repairs.reserved));target[0]=next(w for w in ws if w.handle==handle)
        e.repairs.tick(g,e,h,101)
        self.assertNotIn(handle,e.repairs.reserved)
        self.assertTrue(e.repairs.reserved) # Other healthy workers still repair.

    def test_recent_worker_damage_releases_even_when_enemy_target_is_building(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();e.repairs.tick(g,e,h,100)
        handle=next(iter(e.repairs.reserved));worker=next(w for w in ws if w.handle==handle)
        worker.hp-=5
        e.repairs.tick(g,e,h,101)
        self.assertNotIn(handle,e.repairs.reserved)
        e.repairs.tick(g,e,h,102)
        self.assertNotIn(handle,e.repairs.reserved)

    def test_unknown_enemy_target_does_not_assume_worker_safety(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();target[0]=None
        self.assertFalse(e.repairs.tick(g,e,h,100));self.assertFalse(orders)

    def test_net_damage_during_real_restoration_does_not_cancel_after_fifteen_seconds(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();e.repairs.tick(g,e,h,100)
        initial=set(e.repairs.reserved)
        for handle in initial:cur[handle]=ORDER('restoration')
        h.hp=25
        e.repairs.tick(g,e,h,116)
        self.assertEqual(e.repairs.reserved,initial)
        self.assertTrue(all(cur[k]==ORDER('restoration') for k in initial))
        # Once enemy fire ends, genuinely stalled work still has a deadline.
        g.enemies=lambda:[]
        e.repairs.tick(g,e,h,132)
        self.assertFalse(e.repairs.reserved)

    def test_wrong_restoration_target_does_not_keep_failing_job_alive(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();e.repairs.tick(g,e,h,100)
        for handle in e.repairs.reserved:cur[handle]=ORDER('restoration')
        g.current_order=lambda w:dict(target=m.handle)
        e.repairs.tick(g,e,h,116)
        self.assertFalse(e.repairs.reserved)

    def test_critical_hall_beats_moderately_damaged_mine(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make();m.hp=400
        e.repairs.tick(g,e,h,100)
        self.assertEqual({o[2] for o in orders},{h.handle})

    def test_critical_repair_funds_precede_hero_revival(self):
        g,e,h,m,ws,orders,cur,foe,target=self.make()
        e.ever_heroes={'Udea','Ulic'};g.own=[u for u in g.own if u.type!='Udea']
        revived=[];g.revive=lambda altar:revived.append(altar.handle) or True
        e.tick(g,100)
        self.assertTrue(e.repairs.reserved);self.assertFalse(revived)
        h.hp=h.hp_max
        e.tick(g,101)
        self.assertFalse(e.repairs.reserved);self.assertTrue(revived)

if __name__=='__main__':unittest.main()
