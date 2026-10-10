import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.creeping import Creeping
from undead.formation import Formation,distance
from undead.policy import Situation,Action,choose_rule
from undead.controller import Controller

class CreepTests(unittest.TestCase):
    def game(self):
        return N(map=lambda:True,creeps=lambda:[],creep_camps=lambda:[],dist=dist,
                 visible=lambda *p:True,path_distance=dist)
    def camps(self):
        return [dict(id='ogre',kind='ogre',x=-3000,y=4000,max_level=3,hp=1200),
                dict(id='murloc',kind='murloc',x=-3400,y=-800,max_level=3,hp=2100),
                dict(id='expansion',kind='expansion',x=-4600,y=-2900,max_level=5,hp=1400),
                dict(id='hard',kind='other',x=-6400,y=-3500,max_level=7,hp=2650)]
    def test_murloc_waits_for_actual_tier_two_statue(self):
        g=self.game();plan=Creeping(lambda *a,**k:None,self.camps())
        army=[unit('Udea',1,0)]+[unit('ucry',i+2,0) for i in range(4)]
        home=N(x=-5100,y=2900)
        goal,_=plan.choose(g,army,(-5100,2900),home,1)
        self.assertEqual(plan.active['id'],'ogre')
        goal,_=plan.choose(g,army,goal,home,3)
        self.assertEqual(plan.active['id'],'expansion')
        goal,_=plan.choose(g,army,goal,home,5)
        self.assertIsNone(plan.active)
        army.append(unit('uobs',20,0));plan.tier=2
        plan.choose(g,army,(-3400,-800),home,6)
        self.assertEqual(plan.active['id'],'murloc')

    def test_nearby_safe_expansion_can_beat_distant_ogre(self):
        g=self.game();plan=Creeping(lambda *a,**k:None,self.camps())
        army=[unit('Udea',1,0)]+[unit('ucry',i+2,0) for i in range(4)]
        home=N(x=-5100,y=2900)
        plan.choose(g,army,(-4600,-2800),home,1)
        self.assertEqual(plan.active['id'],'expansion')

    def test_poison_difficulty_can_exclude_same_level_camp_and_low_health_cancels_goal(self):
        g=self.game();home=N(x=-5100,y=2900)
        camps=[dict(id='plain',kind='other',x=-5000,y=2000,max_level=3,hp=800,level_sum=8,difficulty=8),
               dict(id='poison',kind='other',x=-5000,y=2100,max_level=3,hp=800,level_sum=8,difficulty=10)]
        plan=Creeping(lambda *a,**k:None,camps)
        army=[unit('Udea',1,0,600),unit('ucry',2,0,600)]
        self.assertEqual([c['id'] for c in plan.candidates(g,army,home,1)],['plain'])
        plan.choose(g,army,(-5100,2900),home,1)
        for u in army:u.hp=100
        self.assertIsNone(plan.choose(g,army,(-5100,2900),home,2)[0])
        self.assertIn('plain',plan.deferred)

    def test_ground_route_detour_changes_selection(self):
        g=self.game();home=N(x=-5100,y=2900)
        camps=self.camps();plan=Creeping(lambda *a,**k:None,camps)
        army=[unit('Udea',1,0)]+[unit('ucry',i+2,0) for i in range(4)]
        g.path_distance=lambda a,b:10000 if b[1]==4000 else dist(a,b)
        plan.choose(g,army,(-5100,2900),home,1)
        self.assertEqual(plan.active['id'],'expansion')
    def test_lich_opens_level_seven_camps_without_reading_hidden_units(self):
        g=self.game();plan=Creeping(lambda *a,**k:None,[self.camps()[-1]])
        home=N(x=-5100,y=2900)
        army=[unit('Udea',1,0)]+[unit('ucry',i+2,0) for i in range(4)]
        self.assertFalse(plan.has_work(g,army,home,1))
        army.append(unit('Ulic',8,0))
        self.assertTrue(plan.has_work(g,army,home,2))
        goal,_=plan.choose(g,army,(-5000,0),home,3)
        self.assertIsNotNone(goal)
    def test_unseen_empty_camp_is_not_marked_cleared(self):
        g=self.game();g.visible=lambda *p:False
        plan=Creeping(lambda *a,**k:None,self.camps()[:1])
        army=[unit('Udea',1,0),unit('ucry',2,0)]
        home=N(x=-5100,y=2900)
        goal,_=plan.choose(g,army,(-5000,2900),home,1)
        plan.choose(g,army,goal,home,3)
        self.assertFalse(plan.cleared)
        self.assertIsNotNone(plan.active)
    def test_stalled_target_is_deferred_and_another_is_selected(self):
        g=self.game();events=[];plan=Creeping(lambda e,**kw:events.append((e,kw)),self.camps())
        army=[unit('Udea',1,0)]+[unit('ucry',i+2,0) for i in range(4)]
        home=N(x=-5100,y=2900)
        plan.choose(g,army,(-5100,2900),home,1)
        plan.choose(g,army,(-5100,2900),home,28)
        self.assertNotEqual(plan.active['id'],'ogre')
        self.assertTrue(any(e=='creep_target_deferred' for e,_ in events))
    def test_visible_damage_counts_as_progress_even_if_army_stands_still(self):
        g=self.game();creep=unit('nogr',99,-3000);creep.y=4000
        g.creeps=lambda:[creep]
        plan=Creeping(lambda *a,**kw:None,self.camps()[:1])
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        plan.choose(g,army,(-3100,3700),home,1)
        plan.choose(g,army,(-3100,3700),home,2)
        creep.hp-=100
        plan.choose(g,army,(-3100,3700),home,24)
        plan.choose(g,army,(-3100,3700),home,40)
        self.assertIsNotNone(plan.active)
    def test_roadside_damage_keeps_goal_but_idle_blocker_does_not(self):
        g=self.game();foe=unit('hfoo',99,-5100)
        g.visible=lambda *p:False
        plan=Creeping(lambda *a,**kw:None,self.camps())
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        center=(-5100,0)
        plan.choose(g,army,center,home,1,[foe])
        foe.hp-=50
        plan.choose(g,army,center,home,24,[foe])
        plan.choose(g,army,center,home,40,[foe])
        self.assertEqual(plan.active['id'],'ogre')
        plan.choose(g,army,center,home,51,[foe])
        self.assertIn('ogre',plan.deferred)

    def test_shopping_pause_preserves_goal_and_restarts_bounded_stall_timer(self):
        g=self.game();g.visible=lambda *p:False
        plan=Creeping(lambda *a,**kw:None,self.camps())
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        center=(-5100,2900)
        plan.choose(g,army,center,home,1)
        plan.pause(20,'shopping')
        plan.choose(g,army,center,home,120)
        plan.choose(g,army,center,home,140)
        self.assertEqual(plan.active['id'],'ogre')
        plan.choose(g,army,center,home,146)
        self.assertIn('ogre',plan.deferred)

    def test_route_progress_around_woods_uses_ground_distance(self):
        g=self.game();g.visible=lambda *p:False
        remaining=[5000];g.path_distance=lambda *a:remaining[0]
        plan=Creeping(lambda *a,**kw:None,self.camps())
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        plan.choose(g,army,(-5100,2900),home,1)
        remaining[0]=4000
        plan.choose(g,army,(-6000,2000),home,24)
        plan.choose(g,army,(-6000,2000),home,40)
        self.assertEqual(plan.active['id'],'ogre')

    def test_pulling_dk_counts_for_camp_strength_without_receiving_attack_orders(self):
        g=self.game();foe=unit('nogr',99,-3000,1200);foe.y=4000;g.creeps=lambda:[foe]
        bot=Controller(g,lambda *a,**kw:None)
        bot.creeping=Creeping(lambda *a,**kw:None,self.camps()[:1])
        dk=unit('Udea',1,-3100,675);fiend=unit('ucry',2,-3100,550)
        bot.home=N(x=-5100,y=2900);bot.creep_strength=[dk,fiend]
        orders=[];bot.go=lambda army,*a,**kw:orders.extend(army)
        bot.fight=lambda *a:None
        bot.creep([fiend],(-3100,3700),300)
        bot.creep([fiend],(-3100,3700),302)
        self.assertEqual(bot.creeping.active['id'],'ogre')
        self.assertTrue(orders)
        self.assertTrue(all(u is fiend for u in orders))

    def test_repeated_stall_stops_revisiting_without_marking_camp_cleared(self):
        g=self.game();g.visible=lambda *p:False
        plan=Creeping(lambda *a,**kw:None,self.camps()[:1])
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        for now in (1,28,119,146):plan.choose(g,army,(-5100,2900),home,now)
        self.assertFalse(plan.has_work(g,army,home,500))
        self.assertFalse(plan.cleared)
        self.assertIsNone(plan.choose(g,army,(-5100,2900),home,500)[0])
        s=Situation(500,army_hp=5000,tier=3,lich=True,orb=True,third_hero=True,statues=2,fiends=6,
                    creep_targets_available=plan.has_work(g,army,home,500))
        self.assertEqual(choose_rule(s),Action.ATTACK)
        fresh=Creeping(lambda *a,**kw:None,self.camps()[:1])
        self.assertTrue(fresh.has_work(g,army,home,1))

    def test_safety_retreat_does_not_exhaust_a_camp(self):
        g=self.game();plan=Creeping(lambda *a,**kw:None,self.camps()[:1])
        army=[unit('Udea',1,0),unit('ucry',2,0)];home=N(x=-5100,y=2900)
        for now in (1,100,200):
            plan.choose(g,army,(-5100,2900),home,now)
            plan.defer(now+1,'safety_retreat')
        self.assertTrue(plan.has_work(g,army,home,500))

    def test_camps_keep_rule_creeping_but_defense_and_expansion_override(self):
        s=Situation(500,army_hp=5000,tier=2,lich=True,orb=False,statues=2,fiends=6,creep_targets_available=True)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.expansion=True
        self.assertEqual(choose_rule(s),Action.HARASS)
        s.threatened=True
        self.assertEqual(choose_rule(s),Action.DEFEND)

