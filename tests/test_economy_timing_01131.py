import unittest
from types import SimpleNamespace as N
from undead.home_layout import HomeLayout
from undead.economy import Economy
from test_baseline import unit
from test_growth_expansion_0149 import GrowthGame


class LayoutBudgetTests(unittest.TestCase):
    def game(self,trees,visible=True):
        home=N(type='unpl',x=2176,y=4224,handle=(1,1));calls=[];builds=[]
        g=N(my_buildings=lambda:[home],map=lambda:None,trees=lambda *a,**kw:trees,
            visible=lambda x,y:calls.append((x,y)) or visible,
            build_near=lambda w,c,x,y,**kw:builds.append((x,y)) or (x,y))
        return home,g,calls,builds

    def test_distant_trees_do_not_query_engine_before_building(self):
        home,g,calls,builds=self.game([N(x=10000+i,y=10000) for i in range(400)])
        self.assertIsNotNone(HomeLayout().build(g,None,'uaod',home,1))
        self.assertFalse(calls);self.assertEqual(len(builds),1)

    def test_dense_hidden_trees_are_bounded_and_do_not_block_next_tick(self):
        home,g,calls,builds=self.game([],False);layout=HomeLayout()
        first=next(layout.candidates('uaod',home,[home]))
        g.trees=lambda *a,**kw:[N(x=first[0]+i*.1,y=first[1]) for i in range(400)]
        self.assertIsNone(layout.build(g,None,'uaod',home,1))
        self.assertEqual(len(calls),16);self.assertFalse(builds)
        self.assertNotEqual(layout.cursors[('uaod',home.x,home.y)],0)

    def test_unknown_tree_visibility_is_not_treated_as_clear_ground(self):
        home,g,calls,builds=self.game([]);layout=HomeLayout()
        first=next(layout.candidates('uaod',home,[home]));g.trees=lambda *a,**kw:[N(x=first[0],y=first[1])]
        g.visible=lambda *a:None
        layout.build(g,None,'uaod',home,1)
        self.assertNotIn(first,builds)


class TransitionBudgetTests(unittest.TestCase):
    def game(self,tier=1):
        g=GrowthGame(fiends=4);g.own[0].type='unpl' if tier==1 else 'unp1'
        g.own=[u for u in g.own if u.type not in {'Ulic','Nbrn','uobs','uslh'}]
        fiends=g.units('me',{'ucry'})
        g.own=[u for u in g.own if u not in fiends[4:]]
        g.food=28;g.cap=40;g.gold=459;g.lumber=280
        g.costs.update(unp1=(320,210),unp2=(325,230),Ulic=(425,100),uslh=(140,135))
        e=Economy(lambda *a,**kw:None);e.opening_started=True;e.opening_complete=True;e.ever_heroes={'Udea'}
        return g,e

    def test_real_late_tier_two_sample_preserves_lich_and_slaughter_budget(self):
        g,e=self.game();g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp1'],progress=.97)
        e.tick(g,324.95)
        self.assertNotIn('ucry',g.commands);self.assertEqual(g.gold,459)
        g.own[0].type='unp1';g.busy.clear();e.tick(g,330.83)
        self.assertEqual(g.commands,['Ulic'])

    def test_early_upgrade_and_late_surplus_continue_reinforcements(self):
        for progress,gold,lumber in ((.2,459,280),(.97,800,300)):
            with self.subTest(progress=progress):
                g,e=self.game();g.gold=gold;g.lumber=lumber
                g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp1'],progress=progress)
                e.tick(g,240)
                self.assertIn('ucry',g.commands)

    def test_36_of_40_with_paid_lich_funds_tier_three_before_tower(self):
        g,e=self.game(2);g.food=36;g.gold=340;g.lumber=250
        g.busy[g.my_buildings({'uaod'})[0].handle]=N(kind='queue',queue=['Ulic'])
        slaughter=unit('uslh',900,owner=0);slaughter.hp=10;g.own.append(slaughter)
        g.busy[slaughter.handle]=N(kind='construction',queue=['uslh'])
        e.tick(g,400)
        self.assertEqual(g.commands,['unp2']);self.assertFalse(g.builds)

    def test_tight_food_still_builds_supply_during_tech_save(self):
        g,e=self.game(2);g.food=38;g.gold=340;g.lumber=250
        g.busy[g.my_buildings({'uaod'})[0].handle]=N(kind='queue',queue=['Ulic'])
        e.tick(g,400)
        self.assertEqual(g.builds[0][1],'uzig');self.assertNotIn('unp2',g.commands)

    def test_idle_worker_is_reused_instead_of_interrupting_a_miner(self):
        g,e=self.game();workers=g.units('me',{'uaco'});idle=workers[-1]
        g.order_of=lambda w:0 if w==idle else 852018
        e.build(g,'uzig',g.own[0],10)
        self.assertEqual(g.builds[0][0],idle.handle)

    def test_observed_foundation_releases_idle_worker_to_mine(self):
        g,e=self.game();w=g.units('me',{'uaco'})[0]
        foundation=unit('uzig',950,owner=0,x=512);g.own.append(foundation)
        e.home_layout.pending['uzig']=dict(worker=w.handle,point=(512,0),started=1,progress=1,gap=0,before=set())
        e.save_for_trade=True
        e.tick(g,15)
        self.assertIn(w.handle,[h for h,m in g.gathers]);self.assertFalse(e.home_layout.pending)


if __name__=='__main__':unittest.main()
