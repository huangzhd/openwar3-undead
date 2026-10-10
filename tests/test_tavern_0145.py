import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.policy import Action

class TavernTests(unittest.TestCase):
    def setup_game(self,race=3):
        army=[unit('Udea',1,-2000),unit('Ulic',2,-2000)]+[unit('ucry',i,-1900-i*10) for i in range(3,7)]
        tavern=unit('ntav',90,0);shops=[tavern];moves=[];buys=[];events=[]
        resources=dict(gold=1000,lumber=500,food_cap=60,food_used=40)
        g=N(resources=lambda:resources,units=lambda side,codes:shops,dist=dist,path_distance=dist,walk_path=lambda a,b:[b],
            nearest=lambda units,u:min(units,key=lambda t:dist(u,t)),
            move=lambda u,x,y:moves.append((u.handle,(x,y))) or True,
            buy=lambda shop,code:buys.append(code) or N(reason=0))
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)),race)
        b.home=unit('unpl',100,-5000);b.situation.fiends=4;b.situation.statues=1
        return b,army,shops,moves,buys,events,resources

    def test_one_fiend_keeps_assignment_and_main_marches_elsewhere(self):
        b,a,s,m,buys,ev,res=self.setup_game()
        reserved=b.recruit_tavern(a,[],10,3,set());courier=b.tavern_mission['courier']
        self.assertEqual({h for h,p in m},{courier})
        b.formation.plan=lambda units,p,*args,**kw:[(u,p,False) for u in units]
        b.formation.stage='advance';b.go([u for u in a if u.handle not in reserved],(-4000,2000),10)
        self.assertTrue(all(p==(-4000,2000) for h,p in m if h!=courier))
        for u in a:
            if u.handle!=courier:u.x=100
        b.recruit_tavern(a,[],13,3,set())
        self.assertEqual(b.tavern_mission['courier'],courier)

    def test_accepted_hire_waits_for_hero_then_both_follow_moving_army(self):
        for race,code in [(3,'Nbrn'),(4,'Nngs')]:
            with self.subTest(race=race):
                b,a,s,m,buys,ev,res=self.setup_game(race)
                b.recruit_tavern(a,[],10,3,set());courier=next(u for u in a if u.handle==b.tavern_mission['courier']);courier.x=0
                b.recruit_tavern(a,[],20,3,set());self.assertEqual(buys,[code])
                b.recruit_tavern(a,[],22,3,set());self.assertIsNotNone(b.tavern_mission)
                hero=unit(code,50,0);a.append(hero);m.clear()
                reserved=b.recruit_tavern(a,[],23,3,set())
                self.assertIsNone(b.tavern_mission)
                self.assertEqual(reserved,{hero.handle,courier.handle})
                self.assertEqual({h for h,p in m},reserved)
                for u in a:
                    if u.handle not in reserved:u.x=-3500
                m.clear();b.recruit_tavern(a,[],26,3,set())
                self.assertTrue(all(p==(-3500,0) for h,p in m))
                hero.x=courier.x=-3400;b.recruit_tavern(a,[],29,3,set())
                self.assertFalse(b.tavern_joiners)
                self.assertEqual({e['type'] for e in ev if e['event']=='tavern_rejoined'},{code,'ucry'})

    def test_unseen_tavern_only_scouts_centre_then_updates_own_destination(self):
        b,a,s,m,buys,ev,res=self.setup_game();shop=s.pop()
        b.recruit_tavern(a,[],10,3,set());h=b.tavern_mission['courier']
        self.assertEqual(m[-1],(h,(0,0)));self.assertFalse(buys)
        shop.x=700;s.append(shop);b.recruit_tavern(a,[],13,3,set())
        self.assertEqual(m[-1],(h,(700,0)))
        self.assertEqual({who for who,p in m},{h})

    def test_threat_recall_and_pullback_cannot_be_overwritten(self):
        b,a,s,m,buys,ev,res=self.setup_game();b.recruit_tavern(a,[],10,3,set())
        h=b.tavern_mission['courier'];courier=next(u for u in a if u.handle==h);courier.x=0;m.clear()
        b.recruit_tavern(a,[unit('ogru',80,100)],13,3,{h})
        self.assertIsNone(b.tavern_mission);self.assertFalse(m);self.assertFalse(buys)
        self.assertIn(h,b.tavern_joiners)

    def test_no_hero_or_worker_substitute_for_missing_healthy_fiend(self):
        b,a,s,m,buys,ev,res=self.setup_game()
        for u in a:
            if u.type=='ucry':u.hp=100
        a.append(unit('uaco',60,0));a.append(unit('ugho',61,0))
        b.recruit_tavern(a,[],10,3,set())
        self.assertIsNone(b.tavern_mission);self.assertFalse(m);self.assertFalse(buys)

    def test_hire_attempts_bounded_and_no_receipt_only_success(self):
        b,a,s,m,buys,ev,res=self.setup_game();b.recruit_tavern(a,[],10,3,set())
        h=b.tavern_mission['courier'];next(u for u in a if u.handle==h).x=0
        for now in [20,29,38,47]:b.recruit_tavern(a,[],now,3,set())
        self.assertEqual(buys,['Nbrn']*3);self.assertIsNone(b.tavern_mission)
        self.assertFalse(any(e['event']=='tavern_hero_observed' for e in ev))

    def test_no_progress_recalled_and_dispatch_has_total_trip_limit(self):
        b,a,s,m,buys,ev,res=self.setup_game()
        for start in [10,70,130]:
            b.recruit_tavern(a,[],start,3,set());self.assertIsNotNone(b.tavern_mission)
            b.recruit_tavern(a,[],start+26,3,set());self.assertIsNone(b.tavern_mission)
        b.recruit_tavern(a,[],200,3,set());self.assertIsNone(b.tavern_mission)
        self.assertFalse(buys)

    def test_retreat_or_no_resources_or_no_path_prevents_dispatch(self):
        for reason in ['retreat','defend','resources','path']:
            b,a,s,m,buys,ev,res=self.setup_game()
            if reason=='retreat':b.action=Action.RETREAT
            if reason=='defend':b.action=Action.DEFEND
            if reason=='resources':res['gold']=424
            if reason=='path':b.g.path_distance=lambda *args:None
            b.recruit_tavern(a,[],10,3,set())
            self.assertIsNone(b.tavern_mission);self.assertFalse(m);self.assertFalse(buys)

    def test_courier_loss_releases_assignment_without_immediate_replacement(self):
        b,a,s,m,buys,ev,res=self.setup_game();b.recruit_tavern(a,[],10,3,set())
        h=b.tavern_mission['courier'];a[:]=[u for u in a if u.handle!=h];m.clear()
        b.recruit_tavern(a,[],13,3,set())
        self.assertIsNone(b.tavern_mission);self.assertFalse(b.tavern_joiners);self.assertFalse(m)

    def test_full_tick_recruit_does_not_redirect_main_army(self):
        b,a,shops,m,buys,ev,res=self.setup_game()
        home=unit('unp2',100,-5000);a.append(unit('uobs',101,-2000));own=[*a,home]
        for u in own:u.owner=0
        g=b.g
        g.snapshot=lambda **kw:N(clock=100,in_game=True,units=own)
        g.my_buildings=lambda *args:[home]
        g.map=lambda:N(starts=[],walkable=lambda *p:True)
        g.me=lambda:0;g.is_building=lambda u:u is home
        g.my_heroes=lambda:[u for u in a if u.is_hero]
        g.units=lambda side,codes:shops if codes=={'ntav'} else [u for u in a if u.type in codes]
        g.enemies=lambda:[];g.creeps=lambda:[];g.my_units=lambda:own
        g.current_target=lambda u:None;g.inventory=lambda u:['stwp','ocor'];g.cooldown=lambda *args:1
        g.attack_move=lambda u,x,y:m.append((u.handle,(x,y))) or True
        b.economy.tick=lambda *args:None;b.scout=lambda *args:None;b.skills=lambda *args:None;b.items=lambda *args:None
        b.loot.tick=lambda *args:None;b.equipment.tick=lambda *args:False;b.prepare_attack=lambda *args:True
        b.creep=lambda army,center,now:b.go(army,(-4000,2000),now)
        b.tick(forced=Action.ATTACK)
        self.assertEqual(b.action,Action.CREEP)
        self.assertEqual([row['actual'] for row in ev if row['event']=='decision'],['CREEP'])
        courier=b.tavern_mission['courier']
        self.assertEqual([p for h,p in m if h==courier],[(0,0)])
        for hero in [u for u in a if u.is_hero]:
            self.assertEqual([p for h,p in m if h==hero.handle],[(-4000,2000)])
