import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_scout_opening as opening
from test_baseline import FakeGame
from undead.controller import Controller
from undead.creeping import Creeping
from undead.formation import Formation,distance
from undead.policy import Action

class TempoTests(unittest.TestCase):
    def opening(self,x=-2112,y=4608):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        dk.x=x;dk.y=y;b.home=N(x=x,y=y);b.opening_rod_finished=True
        army=[dk]
        for i in (80,81):
            u=unit('uske',i,x,180);u.hp_max=180;u.y=y;u.owner=0;u.alive=True
            all_units.append(u);army.append(u)
        catalog=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['TR']
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in catalog['starts']])
        b.creeping=Creeping(b.log,catalog['camps'])
        return b,g,army,orders

    def test_first_skeletons_depart_for_actual_411_at_each_tr_start_without_fiends(self):
        for x,y,expected in [(-2112,4608,'tr-9'),(5376,-2112,'tr-17'),(2624,-5248,'tr-12'),(-5248,1600,'tr-4')]:
            with self.subTest(start=(x,y)):
                b,g,army,orders=self.opening(x,y)
                b.creep(army,(x,y),198.355)
                self.assertEqual(b.creeping.active['id'],expected)
                point=(b.creeping.active['x'],b.creeping.active['y'])
                self.assertIn(('move',[u.handle for u in army],point),orders)
                self.assertFalse(any(o[0]=='move' and o[2]==(x,y) for o in orders))

    def test_small_turtle_stays_active_after_skeleton_loss_but_low_health_still_retires(self):
        b,g,army,orders=self.opening();b.creep(army,(-2112,4608),198)
        c=b.creeping;point=(c.active['x'],c.active['y'])
        foe=unit('ntrt',100,point[0],200);foe.y=point[1];g.creeps=lambda:[foe]
        self.assertEqual(c.choose(g,army[:1],point,b.home,200)[0],point)
        army[0].hp=100
        self.assertIsNone(c.choose(g,army[:1],point,b.home,201)[0])
        self.assertIn('tr-9',c.deferred)

    def test_larger_turtles_and_poison_still_require_support(self):
        b,g,army,_=self.opening();army.extend(unit('ucry',i,0,600) for i in range(10,20))
        base=next(c for c in b.creeping.catalog if c['id']=='tr-9')
        large=dict(base,id='large',spawns=[dict(level=4)]*3,difficulty=12,hp=2000)
        poison=dict(base,id='poison',poison_units=1)
        b.creeping.catalog=[large,poison]
        self.assertEqual(b.creeping.candidates(g,army,b.home,300),[])
        b.creeping.tier=2;army.append(unit('uobs',30,0,600))
        self.assertEqual({c['id'] for c in b.creeping.candidates(g,army,b.home,301)},{'large','poison'})

    def test_uncontested_clear_immediately_selects_next_even_tier_two_without_orb(self):
        b,g,army,orders=self.opening(-2000,0);g.map=lambda:N(starts=[])
        b.creeping.catalog=[dict(id='a',kind='ogre',x=-500,y=0,max_level=3,hp=800,difficulty=6),
                            dict(id='b',kind='ogre',x=3500,y=0,max_level=3,hp=800,difficulty=6)]
        b.creeping.tier=2
        b.creep(army,(-2000,0),300)
        self.assertEqual(b.creeping.active['id'],'a')
        orders.clear();b.creep(army,(-500,0),302)
        self.assertIn('a',b.creeping.cleared);self.assertEqual(b.creeping.active['id'],'b')
        self.assertIn(('move',[u.handle for u in army],(3500,0)),orders)
        self.assertFalse(any(o[0]=='move' and o[2]==(-2000,0) for o in orders))

    def test_no_eligible_camp_waits_in_field_when_healthy_but_recovers_when_injured(self):
        b,g,army,orders=self.opening();b.creeping.cleared={c['id'] for c in b.creeping.catalog}
        center=(-375,3066);b.creep(army,center,300)
        self.assertEqual(orders[-1][2],center)
        for u in army:u.hp=u.hp_max*.4
        orders.clear();b.creep(army,center,302)
        self.assertEqual(orders[-1][2],(b.home.x,b.home.y))

    def test_new_fiend_joins_dk_skeletons_without_reversing_front(self):
        b,g,army,_=self.opening(0,0);f=Formation(lambda *a,**k:None)
        f.plan(army,(2000,0),1,distance,lambda a,b:[b])
        recruit=unit('ucry',4,-2500)
        orders=f.plan([*army,recruit],(2000,0),3,distance,lambda a,b:[b])
        self.assertNotEqual(f.stage,'regroup')
        self.assertEqual(next(p for u,p,hold in orders if u is recruit),f.anchor)
        self.assertGreater(next(p[0] for u,p,hold in orders if u is army[0]),army[0].x)

class RodTempoTests(unittest.TestCase):
    def make(self):
        g=FakeGame(gold=2000);g.dist=dist;dk=g.my_heroes()[0];dk.x=4000
        inv=['stwp']+[None]*5;g.inventory=lambda h:inv;g.creeps=lambda:[]
        buys=[];g.buy=lambda shop,code:buys.append(code) or N(reason='accepted')
        b=Controller(g,lambda *a,**k:None);b.home=g.my_buildings({'unpl'})[0]
        b.ever_rod=True;b.action=Action.CREEP;b.restock_scrolls=lambda *a:None
        b.bank_supply_jobs=lambda *a:[];b.maintain_skeletons=lambda *a:False
        return b,g,dk,inv,buys

    def test_empty_rod_returns_from_field_then_observed_purchase_releases_shopping(self):
        b,g,dk,inv,buys=self.make();b.items(300,2)
        self.assertEqual(b.shop_goal,(0,0));self.assertFalse(buys)
        dk.x=0;b.items(302,2);self.assertEqual(buys,['rnec'])
        inv[1]='rnec';b.shop_goal=None;b.items(304,2)
        self.assertIsNone(b.shop_goal);self.assertEqual(buys,['rnec'])

    def test_finish_neutral_fight_before_empty_rod_return(self):
        b,g,dk,inv,buys=self.make();foe=unit('ntrt',99,4050);g.creeps=lambda:[foe]
        b.items(300,2);self.assertIsNone(b.shop_goal)
        g.creeps=lambda:[];b.items(302,2);self.assertEqual(b.shop_goal,(0,0))

    def test_existing_rod_tier_three_threats_and_purchase_retry_do_not_recall_army(self):
        for reason in ('inventory','tier3','threat','player','retreat','retry','gold'):
            with self.subTest(reason=reason):
                b,g,dk,inv,buys=self.make();tier=2
                if reason=='inventory':inv[1]='rnec'
                elif reason=='tier3':tier=3
                elif reason=='threat':b.situation.threatened=True
                elif reason=='player':b.battle_enemies=[unit('ogru',100,4100)]
                elif reason=='retreat':b.action=Action.RETREAT
                elif reason=='retry':b.shop_retry_at[(dk.handle,'rnec')]=400
                elif reason=='gold':g.gold=100
                b.items(300,tier);self.assertIsNone(b.shop_goal);self.assertFalse(buys)
                if reason=='tier3':
                    b.items(302,2);self.assertIsNone(b.shop_goal)

if __name__=='__main__':unittest.main()
