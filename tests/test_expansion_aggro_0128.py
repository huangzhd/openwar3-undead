import unittest
from types import SimpleNamespace as N
from test_baseline import unit as seen_unit
from test_micro_loot import unit,dist
from undead.structures import is_structure
from undead.policy import ScoutMemory,Action
from undead.controller import Controller
from undead.creep_aggro import CreepAggro
from undead.referee import Referee
from openwar3.game import Game

class ExpansionRegressionTests(unittest.TestCase):
    def test_mobile_ancient_and_player_mine_survive_fog_and_remain_attack_objectives(self):
        tree=seen_unit('etol',1,x=3840);mine=seen_unit('egol',2,x=4352)
        m=ScoutMemory();m.update([tree,mine],1066.58,0,is_structure)
        m.update([],1300,0,is_structure)
        self.assertEqual(set(m.units),{tree.handle,mine.handle})
        self.assertTrue(all(u.building for u in m.units.values()))
        g=N(dist=dist,me=lambda:0,visible=lambda *p:False)
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=-4500,y=0);b.enemy_main=(4500,6000)
        b.main_searched=True;b.memory=m;moves=[]
        b.go=lambda army,p,now,attack=False:moves.append(p);b.fight=lambda *a:None
        b.attack_search.choose=lambda *a: self.fail('Known live expansion must prevent map search')
        b.advance_attack([],[],(3000,0),1300)
        self.assertEqual(moves[-1],(3840,0))

    def test_ancient_or_mine_is_not_a_win_until_destroyed_and_neutral_mine_does_not_keep_enemy_alive(self):
        for code in ['etol','etoa','etoe','eaom','eaoe','eaow','etrp','egol','ugol']:
            with self.subTest(code=code):
                own=seen_unit('unpl',1,owner=0);enemy=seen_unit(code,2);neutral=seen_unit('ngol',3,owner=15)
                r=Referee();raw=N(in_game=True,units=[own,enemy,neutral])
                self.assertIsNone(r.observe(raw,0,is_structure))
                enemy.alive=False
                self.assertEqual(r.observe(raw,0,is_structure),('win','all_enemy_buildings_destroyed'))

    def test_goal_stays_on_same_building_despite_movement_or_new_foundation(self):
        tree=seen_unit('etol',1,x=3000);altar=seen_unit('eate',2,x=4000)
        g=N(dist=dist,me=lambda:0,visible=lambda *p:False)
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=-4500,y=0);b.enemy_main=(4500,6000)
        b.memory.update([tree,altar],1,0,is_structure);moves=[]
        b.go=lambda army,p,now,attack=False:moves.append(p);b.fight=lambda *a:None
        b.advance_attack([],[],(3100,0),1)
        b.advance_attack([],[],(3900,0),2)
        self.assertEqual(moves,[(3000,0),(3000,0)])
        tree.alive=False;b.memory.update([tree],3,0,is_structure)
        b.advance_attack([],[],(3900,0),3)
        self.assertEqual(moves[-1],(4000,0))

    def test_old_speed_classifier_reproduces_expansion_disappearance(self):
        m=ScoutMemory();tree=seen_unit('etol',1,x=3840)
        m.update([tree],1066.58,0,lambda u:Game.is_building(None,u));m.update([],1300,0,is_structure)
        self.assertFalse(m.units)

class CreepAggroTests(unittest.TestCase):
    def setup(self):
        victim=unit('ucry',1,0);sk=unit('uske',2,100);creep=unit('ngna',3,200);creep.owner=12
        targets={creep.handle:victim};orders=[];events=[]
        def attack(u,t,force=False):
            orders.append(('attack',u.handle,t.handle,force));targets[u.handle]=t;return True
        def stop(u):orders.append(('stop',u.handle));targets.pop(u.handle,None)
        g=N(dist=dist,current_target=lambda u:targets.get(u.handle),attack=attack,stop=stop)
        a=CreepAggro(lambda ev,**kw:events.append((ev,kw)))
        return a,g,victim,sk,creep,targets,orders,events

    def test_allied_attack_then_only_observed_skeleton_target_allows_confirmed_return(self):
        a,g,v,sk,e,targets,orders,events=self.setup()
        a.step(g,[v,sk],[e],0,True)
        self.assertEqual(orders[-1],('attack',v.handle,sk.handle,True))
        self.assertIn(v.handle,a.protected)
        a.step(g,[v,sk],[e],.5,True)
        self.assertIn(v.handle,a.protected)
        self.assertFalse(any(ev=='creep_aggro_confirmed' for ev,_ in events))
        targets[e.handle]=sk;a.step(g,[v,sk],[e],.8,True)
        self.assertFalse(a.protected)
        self.assertEqual(orders[-1],('attack',v.handle,e.handle,False))
        self.assertTrue(any(ev=='creep_aggro_confirmed' for ev,_ in events))

    def test_failed_transfer_stops_friendly_fire_and_retries_at_most_twice(self):
        a,g,v,sk,e,targets,orders,events=self.setup()
        for t in [0,1.3,5,10,11.3,20,30]:a.step(g,[v,sk],[e],t,True)
        self.assertFalse(a.protected)
        self.assertNotIn(v.handle,targets)
        attempts=[o for o in orders if o==('attack',v.handle,sk.handle,True)]
        self.assertEqual(len(attempts),2)
        self.assertFalse(any(ev=='creep_aggro_confirmed' for ev,_ in events))

    def test_safety_cancel_never_overwrites_new_healing_cast_or_retreat(self):
        a,g,v,sk,e,targets,orders,events=self.setup()
        a.step(g,[v,sk],[e],0,True);count=len(orders)
        a.step(g,[v,sk],[e],.3,False,{v.handle})
        self.assertFalse(a.protected);self.assertEqual(len(orders),count)
        a.step(g,[v,sk],[e],10,False)
        self.assertEqual(len(orders),count)

    def test_missing_or_unknown_creep_target_cannot_count_as_confirmed(self):
        a,g,v,sk,e,targets,orders,events=self.setup()
        a.step(g,[v,sk],[e],0,True);targets.pop(e.handle)
        a.step(g,[v,sk],[],1.3,True)
        self.assertFalse(a.protected)
        self.assertEqual(orders[-1],('stop',v.handle))
        self.assertFalse(any(ev=='creep_aggro_confirmed' for ev,_ in events))

    def test_group_attack_does_not_overwrite_pending_allied_attack(self):
        a,g,v,sk,e,targets,orders,events=self.setup()
        b=Controller(g,lambda *a,**kw:None);b.creep_aggro=a
        a.step(g,[v,sk],[e],0,True)
        g.cooldown=lambda *a:1;g.units=lambda *a:[]
        b.fight([v,sk],[e],.2)
        self.assertIs(targets[v.handle],sk)
        self.assertIs(targets[sk.handle],e)

if __name__=='__main__':unittest.main()
