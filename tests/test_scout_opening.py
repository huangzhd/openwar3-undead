import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.creeping import Creeping
from undead.formation import Formation
from undead.policy import Situation

class ScoutCorpseTests(unittest.TestCase):
    def make(self):
        dk=unit('Udea',1,-2000,675);dk.hp_max=675
        scout=unit('uaco',2,-1100,220);scout.hp_max=220
        corpse=unit('nshe',3,-1000,0);corpse.hp_max=15
        own=[dk,scout];all_units=[*own,corpse];orders=[];events=[]
        for u in all_units:
            u.alive=u.hp>0;u.owner=15 if u is corpse else 0;u.visible_to=lambda me:True
        inv=['rnec'];cool=[0]
        g=N(me=lambda:0,unit=lambda h:next((u for u in all_units if u.handle==h),None),
            units=lambda owner,codes=None:[u for u in all_units if u.alive and (u.owner==0 if owner=='me' else (owner=='all' or u.owner==owner)) and (codes is None or u.type in codes)],
            nearest=lambda us,p:min(us,key=lambda u:dist(u,p)),dist=dist,path_distance=dist,
            walk_path=lambda a,b:[b],visible=lambda *p:True,inventory=lambda h:inv,
            cooldown=lambda *a:cool[0],use_item=lambda h,i:orders.append(('rod',h.handle)) or True,
            creeps=lambda:[],map=lambda:True,creep_camps=lambda:[])
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        b.home=N(x=-2000,y=0);b.enemy_main=(5000,0);b.economy.scout=scout.handle
        b.go=lambda us,p,t,**kw:orders.append(('move',[u.handle for u in us],p))
        b.fight=lambda us,foes,t:orders.append(('attack',[u.handle for u in us],[u.handle for u in foes]))
        b.scout_critter=corpse.handle
        return b,g,dk,corpse,own,all_units,orders,events,inv,cool

    def test_only_observed_death_creates_corpse_memory_and_scout_moves_on(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        all_units.remove(corpse);b.scout(100);self.assertIsNone(b.scout_corpse)
        all_units.append(corpse);corpse.visible_to=lambda me:False
        b.scout(101);self.assertIsNone(b.scout_corpse)
        corpse.visible_to=lambda me:True;b.scout(102)
        self.assertEqual(b.scout_corpse['point'],(-1000,0))
        self.assertEqual(orders[-1][2],b.enemy_main)

    def test_fair_kill_event_requires_scout_source_and_tracked_target(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        own[1].addr=123
        event=N(kind='killed',handle=corpse.handle,source_addr=456,x=-1000,y=0,clock=110)
        b.observe_events([event]);self.assertIsNone(b.scout_corpse)
        event.source_addr=123;b.observe_events([event])
        self.assertEqual(b.scout_corpse['clock'],110)
        all_units.remove(corpse)
        self.assertTrue(b.use_scout_corpse([dk],dk,141))
        self.assertEqual(orders[-1][2],(-1000,0))

    def test_approaches_after_rod_and_waits_for_real_two_skeletons(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        b.scout(100);inv.clear()
        self.assertTrue(b.use_scout_corpse([dk],dk,110));self.assertEqual(orders[-1][2],(-2000,0))
        inv.append('rnec');b.use_scout_corpse([dk],dk,141)
        self.assertEqual(orders[-1][2],(-1000,0))
        dk.x=-1200;b.use_scout_corpse([dk],dk,143)
        self.assertIn(('rod',dk.handle),orders);self.assertFalse(b.opening_rod_finished)
        self.assertGreater(b.cast_until[dk.handle],143)
        b.use_scout_corpse([dk],dk,144);self.assertEqual(sum(o[0]=='rod' for o in orders),1)
        for i in (4,5):
            u=unit('uske',i,-1100,180);u.hp_max=180;u.alive=True;u.owner=0;all_units.append(u)
        self.assertFalse(b.use_scout_corpse([dk],dk,145));self.assertTrue(b.opening_rod_finished)
        self.assertEqual(events[-1]['event'],'opening_skeletons_ready');self.assertEqual(events[-1]['fiends'],0)

    def test_three_accepted_but_ineffective_attempts_release_opening(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        b.scout(100);dk.x=-1200
        for t in (141,144,147):self.assertTrue(b.use_scout_corpse([dk],dk,t))
        self.assertFalse(b.use_scout_corpse([dk],dk,150))
        self.assertEqual(sum(o[0]=='rod' for o in orders),3)
        self.assertEqual(events[-1]['reason'],'attempt_limit')

    def test_unsafe_path_and_elapsed_budget_fall_back(self):
        for cause in ('unsafe','old','timeout'):
            with self.subTest(cause=cause):
                b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make();b.scout(100)
                now=141
                if cause=='unsafe':b.creeping.enemy_main=(-1000,0)
                elif cause=='old':now=186
                else:b.opening_rod_started=110
                self.assertFalse(b.use_scout_corpse([dk],dk,now))
                self.assertTrue(b.scout_corpse_abandoned);self.assertFalse(b.opening_rod_finished);self.assertFalse(any(o[0]=='rod' for o in orders))

    def test_cooldown_or_combat_does_not_cast(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make();b.scout(100);dk.x=-1200
        cool[0]=5;b.use_scout_corpse([dk],dk,141);self.assertFalse(any(o[0]=='rod' for o in orders))
        cool[0]=0;b.battle_enemies=[corpse]
        self.assertFalse(b.use_scout_corpse([dk],dk,142));self.assertFalse(any(o[0]=='rod' for o in orders))

    def test_dk_and_two_skeletons_choose_safe_gnoll_without_fiend(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        skels=[unit('uske',i,-2000,180) for i in (4,5)]
        for u in skels:u.hp_max=180
        camps=[dict(id='other',kind='ogre',x=-1950,y=0,max_level=3,hp=800,difficulty=5),
               dict(id='gnoll',kind='gnoll',x=-3000,y=0,max_level=3,hp=880,difficulty=5)]
        c=Creeping(lambda *a,**kw:None,camps);c.opening_gnoll=True
        goal,_=c.choose(g,[dk,*skels],(-2000,0),b.home,150)
        self.assertEqual(goal,(-3000,0))
        # Preference never bypasses safe-camp eligibility.
        c=Creeping(lambda *a,**kw:None,camps);c.opening_gnoll=True;dk.hp=150
        self.assertIsNone(c.choose(g,[dk,*skels],(-2000,0),b.home,150)[0])

    def test_first_fiend_catches_up_without_holding_dk_and_skeletons(self):
        dk=unit('Udea',1,0);skels=[unit('uske',i,0) for i in (2,3)]
        f=Formation(lambda *a,**kw:None);f.plan([dk,*skels],(1000,0),150,dist,lambda a,b:[b])
        spider=unit('ucry',4,-2000)
        orders=f.plan([dk,*skels,spider],(1000,0),214,dist,lambda a,b:[b])
        self.assertIn(spider.handle,f.joiners)
        self.assertTrue(all(not hold for u,p,hold in orders))
        self.assertTrue(any(u is spider and p[0]>spider.x for u,p,hold in orders))

    def test_dying_skeletons_do_not_trigger_five_endangered_portal(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=self.make()
        b.home=N(x=-6000,y=0);inv[:]=['stwp'];g.use_item=lambda *a,**kw:orders.append(('portal',)) or True
        b.situation=Situation(100,local_enemy_hp=1500,army_health=.8)
        foe=unit('hrif',20,dk.x+100,500);foe.owner=1;g.enemies=lambda:[foe];g.current_target=lambda u:None
        skels=[unit('uske',i,dk.x,20) for i in range(4,9)]
        for u in skels:u.hp_max=180
        self.assertFalse(b.emergency_portal([dk,*skels],100))
        for u in skels:u.type='ucry'
        self.assertTrue(b.emergency_portal([dk,*skels],101))
        self.assertEqual(orders,[('portal',)])

if __name__=='__main__':unittest.main()
