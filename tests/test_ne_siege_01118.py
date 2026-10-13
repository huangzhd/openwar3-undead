import unittest
from types import SimpleNamespace as N
import test_siege_0147 as fixture
from undead.siege import ANCIENTS,building_priority

class NightElfSiegeTests(unittest.TestCase):
    def test_attacking_ancient_then_constructing_ancient_then_moon_well_then_others(self):
        h=fixture.SiegeTests();b,a,f,cmd,cur,ids,p,ev=h.game()
        attack=h.enemy('eaom',10,80);new=h.enemy('eaoe',11,400);moon=h.enemy('emow',12,200);other=h.enemy('eate',13,100)
        f[:]=[other,moon,new,attack];cur[attack.handle]=a[0];p[new.handle]=N(kind='construction')
        for now,target in enumerate((attack,new,moon,other),10):
            self.assertIs(b.siege.choose(b.g,a,f,now),target);f.remove(target)

    def test_idle_or_out_of_range_ancient_is_not_an_attacking_tree(self):
        h=fixture.SiegeTests()
        for code in ANCIENTS:
            b,a,f,cmd,cur,ids,p,ev=h.game();tree=h.enemy(code,10,700);moon=h.enemy('emow',11,200);f[:]=[tree,moon]
            self.assertIs(b.siege.choose(b.g,a,f,10),moon)
            tree.x=2000;cur[tree.handle]=a[0]
            self.assertEqual(building_priority(b.g,tree),5)

    def test_low_health_upgrade_or_unknown_production_is_not_new_construction(self):
        h=fixture.SiegeTests()
        for production in (None,N(kind='upgrade'),N(kind='queue')):
            b,a,f,cmd,cur,ids,p,ev=h.game();tree=h.enemy('etol',10,80,10);moon=h.enemy('emow',11,200);f[:]=[tree,moon]
            p[tree.handle]=production
            self.assertIs(b.siege.choose(b.g,a,f,10),moon)

    def test_non_tree_construction_does_not_jump_ahead_of_moon_well(self):
        h=fixture.SiegeTests();b,a,f,cmd,cur,ids,p,ev=h.game()
        altar=h.enemy('eate',10,80);moon=h.enemy('emow',11,200);f[:]=[altar,moon];p[altar.handle]=N(kind='construction')
        self.assertIs(b.siege.choose(b.g,a,f,10),moon)

    def test_worker_interception_remains_except_active_tree_fire_takes_priority(self):
        h=fixture.SiegeTests();b,a,f,cmd,cur,ids,p,ev=h.game()
        worker=h.enemy('ewsp',10,150);tree=h.enemy('eaom',11,80);f[:]=[worker,tree]
        self.assertIs(b.siege.choose(b.g,a,f,10),worker)
        cur[tree.handle]=a[0];self.assertIs(b.siege.choose(b.g,a,f,11),tree)
        self.assertEqual(ev[-1]['reason'],'attacking_ancient')

if __name__=='__main__':unittest.main()
