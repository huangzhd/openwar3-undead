import unittest
from types import SimpleNamespace as N
from undead.policy import Action, Situation, ScoutMemory, choose_rule
from undead.economy import Economy


def unit(code,handle=1,owner=1,x=0,visible=True,alive=True):
    return N(type=code,handle=(handle,0),owner=owner,x=x,y=0,hp=100,hp_max=100,
             level=1,is_hero=code[0].isupper(),alive=alive,visible_to=lambda me:visible)

class FairPolicyTests(unittest.TestCase):
    def test_hidden_movement_death_and_health_cannot_update_memory(self):
        m=ScoutMemory()
        m.update([unit('htow',x=2500)],10,0,lambda _:True)
        hidden=unit('htow',x=100,visible=False,alive=False)
        hidden.hp=1
        m.update([hidden],20,0,lambda _:True)
        remembered=m.expansions((0,0),20)
        self.assertEqual([(u.x,u.hp,u.at) for u in remembered],[(2500,100,10)])
        m.update([],131,0,lambda _:True)
        self.assertTrue(m.units) # buildings persist until their site is actually revisited
        self.assertFalse(m.clear_visible_empty_sites([],lambda *p:False,lambda u:True))
        self.assertEqual(len(m.clear_visible_empty_sites([],lambda *p:True,lambda u:True)),1)
        self.assertFalse(m.units)

    def test_expansion_requires_sighted_hall_not_militia_or_main(self):
        m=ScoutMemory()
        m.update([unit('hmil',1,x=2500),unit('htow',2,x=100),unit('htow',3,x=2500,visible=False)],10,0,lambda _:True)
        self.assertFalse(m.expansions((0,0),10))
        m.update([unit('htow',3,x=2500)],11,0,lambda _:True)
        self.assertEqual(len(m.expansions((0,0),11)),1)
        self.assertFalse(m.expansions((0,0),72))

    def test_tactical_priorities_follow_evidence_and_safety(self):
        s=Situation(100,army_hp=2000)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.expansion=True
        self.assertEqual(choose_rule(s),Action.HARASS)
        s.threatened=True
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.hero_health=.2
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.local_enemy_hp=4000
        self.assertEqual(choose_rule(s),Action.RETREAT)

    def test_push_requires_composition_or_late_game_army(self):
        s=Situation(400,tier=3,lich=True,orb=True,third_hero=True,statues=2,fiends=5)
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.orb=False
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.now=1000
        self.assertEqual(choose_rule(s),Action.CREEP) # no orb, still pre-attack phase
        s.orb=True
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.local_enemy_hp=5000
        self.assertEqual(choose_rule(s),Action.RETREAT)

class FakeGame:
    def __init__(self,tier=1,gold=100):
        codes=['unpl','uaod','uzig','usep','utom','ugrv','ugol','Udea']+['uaco']*6+['ugho']*3+['ucry']
        codes[0]={1:'unpl',2:'unp1',3:'unp2'}[tier]
        self.own=[unit(c,i,owner=0) for i,c in enumerate(codes)]
        self.gold=gold
        self.commands=[]
        self.busy={}
    def my_buildings(self,types=None):
        return [u for u in self.own if u.type in {'unpl','unp1','unp2','uaod','uzig','usep','utom','ugrv','ugol','uslh'} and (types is None or u.type in types)]
    def my_heroes(self): return [u for u in self.own if u.is_hero]
    def units(self,owner,types): return [u for u in self.own if u.type in types]
    def production(self,u): return self.busy.get(u.handle)
    def all_production(self,owner): return [(u,self.busy[u.handle]) for u in self.own if u.handle in self.busy]
    def idle_workers(self): return []
    def gold_mines(self): return []
    def nearest(self,units,point): return units[0] if units else None
    def order_of(self,u): return 1
    def resources(self): return dict(gold=self.gold,lumber=500,food_cap=50,food_used=20)
    def me(self): return 0
    def can_do(self,b,code): return 0 if self.gold>= {'unp1':320,'unp2':325,'Ulic':425,'ucry':215}.get(code,100) else 8
    def train(self,b,code):
        self.commands.append(code)
        return N(reason='accepted')
    def inventory(self,u): return ['rnec']+[None]*5 if u.type=='Udea' else [None]*6

class EconomyTests(unittest.TestCase):
    def test_first_fiend_saves_for_tier_two_instead_of_spending_on_second(self):
        g=FakeGame(gold=250)
        e=Economy(lambda *a,**k:None)
        e.tick(g,100)
        self.assertFalse(g.commands)
        g.gold=320
        e.tick(g,103)
        self.assertEqual(g.commands,['unp1'])

    def test_tier_two_reserves_lich_before_extra_fiends(self):
        g=FakeGame(tier=2,gold=300)
        e=Economy(lambda *a,**k:None)
        e.tick(g,200)
        self.assertFalse(g.commands)
        g.gold=425
        e.tick(g,203)
        self.assertEqual(g.commands,['Ulic'])

    def test_new_match_resets_hero_and_scout_state(self):
        first=Economy(lambda *a,**k:None)
        first.tick(FakeGame(),100)
        second=Economy(lambda *a,**k:None)
        self.assertIsNone(second.scout)
        self.assertFalse(second.ever_heroes)
        self.assertFalse(second.complete)

class CreepCommitmentTests(unittest.TestCase):
    def test_discovered_camp_is_not_forgotten_when_it_leaves_sight(self):
        from undead.controller import Controller
        from math import hypot
        g=N()
        g.units=lambda *a:[]
        g.dist=lambda a,b:hypot((a.x if hasattr(a,'x') else a[0])-(b.x if hasattr(b,'x') else b[0]),
                                (a.y if hasattr(a,'y') else a[1])-(b.y if hasattr(b,'y') else b[1]))
        g.path_distance=g.dist
        g.visible=lambda *p:True
        g.creep_camps=lambda:[dict(x=1500,y=0,hp=50,max_level=1)]
        g.creeps=lambda:[]
        g.map=lambda:None
        bot=Controller(g,lambda *a,**k:None)
        bot.home=N(x=0,y=0)
        moves=[]
        bot.go=lambda army,point,now,attack=False:moves.append(point)
        army=[unit('ucry',owner=0)]
        bot.creep(army,(0,0),10)
        g.creep_camps=lambda:[]
        bot.creep(army,(100,0),11)
        self.assertEqual(moves,[(1500,0),(1500,0)])
        bot.creep(army,(1500,0),20)
        self.assertIsNone(bot.camp_goal)

if __name__=='__main__': unittest.main()
