import unittest
from math import hypot
from types import SimpleNamespace as N
from human_opponents import HumanOpponent


class FakeGame:
    player=2
    buildings={'htow','hkee','hcas','halt','hbar','hbla','hlum','hhou','hwtw','hgtw'}
    def __init__(self):
        self.time=1;self.rows=[];self.orders=[];self.prods={};self.targets={}
        self.money=dict(gold=2000,lumber=1000,food_used=20,food_cap=60)
        self.add('htow',0,0);self.add('ngol',-500,0,owner=15)
        self.add('ngol',2200,0,owner=15)
        for i in range(10):self.add('hpea',i*20,0)
        self.visible_points=True;self.build_ok=True
    def add(self,code,x=0,y=0,owner=2):
        h=len(self.rows)+100
        u=N(type=code,x=x,y=y,handle=(h,1),addr=h,owner=owner,hp=500,hp_max=500,
            alive=True,is_hero=code=='Hamg',mana=300,has_detail=False,level=1,skill_points=0)
        u.visible_to=lambda p:owner==p or owner>=12 or self.visible_points
        self.rows.append(u);return u
    def me(self):return self.player
    def clock(self):return self.time
    def units(self,owner='all',types=None):
        return [u for u in self.rows if u.alive and (owner=='all' or owner=='me' and u.owner==self.player or owner=='creep' and u.owner==12)
                and (types is None or u.type in types)]
    def my_units(self):return self.units('me')
    def my_buildings(self,types=None):return [u for u in self.units('me',types) if u.type in self.buildings]
    def my_workers(self):return self.units('me',{'hpea'})
    def my_army(self):return [u for u in self.my_units() if u.type not in self.buildings|{'hpea'}]
    def my_heroes(self):return [u for u in self.my_units() if u.is_hero]
    def idle_workers(self):return [u for u in self.my_workers() if u.handle not in self.targets]
    def gold_mines(self):return self.units('all',{'ngol'})
    def enemies(self):return [u for u in self.rows if u.owner==1 and u.visible_to(self.player)]
    def is_building(self,u):return u.type in self.buildings
    def is_constructing(self,u):return self.targets.get(u.handle,('',))[0] in ('build','repair')
    def production(self,u):return self.prods.get(u.handle)
    def all_production(self,*args):return [(u,self.prods[u.handle]) for u in self.rows if u.handle in self.prods]
    def queue(self,u):return self.prods[u.handle].queue if u.handle in self.prods else []
    def resources(self):return self.money
    def can_afford(self,code):return self.money['gold']>=100 and self.money['lumber']>=50
    def can_do(self,u,code):return 0 if self.can_afford(code) else 8
    @staticmethod
    def dist(a,b):
        def xy(u):return u if isinstance(u,tuple) else (u.x,u.y)
        a,b=xy(a),xy(b);return hypot(a[0]-b[0],a[1]-b[1])
    def path_distance(self,a,b):return self.dist(a,b)
    def visible(self,*point):return self.visible_points
    def trees(self,*args,**kwargs):return [N(x=0,y=500)]
    def gather(self,w,target):self.orders.append(('gather',w.handle,target));self.targets[w.handle]=('gather',target);return True
    def repair(self,w,b):self.orders.append(('repair',w.handle,b));self.targets[w.handle]=('repair',b);return True
    def build_near(self,w,code,x,y,**kwargs):
        self.orders.append(('build',code,(x,y),w.handle))
        if not self.build_ok:return None
        self.targets[w.handle]=('build',code);return x+400,y
    def train(self,b,code):
        self.orders.append(('train',code,b.handle));self.prods[b.handle]=N(kind='queue',queue=[code]);return True
    def revive(self,b):self.orders.append(('revive',b.handle));return True
    def move(self,u,x,y):self.orders.append(('move',u.handle,(x,y)));return True
    def attack_move(self,u,x,y):self.orders.append(('attack_move',u.handle,(x,y)));return True
    def attack(self,u,e):self.orders.append(('attack',u.handle,e.handle));return True
    def current_target(self,u):return None
    def hero_info(self,u):return dict(skill_points=u.skill_points)
    def abilities(self,u):return []
    def inventory(self,u):return []
    def cooldown(self,*args):return None


