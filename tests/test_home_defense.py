import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
from test_baseline import unit,FakeGame
from test_micro_loot import dist
from undead.home_defense import HomeDefense,RADIUS
from undead.economy import Economy
from undead.controller import Controller
from undead.policy import Action
from session import Session

class DefenseTests(unittest.TestCase):
    def make(self):
        home=unit('unpl',1,0);team=[unit('ugho',i+10,0,x=200+i*30) for i in range(3)]
        for u in team:u.hp=u.hp_max=340
        target=unit('ocat',40,1,x=1100);target.hp=target.hp_max=500
        tree=unit('tree',50,15,x=-300);tree.handle_lo=50;tree.handle_hi=0;orders=[];targets={};events=[]
        def attack(u,t):orders.append(('attack',u.handle,t.handle));targets[u.handle]=t;return True
        def move(u,x,y):orders.append(('move',u.handle,(x,y)));targets.pop(u.handle,None);return True
        def gather(u,t):orders.append(('gather',u.handle,t.handle));targets[u.handle]=t;return True
        g=N(units=lambda *a:team,dist=dist,path_distance=dist,me=lambda:0,current_target=lambda u:targets.get(u.handle),
            attack=attack,move=move,gather=gather,trees=lambda *a:[tree])
        d=HomeDefense(lambda ev,**kw:events.append((ev,kw)))
        return g,d,home,team,target,orders,targets,events

    def test_two_distant_lumber_ghouls_handle_one_raider_without_recalling_army(self):
        g,d,home,team,target,orders,targets,events=self.make()
        team.pop();team[0].x=-1500;team[1].x=-1600;target.type='ugho';target.hp=340
        self.assertTrue(d.tick(g,home,[target],1,lambda _:False))
        self.assertEqual(len(orders),2);self.assertEqual(d.reserved,{u.handle for u in team})
        target.x=RADIUS+1
        self.assertFalse(d.tick(g,home,[target],4,lambda _:False))
        self.assertTrue(all(o[0]=='move' for o in orders[-2:]))

    def test_unknown_path_and_missing_third_ghoul_do_not_raise_or_fake_defense(self):
        g,d,home,team,target,orders,targets,events=self.make();target.type='ugho';target.hp=340
        g.path_distance=lambda *a:None
        self.assertFalse(d.tick(g,home,[target],1,lambda _:False));self.assertFalse(orders)
        self.assertTrue(d.tower_needed)

    def test_spirit_tower_handles_covered_raid_but_not_uncovered_or_construction(self):
        for state in ('ready','far','building'):
            with self.subTest(state=state):
                g,d,home,team,target,orders,targets,events=self.make();team.clear()
                target.type='ugho';target.hp=340
                tower=unit('uzg1',90,owner=0,x=800);tower.hp=tower.hp_max=550
                g.my_buildings=lambda:[home,tower]
                g.production=lambda b:N(kind='upgrade',queue=['uzg1']) if b is tower and state=='building' else None
                if state=='far':tower.x=-800
                handled=d.tick(g,home,[target],1,lambda _:False)
                self.assertEqual(handled,state=='ready')
                self.assertEqual(bool(orders),state=='ready')

    def test_local_attack_stall_and_endangered_building_escalate(self):
        for cause in ('stall','building'):
            g,d,home,team,target,orders,targets,events=self.make();target.type='ugho';target.hp=340
            g.my_buildings=lambda:[home];g.production=lambda _:None
            self.assertTrue(d.tick(g,home,[target],1,lambda _:False))
            if cause=='building':home.hp=30;targets[target.handle]=home
            self.assertFalse(d.tick(g,home,[target],4 if cause=='building' else 22,lambda _:False))
            self.assertTrue(any(e=='home_defense_escalated' for e,_ in events))

    def test_tower_investment_saves_exact_upgrade_cost_and_does_not_duplicate(self):
        import test_growth_expansion_0149 as growth
        g=growth.GrowthGame();e=Economy(lambda *a,**kw:None);home=g.my_buildings({'unp2'})[0]
        e.home_tower_needed=True;g.costs['uzg1']=(145,40)
        g.gold=144;self.assertTrue(e.defense_tower(g,home,700));self.assertFalse(g.commands)
        g.gold=145;self.assertTrue(e.defense_tower(g,home,704))
        self.assertEqual(g.commands,['uzg1']);self.assertEqual(g.gold,0)
        g.gold=1000;self.assertFalse(e.defense_tower(g,home,708));self.assertEqual(g.commands,['uzg1'])
        tower=g.my_buildings({'uzig'})[0];g.busy.clear();tower.type='uzg1'
        self.assertFalse(e.defense_tower(g,home,750));self.assertEqual(g.commands,['uzg1'])

    def test_tower_rejected_orders_stop_after_three_attempts(self):
        import test_growth_expansion_0149 as growth
        g=growth.GrowthGame();e=Economy(lambda *a,**kw:None);home=g.my_buildings({'unp2'})[0]
        g.train=lambda b,c:g.commands.append(c) or False
        for now in (700,704,708,712,716):e.defense_tower(g,home,now)
        self.assertEqual(g.commands,['uzg1']*3)

    def test_controller_keeps_main_tactic_with_two_lumber_ghouls_against_one(self):
        import test_opening_safety_0131 as safety
        g,b,dk,allies,orders,clock=safety.EmergencyTests().controller()
        home=g.my_buildings()[0];ghouls=[unit('ugho',100+i,owner=0,x=home.x-1500-i*50) for i in range(2)]
        for u in ghouls:u.hp=u.hp_max=340
        raider=unit('ugho',200,owner=1,x=home.x+1000);raider.hp=340
        original=g.units;g.units=lambda owner,codes:ghouls if codes=={'ugho'} else original(owner,codes)
        g.enemies=lambda:[raider];g.attack=lambda u,t:orders.append(('ghoul_attack',u.handle,t.handle)) or True
        b.emergency_portal=lambda *a:True
        b.tick(forced=Action.CREEP)
        self.assertEqual(b.action,Action.CREEP)
        self.assertEqual(len([o for o in orders if o[0]=='ghoul_attack']),2)
        self.assertEqual(b.economy.ghoul_reserved,{u.handle for u in ghouls})

    def test_three_harvesters_focus_demolisher_before_ordinary_raider(self):
        g,d,home,team,target,orders,targets,events=self.make()
        footman=unit('hfoo',41,1,x=400)
        self.assertTrue(d.tick(g,home,[footman,target],1,lambda _:False))
        self.assertEqual({o[1] for o in orders},{u.handle for u in team})
        self.assertTrue(all(o[2]==target.handle for o in orders));self.assertEqual(d.reserved,{u.handle for u in team})
        d.tick(g,home,[footman,target],4,lambda _:False);self.assertEqual(len(orders),3)

    def test_retreating_or_hidden_enemy_cancels_chase_and_restores_harvest(self):
        for hidden in (False,True):
            g,d,home,team,target,orders,targets,events=self.make()
            d.tick(g,home,[target],1,lambda _:False)
            if hidden:target.visible_to=lambda _:False
            else:target.x=RADIUS+1
            self.assertFalse(d.tick(g,home,[target],4,lambda _:False))
            self.assertFalse(d.reserved);self.assertEqual([o[0] for o in orders[-3:]],['gather']*3)
            self.assertTrue(all(targets[u.handle].type=='tree' for u in team))

    def test_outer_ghouls_return_by_move_before_harvesting_and_no_immediate_redispatch(self):
        g,d,home,team,target,orders,targets,events=self.make();d.tick(g,home,[target],1,lambda _:False)
        for u in team:u.x=RADIUS+601
        self.assertFalse(d.tick(g,home,[target],4,lambda _:False))
        self.assertEqual([o[0] for o in orders[-3:]],['move']*3);self.assertEqual(len(d.returning),3)
        for u in team:u.x=200
        d.tick(g,home,[target],7,lambda _:False)
        self.assertEqual([o[0] for o in orders[-3:]],['gather']*3);self.assertFalse(d.active)
        d.tick(g,home,[target],8,lambda _:False);self.assertFalse(d.active)

    def test_hero_air_large_and_heavy_raids_remain_for_main_army(self):
        for kind in ('hero','air','large','heavy'):
            g,d,home,team,target,orders,targets,events=self.make()
            foes=[target]
            if kind=='hero':target.is_hero=True
            if kind=='large':foes=[unit('hfoo',i+60,1,x=600) for i in range(4)]
            if kind=='heavy':target.hp=2000
            self.assertFalse(d.tick(g,home,foes,1,lambda _:kind=='air'));self.assertFalse(orders)
            self.assertTrue(d.raiders)

    def test_low_health_or_unreachable_route_withdraws_without_recruiting_same_ghouls(self):
        for kind in ('health','path'):
            g,d,home,team,target,orders,targets,events=self.make();d.tick(g,home,[target],1,lambda _:False)
            if kind=='health':team[0].hp=100
            else:g.path_distance=lambda *a:5000
            self.assertFalse(d.tick(g,home,[target],4,lambda _:False));self.assertFalse(d.active)
            self.assertEqual([o[0] for o in orders[-3:]],['gather']*3)

    def test_rejected_orders_have_bounded_retries_and_never_suppress_main_defense(self):
        g,d,home,team,target,orders,targets,events=self.make()
        g.attack=lambda u,t:orders.append(('rejected',u.handle,t.handle)) or False
        for at in (1,3,5,6,7):self.assertFalse(d.tick(g,home,[target],at,lambda _:False))
        self.assertEqual(len([o for o in orders if o[0]=='rejected']),9);self.assertFalse(d.active)
        self.assertEqual(len([o for o in orders if o[0]=='gather']),3)

    def test_economy_never_overwrites_reserved_defenders_with_gathering(self):
        g=FakeGame();e=Economy(lambda *a,**kw:None);ghouls=g.units('me',{'ugho'})
        e.ghoul_reserved={u.handle for u in ghouls[:2]};g.order_of=lambda _:0
        for u in ghouls:u.has_task=False
        tree=unit('tree',100);g.trees=lambda *a:[tree];g.gather=lambda u,t:g.commands.append(('gather',u.handle))
        e.tick(g,1)
        self.assertEqual(g.commands,[('gather',ghouls[2].handle)])

    def test_controller_reserves_home_ghouls_and_does_not_pull_main_army_for_small_raid(self):
        import test_opening_safety_0131 as safety
        g,b,dk,allies,orders,clock=safety.EmergencyTests().controller()
        home=b.g.my_buildings()[0];ghouls=[unit('ugho',100+i,0,x=home.x+50*i) for i in range(3)]
        for u in ghouls:u.hp=u.hp_max=340
        raider=unit('ocat',200,1,x=home.x+1000);raider.hp=500
        original=g.units;g.units=lambda owner,codes:ghouls if codes=={'ugho'} else original(owner,codes)
        g.enemies=lambda:[raider];g.attack=lambda u,t:orders.append(('ghoul_attack',u.handle,t.handle)) or True
        b.emergency_portal=lambda *a:True
        b.tick(forced=Action.CREEP)
        self.assertEqual(b.action,Action.CREEP);self.assertEqual(b.economy.ghoul_reserved,{u.handle for u in ghouls})
        self.assertEqual(len([o for o in orders if o[0]=='ghoul_attack']),3)
        raider.is_hero=True;g.trees=lambda *a:[];g.move=lambda *a:True;clock[0]+=6
        b.tick(forced=Action.CREEP);self.assertEqual(b.action,Action.DEFEND)

class OpponentTests(unittest.TestCase):
    def check(self,difficulty=2,race=2):
        closed=[];jass=N(Player=lambda i:i,GetPlayerController=lambda _:1,GetPlayerRace=lambda _:race,GetAIDifficulty=lambda _:difficulty)
        audit=N(jass=jass,close=lambda:closed.append(True));session=Session(400,2,4)
        with patch('session.Game',return_value=audit):
            try:return session.verify_opponent(N(pid=1,me=lambda:0))
            finally:self.assertEqual(closed,[True])
    def test_engine_insane_matches_request(self):self.assertEqual(self.check()['difficulty_name'],'insane')
    def test_normal_engine_difficulty_rejects_insane_launch_label(self):
        with self.assertRaisesRegex(RuntimeError,'Actual opponent'):self.check(difficulty=1)
    def test_wrong_actual_race_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'Actual opponent'):self.check(race=1)
