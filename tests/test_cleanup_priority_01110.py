import unittest
from types import SimpleNamespace as N
import test_siege_0147 as siege_tests

class CleanupPriorityTests(unittest.TestCase):
    def scene(self):
        helper=siege_tests.SiegeTests()
        return helper,helper.game()

    def test_idle_fleeing_worker_then_construction_then_completed_tower(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene()
        tower=h.enemy('hgtw',10,200);new=h.enemy('htow',11,400);worker=h.enemy('hpea',12,850)
        p[new.handle]=N(kind='construction');f[:]=[tower,new,worker]
        for now,target in ((10,worker),(12,new),(14,tower)):
            cmd.clear();b.fight(a,f,now)
            self.assertEqual({t for op,u,t in cmd if op=='attack'},{target.handle})
            f.remove(target)

    def test_last_visible_worker_without_buildings_is_still_intercepted(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();worker=h.enemy('uaco',12,700);f.append(worker)
        self.assertTrue(b.focus_siege(a,f,10))
        self.assertTrue(all(cur[u.handle] is worker for u in a))

    def test_hidden_unreachable_or_far_worker_does_not_divert_demolition(self):
        for case in ('hidden','unreachable','far'):
            h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();tower=h.enemy('hgtw',10,100);worker=h.enemy('opeo',12,800);f[:]=[tower,worker]
            if case=='hidden':worker.visible_to=lambda me:False
            if case=='far':worker.x=1300
            if case=='unreachable':b.g.path_distance=lambda start,end:None if end==(worker.x,worker.y) else 100
            self.assertIs(b.siege.choose(b.g,a,f,10),tower)

    def test_damaged_completed_building_is_not_assumed_under_construction(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();tower=h.enemy('hgtw',10,200);base=h.enemy('htow',11,50,10);f[:]=[base,tower]
        self.assertIs(b.siege.choose(b.g,a,f,10),tower)

    def test_surviving_combat_threat_still_preempts_cleanup(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();f[:]=[h.enemy('hpea',10,200),h.enemy('htow',11,300),h.enemy('ogru',12,80)]
        self.assertIsNone(b.siege.choose(b.g,a,f,10))

    def test_repeated_rejected_worker_orders_yield_to_building_then_retry(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();tower=h.enemy('hgtw',10,200);worker=h.enemy('opeo',11,300);f[:]=[tower,worker]
        original=b.g.attack
        b.g.attack=lambda u,t,**kw:False if t is worker else original(u,t,**kw)
        for now in (10,12,14):b.focus_siege(a,f,now)
        b.focus_siege(a,f,16)
        self.assertTrue(all(cur.get(u.handle) is tower for u in a))
        self.assertIs(b.siege.choose(b.g,a,f,25),worker)

    def test_one_accepted_attack_prevents_team_rejection_backoff(self):
        h,(b,a,f,cmd,cur,ids,p,ev)=self.scene();worker=h.enemy('opeo',11,300);f.append(worker)
        b.g.attack=lambda u,t,**kw:u is a[0]
        for now in (10,12,14,16):b.focus_siege(a,f,now)
        self.assertIs(b.siege.choose(b.g,a,f,17),worker)