CATALOG=dict(starts=[dict(slot=0,x=0,y=0),dict(slot=1,x=8000,y=0)],
             neutral_buildings=[dict(code='ngol',x=-500,y=0),dict(code='ngol',x=2200,y=0),dict(code='ngol',x=8500,y=0)],camps=[])


class HumanOpponentTests(unittest.TestCase):
    def setup_bot(self,profile,opening=True):
        g=FakeGame();logs=[];bot=HumanOpponent(g,lambda e,**d:logs.append((e,d)),profile,CATALOG)
        bot.home=(0,0);bot.workers={u.handle:(u,g.time) for u in g.my_workers()}
        if opening:
            for code in ('halt','hbar','Hamg','hfoo','hfoo','hfoo','hfoo'):g.add(code)
        return g,bot,logs

    def test_profiles_make_different_economic_commitments_from_same_state(self):
        g,bot,_=self.setup_bot('human-fast-expand');bot.economy(10,[])
        self.assertEqual(g.orders[0][0:3],('build','htow',(2200,0)))
        self.assertFalse(bot.expanded)
        g,bot,_=self.setup_bot('human-rifle');bot.economy(10,[])
        self.assertEqual(g.orders[0][0:3],('build','hbla',(0,0)))

    def test_expansion_requires_scouting_and_clear_guards_and_never_techs_early(self):
        for hidden,guard in ((True,False),(False,True)):
            g,bot,_=self.setup_bot('human-fast-expand');g.visible_points=not hidden
            if guard:g.add('nrog',2200,0,owner=12)
            bot.economy(10,[])
            self.assertFalse(g.orders)
            mode,goal=bot.destination(g.my_army(),[],10)
            self.assertEqual((mode,goal),('clear_expansion',(2200,0)))

    def test_expansion_not_confirmed_by_order_or_incomplete_foundation(self):
        g,bot,logs=self.setup_bot('human-fast-expand');bot.economy(10,[])
        hall=g.add('htow',2200,0);hall.hp=50
        g.prods[hall.handle]=N(kind='construction',queue=['htow'])
        bot.observe_build(11);bot.economy(12,[])
        self.assertFalse(bot.expanded)
        del g.prods[hall.handle];hall.hp=hall.hp_max;bot.economy(80,[])
        self.assertTrue(bot.expanded)
        self.assertTrue(any(e=='human_expansion_completed' and d['tier_one'] for e,d in logs))

    def test_failed_expansion_has_bounded_attempts_then_falls_back(self):
        g,bot,logs=self.setup_bot('human-fast-expand');g.build_ok=False
        for t in (10,20,30,40,50):bot.economy(t,[])
        self.assertEqual(sum(o[:2]==('build','htow') for o in g.orders),3)
        self.assertTrue(bot.expansion_abandoned)
        self.assertTrue(any(o[:2]==('build','hbla') for o in g.orders))

    def test_mining_workers_not_replaced_on_one_missing_frame_then_loss_recovered(self):
        g,bot,_=self.setup_bot('human-rifle')
        lost=g.my_workers()[0];g.rows.remove(lost)
        bot.labor(10,[]);bot.economy(10,[])
        self.assertFalse(any(o[:2]==('train','hpea') for o in g.orders))
        g.orders.clear();bot.labor(40,[]);bot.economy(40,[])
        self.assertTrue(any(o[:2]==('train','hpea') for o in g.orders))

    def test_labor_saturates_two_completed_mines_without_interrupting_active_workers(self):
        g,bot,_=self.setup_bot('human-fast-expand');g.add('htow',2200,0)
        bot.labor(10,[])
        mining=[o for o in g.orders if o[0]=='gather' and getattr(o[2],'type',None)=='ngol']
        self.assertEqual(sorted(sum(o[2].handle==m.handle for o in mining) for m in g.gold_mines()),[5,5])
        n=len(g.orders);bot.labor(14,[]);self.assertEqual(len(g.orders),n)

    def test_resumes_orphan_building_and_rebuilds_destroyed_altar(self):
        g,bot,_=self.setup_bot('human-rifle')
        bar=g.my_buildings({'hbar'})[0];bar.hp=50
        g.prods[bar.handle]=N(kind='construction',queue=['hbar'])
        bot.repair(10,[])
        self.assertTrue(any(o[0]=='repair' and o[2] is bar for o in g.orders))
        g.rows=[u for u in g.rows if u.type!='halt'];g.orders.clear()
        bot.economy(11,[])
        self.assertEqual(g.orders[0][:2],('build','halt'))

    def test_pending_build_keeps_worker_reserved_and_does_not_duplicate(self):
        g,bot,_=self.setup_bot('human-rifle');bot.economy(10,[])
        builder=bot.pending['worker'];bot.economy(15,[])
        self.assertEqual(sum(o[0]=='build' for o in g.orders),1)
        self.assertNotIn(builder,[w.handle for w in bot.available_workers()])
        bot.observe_build(46)
        self.assertIsNone(bot.pending)

    def test_rifle_requires_six_rifles_to_attack_and_defends_base_first(self):
        g,bot,_=self.setup_bot('human-rifle')
        for _ in range(5):g.add('hrif')
        self.assertEqual(bot.destination(g.my_army(),[],10)[0],'assemble')
        g.add('hrif');self.assertEqual(bot.destination(g.my_army(),[],20)[0],'search')
        enemy=g.add('ucry',500,0,owner=1)
        self.assertEqual(bot.destination(g.my_army(),[enemy],21),('defend',(500,0)))

    def test_low_hero_retreat_is_not_overwritten_by_attack(self):
        g,bot,_=self.setup_bot('human-rifle')
        h=g.my_heroes()[0];h.hp=100;h.x=500
        enemy=g.add('ucry',600,0,owner=1)
        bot.combat(10,[enemy])
        self.assertTrue(any(o[:2]==('move',h.handle) for o in g.orders))
        self.assertFalse(any(o[:2]==('attack',h.handle) for o in g.orders))

    def test_dead_hero_is_revived_not_trained_again(self):
        g,bot,_=self.setup_bot('human-rifle');bot.economy(10,[])
        g.rows=[u for u in g.rows if not u.is_hero];g.orders.clear()
        bot.economy(20,[])
        self.assertTrue(any(o[0]=='revive' for o in g.orders))
        self.assertFalse(any(o[:2]==('train','Hamg') for o in g.orders))

    def test_rifle_saves_for_second_barracks_then_tier_two(self):
        g,bot,_=self.setup_bot('human-rifle')
        for c in ('hbla','hlum','hrif','hrif','hrif','hrif'):g.add(c)
        bot.economy(10,[]);self.assertEqual(g.orders[0][:2],('build','hbar'))
        g.add('hbar');bot.observe_build(11);g.orders.clear();g.money['gold']=10
        bot.economy(20,[]);self.assertFalse(g.orders)
        g.money['gold']=1000;bot.economy(23,[])
        self.assertEqual(g.orders[0][:2],('train','hkee'))

    def test_real_tick_has_no_unrestricted_reads_and_logs_profile(self):
        for profile in ('human-fast-expand','human-rifle'):
            g,bot,logs=self.setup_bot(profile,opening=False)
            bot.tick()
            self.assertTrue(any(o[0]=='gather' for o in g.orders))
            self.assertTrue(any(e=='human_summary' and d['profile']==profile for e,d in logs))


if __name__=='__main__':unittest.main()
