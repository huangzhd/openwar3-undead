import unittest
from types import SimpleNamespace as N
from test_baseline import unit
from test_micro_loot import dist
from undead.policy import Situation,Action,choose_rule
from undead.controller import Controller

class AttackTests(unittest.TestCase):
    def test_orb_boundary_overrides_available_camps_and_expansions(self):
        s=Situation(500,tier=2,lich=True,orb=False,creep_targets_available=True)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.tier=3
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.orb=True;s.third_hero=True
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.expansion=True
        self.assertEqual(choose_rule(s),Action.ATTACK)

    def test_ready_attack_commitment_still_yields_to_safety_and_defense(self):
        s=Situation(1000,tier=3,lich=True,orb=True,third_hero=True,attack_committed=True,creep_targets_available=True,army_hp=2000)
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.threatened=True
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.local_enemy_hp=4000
        self.assertEqual(choose_rule(s),Action.RETREAT)
        s.threatened=False;s.local_enemy_hp=0
        self.assertEqual(choose_rule(s),Action.ATTACK)
        self.assertEqual(choose_rule(Situation(0)),Action.CREEP)

    def test_destroyed_expansion_immediately_advances_to_main_without_hidden_reads(self):
        seen=[];moves=[]
        g=N(me=lambda:0,dist=dist,is_building=lambda u:True,visible=lambda *p:False)
        b=Controller(g,lambda event,**kw:seen.append((event,kw)))
        b.enemy_main=(5000,0)
        expansion=unit('htow',10,x=1000)
        b.memory.update([expansion],1,0,lambda u:True)
        b.go=lambda army,point,now,attack=False:moves.append(point)
        b.fight=lambda *args:None
        army=[unit('Udea',1,owner=0)]
        b.advance_attack(army,[],(900,0),5)
        self.assertEqual(moves[-1],(1000,0)) # fog cannot establish destruction
        g.visible=lambda *p:True
        b.advance_attack(army,[expansion],(900,0),6)
        self.assertEqual(moves[-1],(1000,0)) # visible live building keeps the objective
        b.advance_attack(army,[],(900,0),7)
        self.assertEqual(moves[-1],(5000,0))
        self.assertFalse(b.memory.units)
        self.assertIn('enemy_site_empty',[event for event,_ in seen])
        self.assertEqual([row['reason'] for event,row in seen if event=='attack_goal'],['known_expansion','enemy_main'])

    def test_neutral_sites_are_not_removed_as_destroyed_enemy_structures(self):
        g=N(me=lambda:0,dist=dist,is_building=lambda u:True,visible=lambda *p:True)
        b=Controller(g,lambda *a,**kw:None)
        neutral=unit('nmh1',30,owner=15,x=100)
        b.memory.update([neutral],1,0,lambda u:True)
        b.clear_attack_sites([], (0,0),2)
        self.assertIn(neutral.handle,b.memory.units)

    def test_empty_main_moves_to_other_expansions_without_returning_to_creeping(self):
        moves=[]
        g=N(me=lambda:0,dist=dist,path_distance=dist,is_building=lambda u:True,
            visible=lambda *p:True,map=lambda:None)
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=0,y=0);b.enemy_main=(5000,0)
        b.creeping.catalog=[dict(kind='expansion',x=7000,y=0)]
        b.go=lambda army,point,now,attack=False:moves.append(point)
        b.fight=lambda *a:None
        b.advance_attack([unit('Udea',1,owner=0)],[],(5000,0),1)
        self.assertTrue(b.main_searched)
        self.assertEqual(moves[-1],(7000,0))
        self.assertIsNone(b.creeping.active)

    def test_known_building_persists_while_hidden_and_mobiles_expire(self):
        b=Controller(N(),lambda *a,**kw:None)
        b.memory.update([unit('htow',10),unit('hfoo',11)],1,0,lambda u:u.type=='htow')
        b.memory.update([],200,0,lambda u:u.type=='htow')
        self.assertEqual({u.type for u in b.memory.units.values()},{'htow'})

if __name__=='__main__':unittest.main()