class MovementTests(unittest.TestCase):
    def test_attack_route_fights_blocking_visible_creeps_instead_of_doing_nothing(self):
        g=N(dist=dist);bot=Controller(g,lambda *a,**kw:None)
        army=[unit('Udea',1,0),unit('ucry',2,100)]
        foe=unit('nogr',3,400);bot.battle_enemies=[foe];bot.action=Action.ATTACK
        fought=[];bot.fight=lambda a,enemies,now:fought.extend(enemies)
        bot.go(army,(3000,0),1,attack=True)
        self.assertEqual(fought,[foe])
    def test_new_distant_fiend_catches_up_without_stopping_hero_cohort(self):
        f=Formation(lambda *a,**kw:None)
        army=[unit('Udea',1,0),unit('Ulic',2,50),unit('ucry',3,100)]
        f.plan(army,(2000,0),1,distance,lambda a,b:[b])
        recruit=unit('ucry',4,-2500)
        orders=f.plan([*army,recruit],(2000,0),3,distance,lambda a,b:[b])
        self.assertNotEqual(f.stage,'regroup')
        self.assertIn(recruit.handle,f.joiners)
        self.assertEqual(orders[-1][1],f.anchor)
        recruit.x=0
        f.plan([*army,recruit],(2000,0),5,distance,lambda a,b:[b])
        self.assertNotIn(recruit.handle,f.joiners)
    def test_stalled_rally_moves_to_a_new_shared_point(self):
        f=Formation(lambda *a,**kw:None)
        army=[unit('Udea',1,0),unit('Ulic',2,50),unit('ucry',3,-1500)]
        detour=lambda a,b:distance(a,b)*3
        f.plan(army,(2000,0),1,detour,lambda a,b:[b])
        first=f.rally
        orders=f.plan(army,(2000,0),15,detour,lambda a,b:[b])
        self.assertNotEqual(f.rally,first)
        self.assertEqual({point for _,point,_ in orders},{f.rally})

if __name__=='__main__':unittest.main()
