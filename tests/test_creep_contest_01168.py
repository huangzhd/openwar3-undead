import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_orb_contact_01136 as orb
import test_al_route_01166 as al
import test_foundation_owner_01124 as foundation
import test_tavern_0145 as tavern
import test_opening_safety_0131 as ticks
from test_micro_loot import unit, FakeLootGame
from undead.creeping import Creeping
from undead.controller import Controller
from undead.loot import Loot
from undead.policy import Action, Situation, choose_rule


class CreepContestTests(unittest.TestCase):
    def scene(self):
        g,b,s,ev,e=orb.OrbContactTests().scene()
        c=Creeping(b.log,al.MAP['camps']);c.map_alias='AL';b.creeping=c;c.tier=3
        b.home.x=-2176;b.home.y=-4672;c.cleared=set(c.al_route(b.home)[:-1])
        c.active=next(p for p in c.catalog if p['id']=='al-11');p=(c.active['x'],c.active['y'])
        c.safe_route=lambda *a:True
        for h in g.heroes:h.x=p[0]-850;h.y=p[1]
        e.x=p[0]-80;e.y=p[1]
        guard=unit('nomg',500,p[0],500);guard.y=p[1];guard.owner=12
        g.creeps=lambda:[guard];g.enemies=lambda:[e];g.visible=lambda *a:True
        g.current_target=lambda u:guard if u is e else None
        g.bags[g.dk.handle]=[None]*6;g.bags[g.lich.handle]=['ocor']+[None]*5
        b.player_contact=[];s.orb=None
        b.focus_siege=lambda *a:False
        b.fight=lambda army,foes,now:g.orders.append(('fight',tuple(u.handle for u in foes)))
        b.go=lambda army,p,now,attack=False:g.orders.append(('group',p))
        return g,b,c,ev,e,guard,(g.lich.x,g.lich.y)

    def test_visible_enemy_creeping_with_lich_orb_is_attacked_and_camp_preserved(self):
        g,b,c,ev,e,guard,center=self.scene();camp=c.active
        self.assertFalse(b.detect_player_contact(g.heroes,[e],center)) # beyond ordinary 700 contact
        b.prepare_creep_contest(g.heroes,[e],[guard],center,530)
        self.assertIn(e,b.player_contact)
        self.assertFalse(b.wait_for_orb(g.heroes,[e,guard],530,3))
        self.assertTrue(b.respond_player_contact(g.heroes,530))
        self.assertIn(('fight',(e.handle,)),g.orders)
        self.assertIs(c.active,camp);self.assertTrue(c.paused);self.assertNotIn(camp['id'],c.deferred)
        # Once engaged, changing the enemy's target to our Lich must not abandon the camp.
        g.current_target=lambda u:g.lich if u is e else None
        b.prepare_creep_contest(g.heroes,[e],[guard],center,531)
        b.respond_player_contact(g.heroes,531);self.assertIs(c.active,camp)

    def test_dk_only_unknown_lich_bag_hidden_guard_or_passersby_do_not_trigger(self):
        for reason in ('dk_only','unknown','hidden_guard','passerby','too_far','unsafe_path','dead_lich'):
            with self.subTest(reason=reason):
                g,b,c,ev,e,guard,center=self.scene();visible=[guard]
                if reason=='dk_only':g.bags[g.lich.handle]=[];g.bags[g.dk.handle]=['ocor']
                if reason=='unknown':g.bags[g.lich.handle]=None
                if reason=='hidden_guard':visible=[]
                if reason=='passerby':g.current_target=lambda u:None
                if reason=='too_far':e.x+=3000
                if reason=='unsafe_path':c.safe_route=lambda *a:False
                if reason=='dead_lich':g.lich.hp=0
                b.prepare_creep_contest(g.heroes,[e],visible,center,530)
                self.assertIsNone(b.creep_contest);self.assertFalse(b.player_contact)

    def test_enemy_leaves_resume_same_remaining_camp_then_attack_readiness(self):
        g,b,c,ev,e,guard,center=self.scene();camp=c.active;p=(camp['x'],camp['y'])
        b.prepare_creep_contest(g.heroes,[e],[guard],center,530);b.respond_player_contact(g.heroes,530)
        b.player_contact=[];b.prepare_creep_contest(g.heroes,[],[guard],center,532)
        self.assertIsNone(b.creep_contest);self.assertFalse(b.respond_player_contact(g.heroes,532))
        target,foes=c.choose(g,g.heroes,center,b.home,532)
        self.assertEqual(target,p);self.assertIs(c.active,camp);self.assertNotIn(camp['id'],c.cleared)
        self.assertTrue(any(e['event']=='creep_resumed' for e in ev))
        self.assertFalse(c.observe_clear(g,p,533,[guard]))
        g.creeps=lambda:[];self.assertTrue(c.observe_clear(g,p,534,[]))
        s=Situation(534,tier=3,orb=True,lich=True,third_hero=True)
        s.pre_attack_camp_pending=c.prepare_al_route(b.home,534,False)
        self.assertEqual(choose_rule(s),Action.ATTACK)

    def test_orb_and_ordinary_contact_do_not_impose_retry_delay(self):
        for reason in ('orb_contact_disengage','player_contact','preserve_attack_readiness'):
            g,b,c,ev,e,guard,center=self.scene();camp=c.active
            c.defer(530,reason)
            self.assertEqual(c.choose(g,g.heroes,center,b.home,530)[0],(camp['x'],camp['y']))
        # Failed paths still retain their independent retry protection.
        g,b,c,ev,e,guard,center=self.scene();c.defer(530,'unreachable')
        self.assertIsNone(c.choose(g,g.heroes,center,b.home,531)[0])

    def test_previous_orb_withdrawal_can_be_contested_but_safety_failure_cannot(self):
        for reason in ('orb_contact_disengage','player_contact','safety_retreat','unreachable'):
            g,b,c,ev,e,guard,center=self.scene();c.defer(520,reason)
            b.prepare_creep_contest(g.heroes,[e],[guard],center,530)
            self.assertEqual(b.creep_contest is not None,reason in ('orb_contact_disengage','player_contact'))
            self.assertNotIn('al-11',c.cleared)

    def test_confirmed_handoff_releases_old_cooldown_but_not_new_safety_deferral(self):
        for reason in ('orb_contact_disengage','safety_retreat'):
            g,b,c,ev,e,guard,center=self.scene()
            c.defer(520,reason);c.deferred['al-11']=610
            b.orb_rendezvous=dict(started=520,camp='al-11')
            self.assertFalse(b.wait_for_orb(g.heroes,[],530,3))
            self.assertEqual(c.deferred['al-11'],530 if reason=='orb_contact_disengage' else 610)

    def test_contest_timeout_stops_extended_pursuit_without_waiting_to_creep(self):
        g,b,c,ev,e,guard,center=self.scene()
        b.prepare_creep_contest(g.heroes,[e],[guard],center,530)
        b.prepare_creep_contest(g.heroes,[e],[guard],center,591)
        self.assertIsNone(b.creep_contest);self.assertTrue(b.creep_contest_blocked)
        b.player_contact=[];b.prepare_creep_contest(g.heroes,[],[guard],center,592)
        self.assertIsNotNone(c.choose(g,g.heroes,center,b.home,592)[0])

    def test_full_tick_real_enemy_strength_still_overrides_counter_creeping(self):
        g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
        lich=unit('Ulic',100,0);lich.owner=0;a.append(lich)
        for u in [dk,*a]:u.hp=u.hp_max
        g.my_heroes=lambda:[dk,lich];g.inventory=lambda u:['ocor'] if u is lich else []
        foe=g.enemies()[0];foe.hp=12000
        guard=unit('nomg',501,350,500);guard.owner=12
        g.creeps=lambda:[guard];g.current_target=lambda u:guard if u is foe else None
        b.creeping.catalog=[dict(id='test',x=350,y=0,kind='ogre',max_level=3,hp=500,difficulty=3)]
        b.creeping.active=b.creeping.catalog[0];b.creeping.safe_route=lambda *a:True
        g.visible=lambda *a:True
        b.emergency_portal=lambda *a:False;b.collective_retreat=lambda *a:orders.append(('retreat',))
        b.heal_allies=lambda *a:None;b.frost_armor=lambda *a:None;b.combat_spells=lambda *a:None
        b.army_recovery.tick=lambda *a:False;b.shields.plan=lambda *a:{};b.micro.plan=lambda *a,**k:{}
        b.tick(forced=Action.CREEP)
        self.assertEqual(b.action,Action.RETREAT);self.assertIsNone(b.creep_contest)
        self.assertIn(('retreat',),orders)


