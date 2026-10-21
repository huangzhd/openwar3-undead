import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_creep_tempo_01101 as tempo
import test_ni_rod_foundation_01146 as rods
import test_opening_safety_0131 as ticks
from test_micro_loot import unit
from undead.creeping import Creeping
from undead.controller import Controller
from undead.policy import Situation, Action, choose_rule, attack_ready


MAP=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['AL']


class ALRouteTests(unittest.TestCase):
    def scene(self,north=False):
        x,y=(2176,4672) if north else (-2176,-4672)
        b,g,a,_=tempo.TempoTests().opening(x,y)
        c=Creeping(b.log,MAP['camps']);c.map_alias='AL';c.home_only=True;b.creeping=c
        c.enemy_main=(-2176,-4672) if north else (2176,4672)
        g.map=lambda:N(starts=[(p['x'],p['y']) for p in MAP['starts']])
        g.walk_path=lambda a,z:[a,z]
        g.visible=lambda *args:True;g.creeps=lambda:[]
        g.current_target=lambda u:None
        return b,g,a,c

    def test_first_two_skeletons_start_nearby_322_from_either_spawn(self):
        for north,expected in ((False,'al-3'),(True,'al-16')):
            b,g,a,c=self.scene(north)
            self.assertFalse(c.candidates(g,a[:2],b.home,140))
            b.creep(a,(b.home.x,b.home.y),145)
            self.assertEqual(c.active['id'],expected)

    def test_all_seven_camps_chain_without_strength_tech_statue_or_home_half_wait(self):
        for north,route in ((False,['al-3','al-10','al-12','al-15','al-6','al-8','al-11']),
                            (True,['al-16','al-9','al-7','al-4','al-13','al-11','al-8'])):
            b,g,a,c=self.scene(north);center=(b.home.x,b.home.y)
            b.ni_rod_stop.done=True # Home stop covered by transaction tests below.
            moves=[];b.go=lambda army,p,now,attack=False:moves.append(p)
            for i,k in enumerate(route):
                c.prepare_al_route(b.home,150+i*10,False)
                moves.clear();b.creep(a if i==0 else a[:1],center,150+i*10)
                self.assertEqual(c.active['id'],k)
                point=(c.active['x'],c.active['y'])
                self.assertIn(point,moves);self.assertNotIn((b.home.x,b.home.y),moves)
                # Hidden or surviving camp members must not advance the route.
                g.visible=lambda *args:False
                self.assertFalse(c.observe_clear(g,point,151+i*10,[]))
                g.visible=lambda *args:True
                foe=unit('ngnw',800,point[0],1);foe.y=point[1]
                self.assertFalse(c.observe_clear(g,point,151+i*10,[foe]))
                self.assertTrue(c.observe_clear(g,point,152+i*10,[]));center=point
                self.assertNotIn(k,[p['id'] for p in c.candidates(g,a,b.home,153+i*10)])
            self.assertIsNone(c.choose(g,a,center,b.home,230)[0])

    def test_clear_transitions_same_tick_except_required_home_stop(self):
        for north in (False,True):
            b,g,a,c=self.scene(north);route=c.al_route(b.home);b.ni_rod_stop.done=True
            moves=[];b.go=lambda army,p,now,attack=False:moves.append(p)
            for i,k in enumerate(route[:-1]):
                c.active=next(p for p in c.catalog if p['id']==k)
                center=(c.active['x'],c.active['y']);moves.clear()
                b.creep(a,center,220+i*20)
                self.assertEqual(c.active['id'],route[i+1])
                self.assertEqual(moves,[(c.active['x'],c.active['y'])])

    def test_both_strong_camps_required_before_attack_and_threats_keep_priority(self):
        for north in (False,True):
            b,g,a,c=self.scene(north);route=c.al_route(b.home)
            s=Situation(600,tier=3,dk=True,lich=True,orb=True,third_hero=True)
            for count in (5,6):
                c.cleared=set(route[:count]);s.pre_attack_camp_pending=c.prepare_al_route(b.home,600,False)
                self.assertFalse(attack_ready(s));self.assertEqual(choose_rule(s),Action.CREEP)
            c.cleared=set(route);s.pre_attack_camp_pending=c.prepare_al_route(b.home,601,False)
            self.assertTrue(attack_ready(s));self.assertEqual(choose_rule(s),Action.ATTACK)
            s.threatened=True;self.assertEqual(choose_rule(s),Action.DEFEND)
            s.local_enemy_hp=2000;s.army_hp=500;self.assertEqual(choose_rule(s),Action.RETREAT)

    def test_real_contact_and_unreachable_paths_do_not_skip_or_fake_clear(self):
        b,g,a,c=self.scene();c.cleared.update(c.al_route(b.home)[:4]);c.al_contested=True
        self.assertFalse(c.route_continuous(b.home))
        self.assertIsNone(c.choose(g,a,(b.home.x,b.home.y),b.home,300)[0])
        c.al_contested=False;g.path_distance=lambda *args:None
        for now in (301,392,500):c.choose(g,a,(b.home.x,b.home.y),b.home,now)
        self.assertIn('al-6',c.exhausted);self.assertNotIn('al-6',c.cleared)
        self.assertEqual(c.failures['al-6'],2)

    def test_attack_and_other_map_release_al_constraints(self):
        b,g,a,c=self.scene()
        self.assertFalse(c.prepare_al_route(b.home,600,True));self.assertFalse(c.al_route(b.home))
        c.map_alias='NI';c.al_attack_started=False
        self.assertFalse(c.prepare_al_route(b.home,601,False));self.assertFalse(c.al_route(b.home))

    def test_full_tick_keeps_creeping_with_dk_individual_pull_but_retreats_from_enemy(self):
        g,b,dk,allies,orders,clock=ticks.EmergencyTests().controller()
        c=Creeping(b.log,MAP['camps']);c.map_alias='AL';b.creeping=c
        home=g.my_buildings()[0];home.x=-2176;home.y=-4672
        c.cleared={'al-3','al-10','al-12','al-15'}
        c.active=next(p for p in c.catalog if p['id']=='al-6')
        for u in [dk,*allies]:u.x=c.active['x'];u.y=c.active['y']
        foe=unit('nomg',999,dk.x+100,5000);foe.y=dk.y;foe.owner=12
        g.enemies=lambda:[];g.creeps=lambda:[foe];g.visible=lambda *p:True
        g.map=lambda:N(starts=[(-2176,-4672),(2176,4672)],walkable=lambda *p:True)
        g.walk_path=lambda a,z:[a,z];g.current_target=lambda u:dk if u is foe else None
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        b.micro.plan=lambda *args,**kwargs:{dk.handle:(dk.x-300,dk.y)}
        b.shields.plan=lambda *a:{};b.frost_armor=lambda *a:None
        b.combat_spells=lambda *a:None;b.hero_support_pullbacks=lambda *a:{}
        b.recruit_tavern=lambda *a:set();b.recover_missing_heroes=lambda *a:False
        b.battle_shop.rod_tick=lambda *a:set();b.battle_shop.orb_tick=lambda *a:set()
        b.first_attack_supply.tick=lambda *a:set();b.battle_shop.sell_nearby=lambda *a:False
        b.escort_tavern=lambda *a:self.fail('group tavern interrupts active AL route')
        b.stop_hero_chases=lambda *a:None;b.collect_loot=lambda *a:False
        b.creep=lambda army,center,now:orders.append(('creep',[u.handle for u in army]))
        b.tick()
        self.assertEqual(b.action,Action.CREEP);self.assertTrue(b.situation.pre_attack_camp_pending)
        self.assertIn(('creep',[u.handle for u in allies]),orders)
        self.assertTrue(any(o[:2]==('move',dk.handle) for o in orders))
        foe.owner=1;g.enemies=lambda:[foe];g.creeps=lambda:[]
        b.emergency_portal=lambda *a:False
        b.collective_retreat=lambda *a:orders.append(('retreat',))
        clock[0]+=6;b.tick()
        self.assertFalse(b.situation.continuous_creeping)
        self.assertEqual(b.action,Action.RETREAT);self.assertIn(('retreat',),orders)


