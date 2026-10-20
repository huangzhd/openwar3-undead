import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_creep_tempo_01101 as tempo
import test_ch_stage_01135 as stage
from test_micro_loot import unit
from undead.creeping import Creeping
from undead.policy import Situation, attack_ready, choose_rule, Action


class THRouteTests(unittest.TestCase):
    def scene(self,north=True,strong=False):
        x,y=(-3904,2880) if north else (2880,-3904)
        b,g,a,_=(stage.CHCenterTests().scene(x,y) if strong else tempo.TempoTests().opening(x,y))
        m=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['TH']
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in m['starts']])
        c=Creeping(b.log,m['camps']);b.creeping=c;c.map_alias='TH';c.home_only=True
        c.enemy_main=(2880,-3904) if north else (-3904,2880)
        g.walk_path=lambda a,z:[a,z]
        return b,g,a,c

    def test_first_summon_departs_for_42_at_both_spawns(self):
        for north,expected in ((True,'th-8'),(False,'th-14')):
            b,g,a,c=self.scene(north)
            b.creep(a,(b.home.x,b.home.y),145)
            self.assertEqual(c.active['id'],expected)
            point=(c.active['x'],c.active['y'])
            foe=unit('ntrt',999,point[0],300);foe.y=point[1];g.creeps=lambda:[foe]
            self.assertEqual(c.choose(g,a[:1],point,b.home,146)[0],point)
            a[0].hp=100
            self.assertEqual(c.choose(g,a[:1],point,b.home,147)[0],point) # 0.1.153: DK pulls individually; route stays committed.

    def test_turtle_needs_healthy_dk_and_two_skeletons_before_engagement(self):
        b,g,a,c=self.scene()
        self.assertFalse(c.candidates(g,a[:2],b.home,145))
        a[0].hp=.5*a[0].hp_max
        self.assertFalse(c.candidates(g,a,b.home,145))
        self.assertFalse(c.cleared)

    def test_mirrored_sequence_advances_only_on_visible_clear_without_revisits(self):
        for north,route in ((True,['th-8','th-1','th-2','th-10','th-9','th-6']),
                            (False,['th-14','th-12','th-19','th-20','th-9','th-16'])):
            b,g,a,c=self.scene(north,True);c.tier=3
            center=(b.home.x,b.home.y)
            for i,k in enumerate(route):
                now=500+i*2
                c.prepare_th_route(b.home,now,False)
                point,_=c.choose(g,a,center,b.home,now)
                self.assertEqual(c.active['id'],k)
                g.visible=lambda *args:False
                self.assertFalse(c.observe_clear(g,point,now,[]))
                self.assertNotIn(k,c.cleared)
                g.visible=lambda *args:True
                self.assertTrue(c.observe_clear(g,point,now+1,[]))
                self.assertNotIn(k,{x['id'] for x in c.candidates(g,a,b.home,now+1)})
                center=point
            self.assertFalse(c.prepare_th_route(b.home,520,False))
            self.assertIsNone(c.choose(g,a,center,b.home,520)[0])

    def test_home_321_fish_does_not_need_tier_two_lich_or_statue(self):
        for north,expected in ((True,'th-1'),(False,'th-12')):
            b,g,a,c=self.scene(north,True);c.tier=1
            a=[u for u in a if u.type not in {'Ulic','uobs'}]
            c.cleared.update(c.th_route(b.home)[:1])
            c.choose(g,a,(b.home.x,b.home.y),b.home,300)
            self.assertEqual(c.active['id'],expected)
            c.active=None;a[0].hp=.4*a[0].hp_max;c.th_contested=True
            self.assertFalse(c.candidates(g,a,b.home,301))

    def test_contested_shop_and_laboratory_keep_safety_checks(self):
        b,g,a,c=self.scene(True,True);c.tier=2;c.th_contested=True;c.home_only=False
        c.cleared.update(c.th_route(b.home)[:4])
        self.assertFalse(c.candidates(g,a[:1],b.home,400))
        self.assertEqual(c.candidates(g,a,b.home,400)[0]['id'],'th-9')
        c.cleared.add('th-9')
        self.assertFalse(c.candidates(g,[u for u in a if u.type!='uobs'],b.home,450))
        self.assertEqual(c.candidates(g,a,b.home,450)[0]['id'],'th-6')
        for u in a:u.hp*=.6
        self.assertFalse(c.candidates(g,a,b.home,451))

    def test_clear_laboratory_releases_attack_but_defense_and_retreat_remain_first(self):
        b,g,a,c=self.scene(True,True);c.tier=3
        c.cleared.update(c.th_route(b.home)[:-1])
        s=Situation(600,tier=3,dk=True,lich=True,orb=True,third_hero=True)
        s.pre_attack_camp_pending=c.prepare_th_route(b.home,600,False)
        self.assertEqual(choose_rule(s),Action.CREEP)
        s.threatened=True;self.assertEqual(choose_rule(s),Action.DEFEND)
        s.local_enemy_hp=2000;s.army_hp=500;self.assertEqual(choose_rule(s),Action.RETREAT)
        point,_=c.choose(g,a,(b.home.x,b.home.y),b.home,600)
        self.assertEqual(c.active['id'],'th-6')
        c.observe_clear(g,point,620,[])
        s.pre_attack_camp_pending=c.prepare_th_route(b.home,620,False)
        self.assertTrue(attack_ready(s))

    def test_path_failures_are_bounded_without_skipping_or_faking_clear(self):
        b,g,a,c=self.scene();g.path_distance=lambda *args:None
        for t in (145,240,340):self.assertIsNone(c.choose(g,a,(b.home.x,b.home.y),b.home,t)[0])
        self.assertIn('th-8',c.exhausted);self.assertFalse(c.cleared)
        self.assertTrue(c.prepare_th_route(b.home,1000,False))
        self.assertEqual(c.th_route_stage(b.home),'th-8')

    def test_controller_clear_moves_to_next_camp_after_required_rod_rebuy(self):
        for north in (True,False):
            b,g,a,c=self.scene(north,True);c.tier=3
            b.ni_rod_stop.done=True # The explicit second-camp purchase is covered separately.
            route=c.th_route(b.home);g.creeps=lambda:[];g.visible=lambda *p:True
            moves=[];b.go=lambda army,point,now,attack=False:moves.append(point)
            for i,k in enumerate(route[:-1]):
                c.active=next(p for p in c.catalog if p['id']==k)
                center=(c.active['x'],c.active['y']);moves.clear()
                b.creep(a,center,200+i*30)
                self.assertEqual(c.active['id'],route[i+1])
                self.assertIn((c.active['x'],c.active['y']),moves)
                self.assertNotIn((b.home.x,b.home.y),moves)

    def test_weak_healthy_army_continues_instead_of_staging_or_returning_home(self):
        b,g,a,c=self.scene();c.cleared.add('th-8')
        center=(-590,2491);moves=[]
        for u in a:u.x=center[0];u.y=center[1]
        b.go=lambda army,point,now,attack=False:moves.append(point)
        b.creep(a,center,245)
        self.assertEqual(c.active['id'],'th-1')
        self.assertEqual(moves,[(c.active['x'],c.active['y'])])
        self.assertNotIn((b.home.x,b.home.y),moves)

    def test_consumed_rod_cannot_recall_th_army_to_shop(self):
        b,g,a,c=self.scene();c.cleared.add('th-8');dk=a[0]
        dk.x=-590;dk.y=2491;g.my_heroes=lambda:[dk];g.inventory=lambda h:[None]*6
        b.economy.opening_rod_allowed=True;b.economy.ready=lambda *args:[b.home]
        b.bank_supply_jobs=lambda *args:[];b.restock_scrolls=lambda *args:None
        b.shop_item=lambda *args:(_ for _ in ()).throw(AssertionError('group restock'))
        b.items(230,1)
        self.assertIsNone(b.shop_goal)

    def test_attack_and_other_map_release_route(self):
        b,g,a,c=self.scene(True,True)
        self.assertFalse(c.prepare_th_route(b.home,600,True))
        self.assertTrue(c.candidates(g,a,b.home,600))
        c.map_alias='TR';c.th_attack_started=False
        self.assertFalse(c.prepare_th_route(b.home,601,False))
        self.assertFalse(c.th_route(b.home))


if __name__=='__main__':unittest.main()
