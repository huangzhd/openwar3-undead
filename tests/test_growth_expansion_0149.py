import unittest
from types import SimpleNamespace as N
from test_baseline import unit
from test_upgrades_portal import UpgradeGame
from test_micro_loot import dist
from undead.economy import Economy

class GrowthGame(UpgradeGame):
    def __init__(self,fiends=10):
        super().__init__();self.cap=100;self.food=62;self.levels={'Rura':3,'Rucr':3,'Ruwb':1}
        self.own += [unit('ucry',300+i,owner=0) for i in range(fiends-6)]
        self.neutral=unit('ngol',900,owner=15,x=3000);self.foes=[];self.neutrals=[]
        self.builds=[];self.moves=[];self.gathers=[];self.visible_site=True;self.route=True
        self.costs={'uaco':(75,0),'ucry':(215,40),'uobs':(200,35),'ugol':(255,220),'unpl':(255,0),'usep':(200,50),'uzig':(150,50)}
    def dist(self,a,b):return dist(a,b)
    def path_distance(self,a,b):return dist(a,b) if self.route else None
    def visible(self,*p):return self.visible_site
    def enemies(self):return self.foes
    def creeps(self):return self.neutrals
    def gold_mines(self):return [u for u in self.own if u.type=='ugol']+[self.neutral]
    def is_constructing(self,w):return False
    def idle_workers(self):return self.units('me',{'uaco'})
    def resources(self):return dict(gold=self.gold,lumber=self.lumber,food_cap=self.cap,food_used=self.food)
    def can_afford(self,c):
        gold,lumber=self.costs.get(c,(0,0));return self.gold>=gold and self.lumber>=lumber
    def can_do(self,b,c):return 0 if self.can_afford(c) and self.food+{'uaco':1,'ucry':3,'uobs':3}.get(c,0)<=self.cap else 8
    def train(self,b,c):
        r=super().train(b,c);gold,lumber=self.costs.get(c,(0,0));self.gold-=gold;self.lumber-=lumber
        self.food+={'uaco':1,'ucry':3,'uobs':3}.get(c,0);return r
    def build(self,w,c,x,y):self.builds.append((w.handle,c,x,y));return True
    def build_near(self,w,c,x,y,**kw):self.build(w,c,x+384,y);return (x+384,y)
    def move(self,w,x,y):self.moves.append((w.handle,x,y));return True
    def gather(self,w,m):self.gathers.append((w.handle,m.handle));return True
    def nearest(self,units,point):return min(units,key=lambda u:dist(u,point),default=None)