class ALShopTests(unittest.TestCase):
    def scene(self):
        l,g,h,w,bs,ws,orders,ev,order=foundation.FoundationTests().scene()
        l.map_alias='AL';h.x=-2176;h.y=-4672;g.can_afford=lambda code:True
        for code,x,y in [('uaod',-2720,-4704),('uzig',-2208,-5216),('usep',-1664,-4672)]:
            u=unit(code,len(bs)+10,x);u.y=y;bs.append(u)
        return l,g,h,w,bs,orders,ev

    def test_recorded_successful_command_is_first_and_actual_foundation_confirms(self):
        l,g,h,w,bs,orders,ev=self.scene()
        f=json.loads((Path(__file__).parent/'fixtures/al_185036_shop_layout.json').read_text(encoding='utf-8'))
        command=[e for e in f['events'] if e['event']=='home_build_order_pending'][-1]
        observed=next(e for e in f['events'] if e['event']=='home_foundation_observed')
        point=l.build(g,w,'utom',h,57.905)
        self.assertEqual(point,tuple(command['point']))
        self.assertEqual(orders,[('utom',*point)])
        l.build(g,w,'utom',h,59);self.assertEqual(orders,[('utom',*point)])
        u=unit('utom',100,observed['point'][0]);u.y=observed['point'][1];bs.append(u)
        l.observe(g,61);self.assertNotIn('utom',l.pending)
        self.assertEqual(ev[-1]['point'],tuple(observed['point']))

    def test_slot_failure_falls_back_and_unverified_spawn_is_not_mirrored(self):
        for why in ('occupied','ground','failed','northeast'):
            l,g,h,w,bs,orders,ev=self.scene()
            if why=='occupied':u=unit('uslh',100,-2368);u.y=-4160;bs.append(u)
            if why=='ground':g.map=lambda:N(buildable=lambda x,y:(x,y)!=(-2368,-4192))
            if why=='failed':l.failed_spots[('utom',(-2368,-4192))]=100
            if why=='northeast':h.x=2176;h.y=4672;bs[:]=[h]
            point=l.build(g,w,'utom',h,58)
            self.assertIsNotNone(point);self.assertNotEqual(point,(-2368,-4192))
            if why=='northeast':self.assertNotEqual(point,(2368,4192))


