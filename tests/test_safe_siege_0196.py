import unittest
from types import SimpleNamespace as N
import test_siege_0147 as legacy
from test_micro_loot import unit,dist
from undead.siege import safe_route,fire_clearance
from openwar3.orders import REPAIR
from undead.policy import Action

class SafeSiegeTests(unittest.TestCase):
    def setup_battle(self):
        b,a,f,cmd,cur,ids,p,ev=legacy.SiegeTests().game()
        b.g.map=lambda:N(walkable=lambda x,y:True)
        b.g.walk_path=lambda start,end:[start,end]
        def hold(u):
            cur.pop(u.handle,None);cmd.append(('hold',u.handle,None));return True
        b.g.hold=hold
        return b,a,f,cmd,cur,ids,p,ev

    def enemy(self,*args):return legacy.SiegeTests().enemy(*args)

    def test_isolated_tower_is_attacked_even_without_full_health(self):
        for hp in (500,350):
            b,a,f,cmd,cur,ids,p,ev=self.setup_battle();f.append(self.enemy('hgtw',10,500))
            for u in a:u.hp=hp
            b.fight(a,f,10)
            self.assertTrue(all(cur[u.handle] is f[0] for u in a))
            self.assertFalse(any(op in ('move','hold') for op,_,_ in cmd))

    def test_defenders_inside_tower_fire_are_fought_in_place(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle()
        tower=self.enemy('hgtw',10,500);soldier=self.enemy('hfoo',11,100);f.extend([tower,soldier])
        b.fight(a,f,10)
        self.assertTrue(all(cur[u.handle] is soldier for u in a))
        self.assertFalse(any(op in ('move','hold') for op,_,_ in cmd))

    def test_unwalkable_escape_does_not_cancel_existing_attack(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle()
        tower=self.enemy('hgtw',10,500);soldier=self.enemy('hfoo',11,100);f.extend([tower,soldier])
        b.g.map=lambda:N(walkable=lambda x,y:False)
        for u in a:cur[u.handle]=soldier
        b.fight(a,f,10)
        self.assertTrue(all(cur[u.handle] is soldier for u in a))
        self.assertFalse(any(op in ('move','hold') for op,_,_ in cmd))

    def test_actual_repairer_still_preempts_building(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle()
        tower=self.enemy('hgtw',10,500);worker=self.enemy('hpea',13,450)
        ids[worker.handle]=REPAIR;cur[worker.handle]=tower;f.extend([tower,worker])
        b.fight(a,f,10)
        self.assertTrue(all(cur[u.handle] is worker for u in a))

    def test_ancient_fire_does_not_force_retreat(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle()
        f.extend([self.enemy('etol',10,100),self.enemy('earc',11,150)])
        b.fight(a,f,10)
        self.assertTrue(any(op=='attack' for op,_,_ in cmd))
        self.assertFalse(any(op in ('move','hold') for op,_,_ in cmd))

    def test_casting_statue_and_pulling_units_remain_protected(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle();f.append(self.enemy('hgtw',10,500))
        statue=unit('uobs',5,0);a.append(statue)
        b.cast_until[a[0].handle]=20;b.micro.pulling.add(a[1].handle)
        b.fight(a,f,10)
        self.assertFalse(any(h in {a[0].handle,a[1].handle,statue.handle} for _,h,_ in cmd))
        self.assertIs(cur[a[2].handle],f[0])

    def test_defense_and_retreat_keep_existing_control(self):
        b,a,f,cmd,cur,ids,p,ev=self.setup_battle();f.append(self.enemy('hgtw',10,500))
        for action in (Action.DEFEND,Action.RETREAT):
            b.action=action;self.assertFalse(b.focus_siege(a,f,10))
        self.assertFalse(cmd)
