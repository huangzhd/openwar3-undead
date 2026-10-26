import unittest
from types import SimpleNamespace as N
from test_baseline import unit
import test_wyvern_army_01212 as wyvern
from test_consumables import Game
from undead.controller import Controller
from training import TrainingController
from undead.consumables import Consumables
from undead.stomp_response import improve_scroll_position


class StompTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc,birds=wyvern.WyvernArmyTests().scene(kind)
        tc.x=300;tc.y=0;tc.mana=300
        state={'cd':0}
        old=g.abilities
        g.abilities=lambda u:[dict(code='AOws',level=3,cooldown=state['cd'])] if u is tc else old(u)
        for e in birds:e.x=800
        for i,u in enumerate(own[:6]):u.y=(i-2.5)*35
        b.hero_pressure.select_strategy(g,own,foes,10)
        return b,g,own,foes,orders,events,effects,dk,tc,birds,state

    def test_dodge_spreads_only_threatened_units_then_releases_at_observed_stomp(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene(kind)
            own[5].x=-700
            pulls={};b.stomp_response.tick(b,own,foes,10,pulls)
            self.assertIn(own[0].handle,pulls);self.assertIn(own[6].handle,pulls)
            self.assertNotIn(own[5].handle,pulls);self.assertNotIn(dk.handle,pulls)
            self.assertGreater(max(p[1] for p in pulls.values())-min(p[1] for p in pulls.values()),150)
            self.assertTrue(all(g.dist(p,tc)>=530 for p in pulls.values()))
            state['cd']=5.5;pulls={};b.stomp_response.tick(b,own,foes,10.5,pulls)
            self.assertFalse(pulls)
            self.assertTrue(any(n=='battle_stomp_observed' for n,_ in events))
            # The normal focus path can fire immediately after this release.
            for e in birds:e.x=330
            b.focus_ranged(own,foes,10.6)
            self.assertTrue(any(o[0]=='attack' for o in orders))

    def test_ready_tc_timeout_does_not_cause_continuous_reshuffling(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene()
        b.stomp_response.tick(b,own,foes,10,{})
        pulls={};b.stomp_response.tick(b,own,foes,12,pulls)
        self.assertFalse(pulls)
        pulls={};b.stomp_response.tick(b,own,foes,14,pulls)
        self.assertFalse(pulls)

    def test_unknown_first_cooldown_silence_and_unrelated_armies_do_not_dodge(self):
        for why in ('unknown','first_cooling','silenced','mixed','retreat'):
            b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene()
            if why=='unknown':state['cd']=None
            if why=='first_cooling':state['cd']=5
            if why=='silenced':effects[tc.handle]=['BNsi']
            if why=='mixed':own.append(unit('uabo',99))
            if why=='retreat':b.action=type(b.action).RETREAT
            pulls={};b.stomp_response.tick(b,own,foes,10,pulls)
            self.assertFalse(pulls,why);self.assertFalse(events and any(n=='battle_stomp_observed' for n,_ in events))

    def test_respects_cast_retreat_stun_and_path_and_does_not_overwrite_pulls(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene()
        b.cast_until[own[0].handle]=11;effects[own[1].handle]=['BPSE'];b.micro.pulling.add(own[2].handle)
        own[3].hp=100
        pulls={own[4].handle:(-1000,0)}
        b.stomp_response.tick(b,own,foes,10,pulls,blocked={own[5].handle})
        self.assertTrue(all(u.handle not in pulls for u in own[:4]))
        self.assertEqual(pulls[own[4].handle],(-1000,0))
        b.stomp_response.windows.clear();b.stomp_response.next_at.clear();g.path_distance=lambda *a:None
        pulls={};b.stomp_response.tick(b,own,foes,12,pulls)
        self.assertFalse(pulls)

    def test_one_net_after_stomp_no_duplicates_and_no_nets_before(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene()
        for e in birds:e.x=360;effects[e.handle]=[]
        g.tech_many=lambda codes:{'Ruwb':1}
        old=g.abilities
        g.abilities=lambda u:[dict(code='Aweb',level=1)] if u.type=='ucry' else old(u)
        b.stomp_response.tick(b,own,foes,10,{})
        self.assertFalse(any(o[0]=='cast' and o[2]=='web' for o in orders))
        state['cd']=5.5;b.stomp_response.tick(b,own,foes,10.5,{})
        nets=[o for o in orders if o[0]=='cast' and o[2]=='web'];self.assertEqual(len(nets),1)
        b.stomp_response.tick(b,own,foes,11.7,{})
        self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2]=='web']),1)
        effects[nets[0][3]['target'].handle]=['Bwea'];b.stomp_response.tick(b,own,foes,12,{})
        self.assertTrue(any(n=='battle_web_observed' for n,_ in events))

    def test_precontact_roar_arc_covers_all_six_without_one_stomp_covering_everyone(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene(kind)
            lich=own[6];g.inventory=lambda u:['sror'] if u is lich else []
            b.battle_started=False;b.prepare_battle(1,own,target=(2000,0),foes=[])
            lp=b.prep_points[lich.handle];dp=b.prep_points[dk.handle]
            points=[b.prep_points[u.handle] for u in own if u.type=='ucry']
            self.assertTrue(all(g.dist(lp,p)<=441 for p in points))
            self.assertTrue(all(g.dist(dp,p)<600 for p in points))
            self.assertGreater(max(g.dist(a,c) for a in points for c in points),700)
            b.battle_started=True;b.battle_last_enemy=1;before=len(orders);b.prepare_battle(2,own,target=(2000,0))
            self.assertEqual(len(orders),before)

    def test_frost_armor_cannot_cancel_lich_dodge_but_resumes_after_stomp(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=self.scene()
        lich=own[6];old=g.abilities
        g.abilities=lambda u:[dict(code='AUfu',level=1)] if u is lich else old(u)
        tc.x=200;g.current_target=lambda u:own[0] if u is tc else None
        own[0].hp=300
        b.stomp_response.tick(b,own,foes,10,{})
        b.frost_armor(own,foes,10)
        self.assertFalse(any(o[0]=='cast' and o[2]=='frostarmor' for o in orders))
        state['cd']=5;b.stomp_response.tick(b,own,foes,10.5,{})
        b.frost_armor(own,foes,10.5)
        self.assertTrue(any(o[0]=='cast' and o[2]=='frostarmor' for o in orders))


class ScrollTests(unittest.TestCase):
    def setup(self):
        g=Game();events=[];c=Consumables(lambda n,**k:events.append((n,k)));locks={}
        for u in g.army:u.hp=u.hp_max
        foe=unit('Otch',99,owner=1,x=600);foe.has_detail=True
        g.me=lambda:0;g.current_target=lambda u:None
        return g,c,events,locks,[foe]

    def test_roar_waits_for_every_live_fiend_then_observes_all_buffs(self):
        g,c,events,locks,foes=self.setup();lich=g.heroes[1];g.bags[lich.handle][0]='sror';g.effect=True
        distant=unit('ucry',51,x=650);distant.mana=distant.mana_max=0;g.army.append(distant)
        c.tick(g,g.army,foes,1,locks);self.assertFalse(g.orders)
        distant.x=550;c.tick(g,g.army,foes,2,locks)
        self.assertIn(('use','Ulic','sror'),g.orders)
        c.tick(g,g.army,foes,3,locks)
        observed=[v for n,v in events if n=='consumable_effect_observed']
        self.assertIn(distant.handle,observed[0]['buffed'])

    def test_recent_group_damage_triggers_before_half_health_and_requires_real_damage(self):
        g,c,events,locks,foes=self.setup();dk=g.heroes[0];g.bags[dk.handle][0]='shea'
        foes.extend([unit('owyv',98,owner=1,x=650),unit('owyv',97,owner=1,x=670)])
        for i in range(2):g.army.append(unit('ucry',30+i,x=150+i*30))
        for u in g.army:u.hp=u.hp_max=600
        c.tick(g,g.army,foes,1,locks);self.assertFalse(g.orders)
        for u in g.army[3:]:u.hp=430
        c.tick(g,g.army,foes,2,locks)
        self.assertIn(('use','Udea','shea'),g.orders)
        use=next(v for n,v in events if n=='consumable_use_attempt')
        self.assertEqual(use['half_health_units'],0);self.assertEqual(use['recent_wounded'],3)

    def test_coverage_step_moves_only_carrier_once_and_emergency_does_not_wait(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=StompTests().scene()
        foes[:]=[];dk.x=-550;dk.y=0
        for i,u in enumerate(own[:6]):u.x=100;u.y=(i-2.5)*30;u.hp=300
        self.assertTrue(improve_scroll_position(b,dk,own,foes,10,600,150))
        self.assertEqual([o[1] for o in orders if o[0]=='move'],[dk.handle])
        self.assertFalse(improve_scroll_position(b,dk,own,foes,10.6,600,150))
        from unittest.mock import Mock
        g,c,events,locks,foes=self.setup();dk,lich,_=g.heroes
        g.bags[dk.handle][0]='shea';lich.hp=80;dk.mana=0
        controller=Mock();controller.consumables=c
        c.tick(g,g.army,foes,10,locks,controller=controller)
        self.assertIn(('use','Udea','shea'),g.orders)
        controller.g.move.assert_not_called()

    def test_scattered_wounded_trigger_carrier_approach_then_scroll_after_arrival(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=StompTests().scene()
        foes[:]=[];dk.x=-550;dk.y=0
        for i,u in enumerate(own[:6]):u.x=100;u.y=(i-2.5)*30;u.hp=300
        g.inventory=lambda u:['shea'] if u is dk else []
        g.use_item=lambda u,slot:orders.append(('use',u.handle,slot)) or True
        b.consumables.tick(g,own,foes,10,b.cast_until,controller=b)
        moves=[o for o in orders if o[0]=='move'];self.assertEqual(len(moves),1)
        self.assertFalse(any(o[0]=='use' for o in orders))
        dk.x,dk.y=moves[0][2]
        b.consumables.tick(g,own,foes,10.6,b.cast_until,controller=b)
        self.assertEqual(len([o for o in orders if o[0]=='use']),1)
        use=next(v for n,v in events if n=='consumable_use_attempt')
        self.assertTrue(all(u.handle in use['targets'] for u in own[:6]))

    def test_scroll_coverage_never_moves_carrier_into_tc_stomp_radius(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,state=StompTests().scene()
        dk.x=-450;dk.y=0;tc.x=0;tc.y=0;foes[:]=[tc]
        for i,u in enumerate(own[:6]):u.x=200;u.y=(i-2.5)*20;u.hp=300
        b.army_recovery.safe_path=lambda *a,**k:100
        self.assertFalse(improve_scroll_position(b,dk,own,foes,10,600,150))
        self.assertFalse(orders)


if __name__=='__main__':unittest.main()
