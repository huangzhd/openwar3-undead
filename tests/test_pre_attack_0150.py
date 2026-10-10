import unittest
from dataclasses import replace
from types import SimpleNamespace as N
from test_baseline import unit
from test_micro_loot import dist
from test_growth_expansion_0149 import GrowthGame
from undead.policy import Action,Situation,choose_rule
from undead.controller import Controller
from undead.creeping import Creeping
from undead.economy import Economy

class PreAttackTests(unittest.TestCase):
    def ready(self):return Situation(500,tier=3,dk=True,lich=True,orb=True,third_hero=True,attack_committed=True)
    def bot(self):
        orders=[];events=[]
        g=N(dist=dist,me=lambda:0,path_distance=dist,walk_path=lambda a,b:[b],
            move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True,
            attack_move=lambda u,x,y:orders.append(('attack_move',u.handle,(x,y))) or True,
            hold=lambda u:orders.append(('hold',u.handle,None)) or True,
            current_target=lambda u:None,is_building=lambda u:u.type in {'uzig','unp2'},
            attack=lambda u,t,**kw:orders.append(('attack',u.handle,t.handle)) or True,
            stop=lambda u:orders.append(('stop',u.handle,None)) or True)
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        b.home=unit('unp2',90,owner=0,x=-4000)
        return b,orders,events
    def test_each_missing_requirement_blocks_even_previous_commitment(self):
        for field,value in [('tier',2),('tier',0),('orb',False),('lich',False),('dk',False),('third_hero',False)]:
            with self.subTest(field=field,value=value):
                self.assertEqual(choose_rule(replace(self.ready(),**{field:value})),Action.CREEP)
        self.assertEqual(choose_rule(self.ready()),Action.ATTACK)
        self.assertEqual(choose_rule(replace(self.ready(),threatened=True)),Action.DEFEND)
    def test_creep_march_cannot_intercept_or_attack_move_into_buildings(self):
        b,orders,_=self.bot();a=[unit('Udea',1,owner=0),unit('ucry',2,owner=0,x=-50)]
        b.battle_enemies=[unit('uzig',9,x=200)]
        b.go(a,(1000,0),10,attack=True)
        self.assertEqual({r[1] for r in orders},{u.handle for u in a})
        self.assertTrue(all(r[0]=='move' for r in orders))
    def test_creep_fight_does_not_select_player_building(self):
        b,orders,_=self.bot();b.fight([unit('ucry',1,owner=0)],[unit('uzig',9,x=200)],10)
        self.assertFalse(orders)
    def test_seen_structure_forces_retreat_and_releases_allied_aggro(self):
        b,orders,ev=self.bot();dk=unit('Udea',1,owner=0);sk=unit('uske',2,owner=0,x=-50)
        tower=unit('uzig',9,x=800)
        b.creeping.active=dict(id='enemy-door-ogres')
        b.creep_aggro.active=dict(victim=dk.handle,skeleton=sk.handle,creeps=[],started=9)
        self.assertTrue(b.pre_attack_retreat([dk,sk],[tower],10))
        self.assertIsNone(b.creep_aggro.active)
        self.assertEqual(b.action,Action.RETREAT)
        self.assertEqual({r[1] for r in orders if r[0]=='move'},{dk.handle,sk.handle})
        self.assertTrue(all(r[2][0]<0 for r in orders if r[0]=='move'))
        self.assertGreater(b.creeping.deferred['enemy-door-ogres'],10)
        self.assertTrue(any(e['event']=='pre_attack_base_retreat' for e in ev))
    def test_remembered_building_and_leading_hero_trigger_retreat(self):
        b,orders,_=self.bot();army=[unit('ucry',i,owner=0,x=-2000) for i in range(1,4)]+[unit('Udea',5,owner=0,x=100)]
        b.memory.update([unit('uzig',9,x=900)],1,0,lambda u:True)
        self.assertTrue(b.pre_attack_retreat(army,[],10))
        self.assertTrue(orders)
    def test_retreat_hysteresis_avoids_immediate_return_but_expires(self):
        b,_,_=self.bot();a=[unit('ucry',1,owner=0)]
        self.assertTrue(b.pre_attack_retreat(a,[unit('uzig',9,x=800)],10))
        a[0].x=-3000
        self.assertTrue(b.pre_attack_retreat(a,[],15))
        self.assertFalse(b.pre_attack_retreat(a,[],23))
    def test_ready_army_and_home_defense_are_not_blocked(self):
        b,orders,_=self.bot();a=[unit('ucry',1,owner=0)];foes=[unit('uzig',9,x=800)]
        b.situation=self.ready();self.assertFalse(b.pre_attack_retreat(a,foes,10))
        b.situation.third_hero=False;b.action=Action.DEFEND
        self.assertFalse(b.pre_attack_retreat(a,foes,11));self.assertFalse(orders)
    def test_tavern_courier_near_building_does_not_drag_main_army_home(self):
        b,_,_=self.bot();a=[unit('ucry',i,owner=0,x=-3000) for i in range(1,4)]
        courier=unit('uske',5,owner=0,x=500);b.tavern_mission={'courier':courier.handle}
        self.assertFalse(b.pre_attack_retreat(a+[courier],[unit('uzig',9,x=900)],10))
    def test_shield_carrier_receives_safety_move_during_base_retreat(self):
        b,orders,_=self.bot();a=[unit('ucry',1,owner=0)]
        b.shield_moves={a[0].handle:(-500,300)}
        self.assertTrue(b.pre_attack_retreat(a,[unit('uzig',9,x=800)],10))
        self.assertEqual(orders,[('move',a[0].handle,(-500,300))])
    def test_enemy_door_camp_and_crossing_route_excluded_but_escape_allowed(self):
        c=Creeping(lambda *a,**kw:None,camps=[]);c.enemy_structures=[unit('uzig',9,x=3424)]
        c.enemy_structures[0].y=3616
        g=N(dist=dist,walk_path=lambda a,b:[b])
        self.assertFalse(c.safe_route(g,(0,0),(2878.6,4444.3)))
        self.assertFalse(c.safe_route(g,(1000,3616),(6000,3616)))
        self.assertTrue(c.safe_route(g,(2726,3602),(0,0)))
        self.assertTrue(c.safe_route(g,(0,0),(-2000,0)))
    def test_full_tick_upgrade_then_incursion_then_ready_assault(self):
        b,orders,events=self.bot();a=[unit(c,i,owner=0) for i,c in enumerate(['Udea','Ulic','Nbrn','ucry','ucry'],1)]
        for u in a:u.mana=0;u.mana_max=300;u.hp=u.hp_max=600
        tower=unit('uzig',80,x=800);own=a+[b.home];foes=[tower];busy=[True];clock=[500]
        g=b.g;g.snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own+foes)
        g.my_buildings=lambda *args:[b.home];g.my_heroes=lambda:[u for u in a if u.is_hero]
        g.map=lambda:N(starts=[],walkable=lambda *p:True);g.units=lambda side,codes:[u for u in a if u.type in codes]
        g.enemies=lambda:foes;g.creeps=lambda:[];g.my_units=lambda:own
        g.inventory=lambda u:['ocor','stwp'];g.cooldown=lambda *args:1
        g.resources=lambda:dict(gold=1000,lumber=500,food_cap=70,food_used=40)
        g.production=lambda u:N(kind='upgrade') if busy[0] else None
        b.economy.tick=lambda *a:None;b.scout=lambda *a:None;b.skills=lambda *a:None;b.items=lambda *a:None
        b.combat_spells=lambda *a:None;b.loot.tick=lambda *a:None;b.equipment.tick=lambda *a:False
        b.prepare_attack=lambda *a:True;b.creep=lambda *a:self.fail('must withdraw before creeping')
        advanced=[];b.advance_attack=lambda *a:advanced.append(True)
        b.tick(forced=Action.ATTACK)
        self.assertEqual(b.situation.tier,2);self.assertEqual(b.action,Action.RETREAT)
        self.assertFalse(advanced);self.assertTrue(any(r[0]=='move' for r in orders))
        self.assertEqual([e['actual'] for e in events if e['event']=='decision'],['CREEP'])
        busy[0]=False;a[2].x=4000;clock[0]+=6;b.tick()
        self.assertEqual(b.action,Action.RETREAT);self.assertFalse(advanced)
        a[2].x=0;clock[0]+=6;b.tick()
        self.assertEqual(b.action,Action.ATTACK);self.assertTrue(advanced)
    def test_missing_third_hero_does_not_block_growth_but_low_gold_is_reserved(self):
        for gold in [3000,500]:
            g=GrowthGame();g.own=[u for u in g.own if u.type!='Nbrn'];g.gold=gold
            e=Economy(lambda *a,**kw:None);e.ever_heroes={'Udea','Ulic'};e.scout=(9999,0)
            e.tick(g,700)
            if gold==3000:self.assertEqual(g.commands,['ucry']);self.assertLess(g.gold,gold)
            else:self.assertFalse(g.commands);self.assertEqual(g.gold,gold)
