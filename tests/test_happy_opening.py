import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N

from review_opening_timing import reference_orders
from undead.policy import Action, ScoutMemory, Situation, choose_rule
from undead.replay_opening import HAPPY_LR, LR_NE_HOME, LR_SW_HOME


class HappyOpeningTests(unittest.TestCase):
    def test_both_templates_match_one_same_side_replay_each(self):
        evidence=Path(__file__).resolve().parents[1]/'docs/evidence'
        for side,file,tech in [(LR_SW_HOME,'happy-lr','happy-lr-progression'),
                               (LR_NE_HOME,'happy-lr-second','happy-lr-second')]:
            buildings=json.loads((evidence/(file+'-20261103.json')).read_bytes())
            orders=buildings.get('opening_build_orders',buildings.get('orders'))
            timeline=json.loads((evidence/(tech+'-20261103.json')).read_bytes())['orders']
            for code,(ms,point) in HAPPY_LR[side].items():
                row=next(r for r in orders+timeline if r['code']==code)
                self.assertEqual(ms,row.get('ms',row.get('timeslot_ms')))
                if point:self.assertEqual(list(point),row['point'])

    def test_missing_rejected_and_late_receipts_cannot_pass(self):
        rows=[dict(event='reference_opening',home=LR_SW_HOME)]
        for code,(ms,_) in HAPPY_LR[LR_SW_HOME].items():
            rows.append(dict(event='reference_order',code=code,target_ms=ms,clock=ms/1000-1,
                             after=ms/1000+1,accepted=True))
        self.assertTrue(reference_orders(rows)['all_within_one_second'])
        rows[2]['after']+=.001
        rows[3]['accepted']=False
        result=reference_orders(rows[:-1])
        self.assertFalse(result['all_within_one_second'])
        self.assertFalse(result['orders']['uzig']['within_one_second'])
        self.assertIsNone(result['orders']['usep']['signed_window_ms'])
        self.assertIsNone(result['orders']['ugrv']['signed_window_ms'])

    def test_southwest_shop_uses_rule_tower_layout_on_happy_clock(self):
        import test_foundation_owner_01124 as foundation
        for visible in (False,True):
            wanted=(-4416,-3776)
            layout,g,home,worker,buildings,_,orders,_,_=foundation.FoundationTests().scene()
            layout.map_alias='LR'
            layout.opening_profile=HAPPY_LR[LR_SW_HOME]
            buildings.append(N(type='uzig',x=-4256,y=-4064,handle=(3,4)))
            g.trees=lambda *a,**kw:[N(x=-4480,y=-3520)]
            g.visible=lambda x,y:visible
            g.can_afford=lambda c:True
            g.build=lambda w,c,x,y:orders.append((x,y)) or True
            g.snapshot=lambda max_age:N(clock=55.4,epoch=1)
            self.assertEqual(layout.build(g,worker,'utom',home,55.4),wanted)
            self.assertEqual(orders,[wanted])

    def test_shop_can_move_past_both_previously_tried_sites(self):
        import test_foundation_owner_01124 as foundation
        layout,g,home,w,buildings,_,orders,_,_=foundation.FoundationTests().scene()
        layout.map_alias='LR';layout.opening_profile=HAPPY_LR[LR_SW_HOME]
        buildings.append(N(type='uzig',x=-4256,y=-3936,handle=(3,4)))
        trees=[N(x=-4480,y=-3520),N(x=-4110,y=-3450)]
        g.trees=lambda *a,**kw:trees
        g.visible=lambda x,y:True
        g.can_afford=lambda c:True
        g.build=lambda w,c,x,y:orders.append((x,y)) or True
        g.snapshot=lambda max_age:N(clock=55.4,epoch=1)
        for i in range(6):
            spot=layout.build(g,w,'utom',home,55.4+i)
            if spot:break
        self.assertEqual(orders,[spot])
        self.assertTrue(all(max(abs(spot[0]-t.x),abs(spot[1]-t.y))>=256 for t in trees))
        self.assertLessEqual((spot[0]+4416)**2+(spot[1]+3776)**2,384**2)

    def test_fresh_scouting_changes_strategy_and_defense_takes_priority(self):
        s=Situation(600,tier=3,lich=True,orb=True,third_hero=True,scouted_attack_target=False)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.exposed_worker=True
        self.assertEqual(choose_rule(s),Action.HARASS)
        s.scouted_attack_target=True
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.threatened=True
        self.assertEqual(choose_rule(s),Action.DEFEND)
        memory=ScoutMemory()
        memory.units={i:N(type='hgtw',at=100,x=i*100,y=100) for i in (1,2)}
        self.assertTrue(memory.guarded(N(x=0,y=0),120))
        self.assertFalse(memory.guarded(N(x=0,y=0),161))

    def test_sixth_acolyte_can_be_queued_before_shop_at_worker_cost(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        g=GrowthGame()
        g.own=[unit(c,i+1,owner=0) for i,c in enumerate(['unpl','uaod','uzig','usep','ugol']+['uaco']*5)]
        g.gold,g.lumber,g.food,g.cap=75,50,7,20
        e=Economy(lambda *a,**kw:None)
        e.home_layout.opening_profile=HAPPY_LR[LR_SW_HOME]
        e.home_layout.opening_issued.update(('uaod','uzig','usep'))
        e.tick(g,40)
        self.assertEqual(g.commands,['uaco'])
        self.assertEqual(e.count(g,'uaco'),6)

    def test_training_hall_rallies_to_owned_mine_object_once_per_binding(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        g=GrowthGame()
        home=unit('unpl',1,owner=0)
        mine=unit('ugol',2,owner=0,x=500)
        enemy=unit('ugol',3,owner=1,x=10)
        g.own=[home,mine]
        g.gold_mines=lambda:[enemy,g.neutral,mine]
        calls=[]
        g.rally=lambda source,*,target:calls.append((source,target)) or True
        economy=Economy(lambda *a,**kw:None)
        g.busy[home.handle]=N(kind='queue',queue=['uaco'])
        economy.tick(g,6)
        economy.tick(g,7)
        self.assertEqual(calls,[(home,mine)])
        mine=unit('ugol',4,owner=0,x=600)
        g.own=[home,mine]
        economy.tick(g,8)
        self.assertEqual(calls[-1],(home,mine))
        self.assertEqual(len(calls),2)

    def test_missing_assigned_worker_does_not_divert_a_miner_and_rebuild_can_use_one(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        g=GrowthGame();home=unit('unpl',1,owner=0);home.x,home.y=LR_SW_HOME
        workers=[unit('uaco',n,owner=0,x=home.x) for n in range(2,8)]
        for w in workers:w.y=home.y
        g.own=[home,*workers[:4]]
        e=Economy(lambda *a,**kw:None)
        e.home_layout.map_alias='LR';e.home_layout.opening_profile=HAPPY_LR[LR_SW_HOME]
        e.opening_workers=[w.handle for w in workers[:4]];e.altar_worker=workers[2].handle
        g.snapshot=lambda **kw:N(clock=40,epoch=1)
        self.assertFalse(e.build(g,'usep',home,40))
        e.home_layout.pending['uaod']=dict(worker=e.altar_worker)
        self.assertFalse(e.build(g,'uzig',home,40))
        g.own.append(workers[4]);e.opening_workers.append(workers[4].handle)
        self.assertTrue(e.build(g,'usep',home,40))
        self.assertEqual(g.builds[-1][0],workers[4].handle)
        e.home_layout.pending.clear();e.home_layout.opening_foundations.add('usep')
        e.scout=workers[4].handle
        self.assertTrue(e.build(g,'usep',home,45))
        self.assertNotEqual(g.builds[-1][0],e.scout)

    def test_graveyard_uses_available_home_miner_as_soon_as_affordable(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        g=GrowthGame();home=unit('unpl',1,owner=0);home.x,home.y=LR_SW_HOME
        workers=[unit('uaco',n,owner=0,x=home.x) for n in range(2,8)]
        for w in workers:w.y=home.y
        g.own=[home,*workers];g.costs['ugrv']=(215,0)
        g.snapshot=lambda **kw:N(clock=69,epoch=1)
        e=Economy(lambda *a,**kw:None);e.home_layout.map_alias='LR'
        e.home_layout.opening_profile=HAPPY_LR[LR_SW_HOME];e.opening_workers=[w.handle for w in workers]
        e.scout=workers[-1].handle
        g.gold=214;self.assertFalse(e.build(g,'ugrv',home,68))
        g.gold=215;self.assertTrue(e.build(g,'ugrv',home,69))
        self.assertIn(g.builds[-1][0],e.opening_workers[:5])

    def test_return_to_gold_is_appended_once_to_the_designated_builders_order(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        for code,index in [('uzig',2),('usep',4),('utom',5)]:
            g=GrowthGame();home=unit('unpl',1,owner=0);home.x,home.y=LR_SW_HOME
            workers=[unit('uaco',i,owner=0,x=home.x) for i in range(2,8)]
            mine=unit('ugol',8,owner=0,x=-4608);mine.y=-4288
            g.own=[home,mine,*workers];g.snapshot=lambda **kw:N(clock=65,epoch=1)
            orders=[]
            g.build=lambda w,c,x,y:orders.append(('build',w.handle,c)) or True
            g.gather=lambda w,m,queue=None:orders.append((queue,w.handle,m.handle)) or True
            e=Economy(lambda *a,**kw:None);e.home_layout.map_alias='LR'
            e.home_layout.opening_profile=HAPPY_LR[LR_SW_HOME];e.opening_workers=[w.handle for w in workers]
            self.assertTrue(e.build(g,code,home,65))
            self.assertTrue(e.build(g,code,home,66))
            h=workers[index].handle
            self.assertEqual(orders,[('build',h,code)]+([] if code=='utom' else [('after',h,mine.handle)]))

    def test_fifth_worker_can_join_queue_only_after_opening_builds_are_paid(self):
        from test_growth_expansion_0149 import GrowthGame
        from test_baseline import unit
        from undead.economy import Economy
        g=GrowthGame();hall=unit('unpl',1,owner=0);hall.x,hall.y=LR_SW_HOME
        g.own=[hall,unit('uaod',2,owner=0)]+[unit('uaco',i,owner=0) for i in (3,4,5)]
        g.gold,g.food,g.cap=115,6,10
        g.busy[hall.handle]=N(kind='queue',queue=['uaco'])
        e=Economy(lambda *a,**kw:None);e.home_layout.opening_profile=HAPPY_LR[LR_SW_HOME]
        self.assertFalse(e.train(g,hall,'uaco',12))
        g.own.append(unit('uzig',6,owner=0))
        self.assertFalse(e.train(g,hall,'uaco',10))
        self.assertTrue(e.train(g,hall,'uaco',12))
        self.assertFalse(e.train(g,hall,'uaco',15))
        self.assertEqual(g.commands,['uaco'])

    def test_known_defenders_can_delay_assault_and_stale_base_cannot_start_it(self):
        hall=N(type='htow',owner=2,at=20,x=50,y=0,building=True,hp=1500)
        guard=N(type='hfoo',owner=2,at=30,x=50,y=20,building=False,hp=420)
        memory=ScoutMemory()
        memory.units={(1,2):hall,(3,4):guard}
        center=(0,0)
        self.assertIsNone(memory.scouted_human_objective(center,35,400))
        self.assertIs(memory.scouted_human_objective(center,35,800),hall)
        self.assertIsNone(memory.scouted_human_objective(center,81,800))