class ALHomeRodTests(unittest.TestCase):
    def scene(self,north=False):
        g,b,shop,stop,ev=rods.NIRodTests().scene()
        _,_,_,c=ALRouteTests().scene(north);b.creeping=c;b.ni_rod_stop=stop
        b.home=N(x=2176 if north else -2176,y=4672 if north else -4672)
        route=c.al_route(b.home);c.cleared.update(route[:2])
        g.home.x=b.home.x;g.home.y=b.home.y
        yard=unit('ugrv',99,b.home.x+200);yard.y=b.home.y
        b.economy.ready=lambda g,code:[yard] if code=='ugrv' else [g.home]
        g.my_buildings=lambda codes:[yard] if 'ugrv' in codes else [g.home]
        camp=next(p for p in c.catalog if p['id']==route[1]);g.dk.x=camp['x'];g.dk.y=camp['y']
        skeletons=[];cool=[0]
        g.units=lambda side,codes:[u for u in skeletons if u.type in codes]
        g.cooldown=lambda *args:cool[0]
        g.use_item=lambda h,i:g.orders.append(('rod',h.handle)) or True
        b.rod_birth_windows=[];b.use_rod=lambda h,i,t:Controller.use_rod(b,h,i,t)
        return g,b,shop,stop,ev,skeletons,cool

    def purchase(self,g,b,shop,stop):
        stop.tick(b,[g.dk],220)
        g.dk.x=b.home.x;g.dk.y=b.home.y
        stop.tick(b,[g.dk],225)
        self.assertFalse(stop.mission['returning'])
        shop.observe(g,229)

    def test_one_extra_rod_then_observed_home_summon_then_release_to_shop(self):
        for north in (False,True):
            g,b,shop,stop,ev,skeletons,cool=self.scene(north)
            g.bags[g.dk.handle][1]='rnec'
            self.purchase(g,b,shop,stop)
            self.assertTrue(stop.tick(b,[g.dk],229));self.assertFalse(stop.done)
            self.assertIn(('rod',g.dk.handle),g.orders)
            for i in (80,81):
                u=unit('uske',i,b.home.x,180);u.y=b.home.y;skeletons.append(u)
            cool[0]=20
            self.assertFalse(stop.tick(b,[g.dk],231));self.assertTrue(stop.done)
            stop.tick(b,[g.dk],235)
            self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)
            self.assertTrue(any(e.get('skeletons_observed') for e in ev))
            c=b.creeping;g.creeps=lambda:[];g.visible=lambda *args:False
            g.map=lambda:N(starts=[(p['x'],p['y']) for p in MAP['starts']])
            point,_=c.choose(g,[g.dk],(b.home.x,b.home.y),b.home,231)
            self.assertEqual(c.active['id'],c.al_route(b.home)[2])
            self.assertNotEqual(point,(b.home.x,b.home.y))

    def test_cooldown_not_ready_or_unknown_departs_without_wait_or_cast(self):
        for cd in (18,None):
            g,b,shop,stop,ev,_,cool=self.scene();self.purchase(g,b,shop,stop);cool[0]=cd
            self.assertFalse(stop.tick(b,[g.dk],229));self.assertTrue(stop.done)
            self.assertFalse(any(o[0]=='rod' for o in g.orders))
            self.assertFalse(any(e.get('skeletons_observed') for e in ev))

    def test_return_home_includes_army_and_does_not_stage_at_shop_camp(self):
        g,b,shop,stop,ev,_,_=self.scene();f=unit('ucry',90,g.dk.x);f.y=g.dk.y
        stop.tick(b,[g.dk,f],220)
        self.assertIn(('move','Udea',(b.home.x,b.home.y)),g.orders)
        self.assertIn(('move','ucry',(b.home.x,b.home.y)),g.orders)

    def test_old_acquisitions_do_not_skip_required_after_second_camp_purchase(self):
        g,b,shop,stop,ev,_,cool=self.scene();b.rod_acquisitions['Udea']=2
        g.bags[g.dk.handle][1]='rnec';self.purchase(g,b,shop,stop);cool[0]=15
        self.assertFalse(stop.tick(b,[g.dk],229))
        self.assertTrue(stop.done);self.assertEqual(g.inventory(g.dk).count('rnec'),2)
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)

    def test_unconfirmed_purchase_never_summons_and_is_bounded(self):
        g,b,shop,stop,ev,_,_=self.scene();g.dk.x=b.home.x;g.dk.y=b.home.y
        g.buy=lambda *args:g.orders.append(('fake-buy',)) or True
        for t in (220,224,228,232,236):shop.observe(g,t);stop.tick(b,[g.dk],t)
        self.assertTrue(stop.failed);self.assertFalse(stop.done)
        self.assertFalse(any(o[0]=='rod' for o in g.orders))
        self.assertEqual(sum(o[0]=='fake-buy' for o in g.orders),3)

    def test_summon_receipt_is_not_effect_and_retries_are_bounded(self):
        g,b,shop,stop,ev,_,_=self.scene();self.purchase(g,b,shop,stop)
        for t in (229,233,237,241):stop.tick(b,[g.dk],t)
        self.assertTrue(stop.done)
        self.assertEqual(sum(o[0]=='rod' for o in g.orders),2)
        self.assertFalse(any(e.get('skeletons_observed') for e in ev))

    def test_same_tick_second_clear_intercepts_before_shop_march(self):
        b,g,a,c=ALRouteTests().scene();route=c.al_route(b.home)
        c.cleared={route[0]};c.active=next(p for p in c.catalog if p['id']==route[1])
        center=(c.active['x'],c.active['y'])
        for u in a:u.x,u.y=center
        g.my_heroes=lambda:[a[0]];g.inventory=lambda h:['rnec',None,None,None,None,None]
        b.rod_acquisitions={'Udea':1};b.economy.ready=lambda *args:[b.home]
        moves=[];b.go=lambda *args,**kwargs:self.fail('shop march before home stop')
        b.go_raw=lambda army,p,t:moves.extend((u.type,p) for u in army)
        b.creep(a,center,220)
        self.assertIsNotNone(b.ni_rod_stop.mission)
        self.assertIn(('Udea',(b.home.x,b.home.y)),moves)


if __name__=='__main__':unittest.main()