class GrowthExpansionTests(unittest.TestCase):
    def make(self,fiends=10):
        g=GrowthGame(fiends);events=[];e=Economy(lambda event,**kw:events.append(dict(event=event,**kw)))
        e.ever_heroes={h.type for h in g.my_heroes()};e.scout=(9999,0)
        e.expansion.safe_route=lambda a,b:g.route
        return g,e,events
    def enable_site(self,g,e):
        e.expansion.camps=[dict(id='clear',x=3000,y=0,kind='expansion')]
        e.expansion.observe(g)
    def step(self,g,e,t):return e.expansion.tick(g,e,g.my_buildings({'unp2'})[0],t)
    def foundation(self,g,code,handle,complete=False):
        b=unit(code,handle,owner=0,x=3000 if code=='ugol' else 3384);g.own.append(b)
        if not complete:b.hp=10;g.busy[b.handle]=N(kind='construction',queue=[])
        return b

    def test_surplus_at_six_or_ten_fiends_spends_before_fifteen_minutes(self):
        for n in [6,10]:
            g,e,_=self.make(n);e.tick(g,700)
            self.assertEqual(g.commands,['ucry']);self.assertLess(g.gold,3000)
    def test_fiend_and_statue_queues_run_concurrently(self):
        g,e,_=self.make(12);e.tick(g,700);e.tick(g,703)
        self.assertEqual(g.commands,['uobs','ucry'])
        self.assertEqual({b.type for b,p in g.all_production('me')},{'usep','uslh'})
    def test_supply_is_early_and_pending_foundation_prevents_duplicate(self):
        g,e,_=self.make();g.cap=70;e.tick(g,700)
        self.assertEqual([x[1] for x in g.builds],['uzig'])
        b=self.foundation(g,'uzig',800);e.tick(g,703)
        self.assertEqual([x[1] for x in g.builds],['uzig']);self.assertIn('ucry',g.commands)
    def test_busy_crypt_uses_second_crypt_and_no_more_than_two_are_built(self):
        g,e,_=self.make();e.tick(g,700);e.tick(g,703)
        self.assertEqual([x[1] for x in g.builds],['usep'])
        b=self.foundation(g,'usep',801,True);e.tick(g,706)
        self.assertEqual(g.busy[b.handle].queue,['ucry'])
        e.tick(g,709);self.assertEqual(len(g.builds),1)
    def test_full_army_keeps_worker_slots_and_does_not_overtrain_statues(self):
        g,e,_=self.make(20);g.own.append(unit('uobs',802,owner=0));g.food=95
        e.tick(g,700);self.assertFalse(g.commands)
        self.assertFalse(g.builds)
    def test_no_cleared_camp_or_unsafe_route_does_not_dispatch(self):
        g,e,_=self.make();e.expansion.observe(g);self.step(g,e,700)
        self.assertIsNone(e.expansion.point)
        self.enable_site(g,e);g.route=False;self.step(g,e,703)
        self.assertIsNone(e.expansion.point)
    def test_sixth_worker_is_trained_without_pulling_five_miners(self):
        g,e,_=self.make();g.own.remove(g.units('me',{'uaco'})[-1]);self.enable_site(g,e)
        self.step(g,e,700);self.assertEqual(g.commands,['uaco'])
        self.assertIsNone(e.expansion.builder);self.assertFalse(g.moves)
    def test_build_receipt_waits_for_real_foundations_and_completion_before_five_workers(self):
        g,e,events=self.make();self.enable_site(g,e);self.step(g,e,700)
        w=next(w for w in g.units('me',{'uaco'}) if w.handle==e.expansion.builder)
        self.assertEqual(len(g.moves),1);w.x=3000
        self.step(g,e,704);self.assertEqual(g.builds[-1][1],'ugol')
        self.step(g,e,706);self.assertEqual(len(g.builds),1);self.assertFalse(e.expansion.ready)
        mine=self.foundation(g,'ugol',810);self.step(g,e,710)
        self.assertEqual([x[1] for x in g.builds],['ugol','unpl'])
        hall=self.foundation(g,'unpl',811)
        e.expansion.upkeep(g,g.my_buildings({'unp2'})[0],720)
        self.assertFalse(e.expansion.ready);self.assertFalse(g.commands)
        for b in [mine,hall]:g.busy.pop(b.handle);b.hp=b.hp_max
        e.expansion.upkeep(g,g.my_buildings({'unp2'})[0],800);self.step(g,e,800)
        self.assertTrue(e.expansion.ready);self.assertEqual(g.commands,['uaco'])
        self.assertEqual(g.busy[hall.handle].queue,['uaco'])
        g.busy.pop(hall.handle);g.own += [unit('uaco',820+i,owner=0,x=3384) for i in range(4)]
        e.expansion.upkeep(g,g.my_buildings({'unp2'})[0],804)
        self.assertEqual(len(e.expansion.miners),5)
        self.assertTrue(all(m==mine.handle for w,m in g.gathers))
        self.step(g,e,804);self.assertEqual(g.commands,['uaco'])
    def test_builder_and_expansion_miners_are_not_reused_by_home_orders(self):
        g,e,_=self.make();self.enable_site(g,e);self.step(g,e,700);builder=e.expansion.builder
        e.tick(g,701);self.assertNotIn(builder,[w for w,m in g.gathers])
        e.build(g,'uzig',g.my_buildings({'unp2'})[0],705)
        self.assertNotEqual(g.builds[-1][0],builder)
    def test_danger_recalls_builder_and_retry_is_bounded(self):
        g,e,events=self.make();self.enable_site(g,e);self.step(g,e,700)
        g.foes=[unit('hfoo',899,x=3000)];self.step(g,e,704)
        self.assertIsNone(e.expansion.builder);self.assertEqual(g.moves[-1][1:],(0,0))
        g.foes=[];self.step(g,e,710);self.assertIsNone(e.expansion.builder)
        self.step(g,e,825);self.assertIsNotNone(e.expansion.builder)
        g.foes=[unit('hfoo',899,x=3000)];self.step(g,e,826);g.foes=[];self.step(g,e,1000)
        self.assertIsNone(e.expansion.builder);self.assertEqual(e.expansion.rounds,2)
    def test_unseen_or_enemy_occupied_mine_is_not_built(self):
        g,e,_=self.make();self.enable_site(g,e);self.step(g,e,700)
        w=next(w for w in g.units('me',{'uaco'}) if w.handle==e.expansion.builder);w.x=3000
        g.visible_site=False;self.step(g,e,704);self.assertFalse(g.builds)
        g.visible_site=True;g.foes=[unit('htow',898,x=3000)];self.step(g,e,707)
        self.assertFalse(g.builds);self.assertIsNone(e.expansion.builder)
    def test_home_identity_survives_new_hall_order_and_keeps_tier(self):
        g,e,_=self.make();e.tick(g,700);home=e.home_handle
        b=self.foundation(g,'unpl',888,True);g.own.remove(b);g.own.insert(0,b)
        e.tick(g,705);self.assertEqual(e.home_handle,home)
        self.assertNotIn('unp1',g.commands)

    def test_hall_build_walk_is_not_overwritten_by_return_to_mine(self):
        g,e,_=self.make();self.enable_site(g,e);self.step(g,e,700)
        w=next(w for w in g.units('me',{'uaco'}) if w.handle==e.expansion.builder)
        w.x=3000;self.foundation(g,'ugol',910);self.step(g,e,704)
        w.x=3600;before=len(g.moves);self.step(g,e,710)
        self.assertEqual(len(g.moves),before)
        self.assertEqual([x[1] for x in g.builds],['unpl'])
    def test_accepted_build_without_foundation_is_not_infinite_or_marked_complete(self):
        g,e,events=self.make();self.enable_site(g,e);self.step(g,e,700)
        w=next(w for w in g.units('me',{'uaco'}) if w.handle==e.expansion.builder);w.x=3000
        for t in [704,720,736,752]:self.step(g,e,t)
        self.assertEqual([x[1] for x in g.builds],['ugol']*3)
        self.assertIsNone(e.expansion.builder);self.assertFalse(e.expansion.ready)
        self.assertEqual(events[-1]['reason'],'foundation_not_observed')
    def test_worker_death_defers_instead_of_retasking_main_miners(self):
        g,e,events=self.make();self.enable_site(g,e);self.step(g,e,700)
        g.own=[u for u in g.own if u.handle!=e.expansion.builder]
        self.step(g,e,704);self.assertIsNone(e.expansion.builder)
        self.step(g,e,710);self.assertFalse(g.commands)
        self.assertEqual(len(g.units('me',{'uaco'})),5)
    def test_expansion_loss_releases_miners_for_home_recovery(self):
        g,e,events=self.make();self.enable_site(g,e);self.step(g,e,700)
        mine=self.foundation(g,'ugol',920,True);hall=self.foundation(g,'unpl',921,True)
        g.own += [unit('uaco',930+i,owner=0,x=3384) for i in range(4)]
        home=g.my_buildings({'unp2'})[0];e.expansion.upkeep(g,home,800)
        assigned=set(e.expansion.miners);self.assertEqual(len(assigned),5)
        g.own.remove(mine);e.expansion.upkeep(g,home,805)
        self.assertFalse(e.expansion.ready);self.assertFalse(e.expansion.miners)
        self.assertTrue(assigned.issubset({w for w,x,y in g.moves if x==home.x and y==home.y}))