class PromptThirdHeroTests(unittest.TestCase):
    def test_lack_of_gold_does_not_consume_dispatch_window(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        res['gold']=424;b.recruit_tavern(a,[],440,3,set())
        b.recruit_tavern(a,[],480,3,set());self.assertFalse(b.tavern_group_requested)
        res['gold']=425;a[-1].x=0
        b.recruit_tavern(a,[],500,3,set());self.assertEqual(buys,['Nbrn'])

    def test_affordable_hire_does_not_wait_for_four_fiends_or_statue(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        b.situation.fiends=1;b.situation.statues=0;a[:]=a[:3];a[-1].x=0
        res.update(gold=425,lumber=135,food_used=45,food_cap=50)
        b.recruit_tavern(a,[],500,3,set())
        self.assertEqual(buys,['Nbrn']);self.assertIsNotNone(b.tavern_mission)
        self.assertFalse(any(e['event']=='tavern_hero_observed' for e in ev))

    def test_safe_existing_courier_buys_while_main_has_enemy_contact(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        b.recruit_tavern(a,[],500,3,set())
        courier=next(u for u in a if u.handle==b.tavern_mission['courier']);courier.x=0
        enemy=unit('hfoo',99,-2000);enemy.owner=1
        b.player_contact=[enemy];b.battle_enemies=[enemy]
        b.recruit_tavern(a,[enemy],501,3,set())
        self.assertEqual(buys,['Nbrn']);self.assertIsNotNone(b.tavern_mission)

    def test_neutral_combat_does_not_block_safe_spare_courier(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        a[-1].x=0;guard=unit('nomg',99,-2000);guard.owner=12;b.battle_enemies=[guard]
        b.recruit_tavern(a,[guard],500,3,set())
        self.assertEqual(buys,['Nbrn']);self.assertEqual(b.tavern_mission['courier'],a[-1].handle)


class FreshDropPriorityTests(unittest.TestCase):
    def test_fresh_drop_precedes_orb_trip_and_next_camp_in_full_tick(self):
        g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
        for u in [dk,*a]:u.hp=u.hp_max
        g.enemies=lambda:[];g.inventory=lambda u:[];g.current_target=lambda u:None
        b.emergency_portal=lambda *a:False;b.heal_allies=lambda *a:None
        b.frost_armor=lambda *a:None;b.combat_spells=lambda *a:None
        b.army_recovery.tick=lambda *a:False;b.shields.plan=lambda *a:{};b.micro.plan=lambda *a,**k:{}
        b.collect_loot=lambda *a:orders.append(('loot',)) or True
        b.battle_shop.orb_tick=lambda *a:orders.append(('orb',)) or set()
        b.creep=lambda *a:orders.append(('next_camp',))
        b.tick(forced=Action.CREEP)
        self.assertIn(('loot',),orders);self.assertNotIn(('orb',),orders);self.assertNotIn(('next_camp',),orders)

    def test_mid_camp_drop_orders_picker_only_and_confirms_inventory(self):
        g=FakeLootGame();g.hero.hp=g.hero.hp_max
        friend=unit('ucry',2,20);guard=unit('nftt',3,300);guard.owner=12;g.creeps=lambda:[guard]
        b=Controller(g,lambda *a,**k:None);b.action=Action.CREEP;b.loot=Loot({},b.log)
        fought=[];b.fight=lambda army,foes,now:fought.extend(u.handle for u in army)
        b.go=lambda *a,**k:self.fail('main army must keep fighting')
        self.assertTrue(b.collect_loot([g.hero,friend],[guard],530,[g.hero]))
        self.assertEqual(g.pickups,['ratf']);self.assertEqual(fought,[friend.handle]);self.assertFalse(b.loot.done)
        g.ground=[];g.inv[0]='ratf'
        b.collect_loot([g.hero,friend],[guard],531,[g.hero]);self.assertTrue(b.loot.done)


if __name__=='__main__':unittest.main()
