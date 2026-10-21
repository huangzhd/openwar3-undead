import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_scout_opening as scout
import test_opening_safety_0131 as ticks
import test_tavern_0145 as tavern
import test_battle_shop_0163 as shop
from test_micro_loot import unit,dist
from undead.policy import Action
from undead.camp_pull import ALMercenaryPull
from undead.creeping import Creeping


class ALCorpseTests(unittest.TestCase):
    def scene(self):
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=scout.ScoutCorpseTests().make()
        f=json.loads((Path(__file__).parent/'fixtures/al_192008_corpse.json').read_text(encoding='utf-8'))
        b.creeping.map_alias='AL';b.scout_corpse=dict(point=tuple(f['corpse']['point']),handle=tuple(f['corpse']['handle']),clock=f['corpse']['clock'])
        row=next(u for u in f['frame']['army'] if u['type']=='Udea');dk.x=row['x'];dk.y=row['y']
        foes=[]
        for row in f['frame']['enemies']:
            u=unit(row['type'],row['handle'][0],row['x'],row['hp']);u.y=row['y'];u.owner=12;foes.append(u)
        g.creeps=lambda:foes;g.current_target=lambda u:None
        b.battle_enemies=foes
        return b,g,dk,foes,orders,events,cool

    def test_recorded_position_casts_without_entering_idle_camp_and_waits_for_actual_skeletons(self):
        b,g,dk,foes,orders,ev,cool=self.scene()
        self.assertGreater(g.dist(dk,b.scout_corpse['point']),400)
        self.assertTrue(b.safe_al_corpse_approach(dk,foes,132.13))
        self.assertTrue(b.use_scout_corpse([dk],dk,132.13))
        self.assertEqual(orders,[('rod',dk.handle)]);self.assertFalse(b.opening_rod_finished)
        skels=[unit('uske',800+i,dk.x,180) for i in range(2)]
        g.units=lambda owner,codes:[u for u in skels if u.type in codes]
        self.assertFalse(b.use_scout_corpse([dk],dk,133));self.assertTrue(b.opening_rod_finished)

    def test_actual_aggro_close_guard_player_cooldown_and_other_map_keep_protection(self):
        for reason in ('aggro','close','player','cooldown','map'):
            b,g,dk,foes,orders,ev,cool=self.scene()
            if reason=='aggro':g.current_target=lambda u:dk
            if reason=='close':foes[0].x=dk.x+200;foes[0].y=dk.y
            if reason=='player':foes[0].owner=1
            if reason=='cooldown':cool[0]=10
            if reason=='map':b.creeping.map_alias='TH'
            b.use_scout_corpse([dk],dk,132.13)
            self.assertFalse(any(o[0]=='rod' for o in orders),reason)

    def test_full_tick_idle_neutral_hp_no_longer_causes_retreat_before_summon(self):
        original,_,_,foes,_,_,_=self.scene()
        g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
        home=g.my_buildings()[0];dk.x=-706;dk.y=-3204;dk.hp=dk.hp_max=675;clock[0]=132.13
        b.creeping.map_alias='AL';b.scout_corpse=original.scout_corpse;b.creeping.safe_route=lambda *a:True
        own=[dk,home];g.snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own)
        g.my_units=lambda:own;g.units=lambda side,codes:[u for u in own if u.type in codes]
        g.enemies=lambda:[];g.creeps=lambda:foes;g.current_target=lambda u:None
        g.inventory=lambda u:['rnec'];g.use_item=lambda h,i:orders.append(('rod',h.handle)) or True
        b.emergency_portal=lambda *a:False;b.heal_allies=lambda *a:None
        b.combat_spells=lambda *a:None;b.frost_armor=lambda *a:None
        b.army_recovery.tick=lambda *a:False;b.shields.plan=lambda *a:{};b.micro.plan=lambda *a,**k:{}
        b.collect_loot=lambda *a:False;b.support_dk=lambda *a:False
        b.battle_shop.sell_nearby=lambda *a:False;b.battle_shop.rod_tick=lambda *a:set()
        b.equipment.tick=lambda *a:False;b.creep=lambda army,center,now:b.use_scout_corpse(army,dk,now)
        b.tick(forced=Action.CREEP)
        self.assertEqual(b.action,Action.CREEP);self.assertIn(('rod',dk.handle),orders)


class OrbFirstTests(unittest.TestCase):
    def test_missing_or_unknown_orb_blocks_solo_and_group_even_with_surplus_gold(self):
        for bag in ([],None):
            b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game();b.g.inventory=lambda h:bag
            res['gold']=2000;b.recruit_tavern(a,[],500,3,set())
            self.assertFalse(m);self.assertFalse(buys)
            b.tavern_group_requested=True;b.escort_tavern(a,[],501,3)
            self.assertFalse(m);self.assertFalse(buys)

    def test_existing_courier_cannot_buy_on_receipt_without_orb_in_bag(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        b.recruit_tavern(a,[],500,3,set());courier=next(u for u in a if u.handle==b.tavern_mission['courier']);courier.x=0
        b.g.inventory=lambda h:[];b.recruit_tavern(a,[],501,3,set());self.assertFalse(buys)
        b.g.inventory=lambda h:['ocor'] if h.type=='Udea' else []
        b.recruit_tavern(a,[],502,3,set());self.assertEqual(buys,['Nbrn'])

    def test_bracer_sell_requires_inventory_removal_and_refund(self):
        for confirmed in (False,True):
            g,b,s,ev=shop.ShoppingTests().make();g.dk.x=g.home.x;g.bags[g.dk.handle]=['brac']+[None]*5
            def sell(h,slot,target):
                if confirmed:g.bags[h.handle][slot]=None;g.gold+=200
                return True
            g.sell_item=sell
            self.assertTrue(s.sell_nearby(b,g.heroes,[],500));s.observe(g,504)
            self.assertEqual(any(e['event']=='shop_transaction_confirmed' for e in ev),confirmed)
            self.assertEqual('brac' in g.inventory(g.dk),not confirmed)


class MercenaryPullTests(unittest.TestCase):
    def test_full_tick_pull_precedes_spells_and_regular_camp_attack(self):
        g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
        lich=unit('Ulic',100,-850,600);lich.owner=0;a.append(lich)
        for u in [dk,*a]:u.x=-850;u.hp=u.hp_max
        own=[dk,*a,*g.my_buildings()]
        g.my_units=lambda:own;g.snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own)
        g.units=lambda side,codes:[u for u in own if u.type in codes]
        g.my_heroes=lambda:[dk,lich];g.inventory=lambda u:['ocor'] if u is lich else []
        guard=unit('nfsh',501,0,450);guard.owner=12
        g.enemies=lambda:[];g.creeps=lambda:[guard];g.current_target=lambda u:None
        g.map=lambda:N(starts=[],walkable=lambda *p:True);g.visible=lambda *p:True
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        g.attack=lambda u,e,**kw:orders.append(('tag',u.handle,e.handle)) or True
        b.creeping.map_alias='AL';b.creeping.catalog=[dict(id='al-11',kind='mercenary',x=0,y=0)]
        b.creeping.active=b.creeping.catalog[0];b.creeping.safe_route=lambda *a:True
        b.emergency_portal=lambda *a:False;b.heal_allies=lambda *a:None
        b.combat_spells=lambda *a:orders.append(('offense',));b.shields.plan=lambda *a:{};b.micro.plan=lambda *a,**k:{}
        b.tick(forced=Action.CREEP)
        self.assertIn(('tag',lich.handle,guard.handle),orders);self.assertNotIn(('offense',),orders)
        self.assertTrue(all(p[0]<0 for kind,h,p in orders if kind=='move'))

    def scene(self):
        lich=unit('Ulic',1,-850,600);dk=unit('Udea',2,-900,600);fiend=unit('ucry',3,-800,600)
        target=unit('nfsh',4,0,450);target.owner=12;army=[lich,dk,fiend];guards=[target];orders=[];events=[]
        g=N(dist=dist,path_distance=dist,map=lambda:N(walkable=lambda *p:True),creeps=lambda:guards,
            current_target=lambda u:None,attack=lambda u,e,**kw:orders.append(('attack',u.handle,e.handle)) or True)
        c=Creeping(lambda *a,**k:None,[dict(id='al-11',kind='mercenary',x=0,y=0)])
        c.active=c.catalog[0];c.map_alias='AL';c.safe_route=lambda *a:True
        b=N(g=g,creeping=c,home=N(x=-4000,y=-1000),action=Action.CREEP,attack_committed=False,
            player_contact=[],teleport=None,situation=N(threatened=False),set_intent=lambda s:None,
            go_raw=lambda units,p,t:orders.extend(('move',u.handle,p) for u in units))
        pull=ALMercenaryPull(lambda event,**kw:events.append(dict(event=event,**kw)))
        return pull,b,army,target,orders,events

    def test_lich_tags_then_actual_aggro_moves_lich_back_and_pulled_guard_releases_combat(self):
        pull,b,a,t,orders,ev=self.scene();lich=a[0]
        self.assertTrue(pull.tick(b,a,500));rear=pull.active['rear']
        self.assertEqual([o for o in orders if o[0]=='attack'],[('attack',lich.handle,t.handle)])
        self.assertEqual({o[1] for o in orders if o[0]=='move'},{u.handle for u in a[1:]})
        self.assertEqual(pull.active['phase'],'tag') # receipt does not imply aggro
        b.g.current_target=lambda u:lich if u is t else None;orders.clear()
        self.assertTrue(pull.tick(b,a,501));self.assertIn(('move',lich.handle,rear),orders)
        t.x=-350
        self.assertFalse(pull.tick(b,a,503));self.assertEqual(ev[-1]['reason'],'guard_pulled_observed')
        before=list(orders);self.assertFalse(pull.tick(b,a,504));self.assertEqual(orders,before)
        self.assertNotIn('al-11',b.creeping.cleared)

    def test_uncertain_hit_has_two_attempts_and_twenty_second_limit(self):
        pull,b,a,t,orders,ev=self.scene()
        for now in (500,504,508,515):self.assertTrue(pull.tick(b,a,now))
        self.assertFalse(pull.tick(b,a,520));self.assertFalse(pull.tick(b,a,530))
        self.assertEqual(sum(o[0]=='attack' for o in orders),2)
        self.assertEqual(ev[-1]['reason'],'unconfirmed_timeout')

    def test_existing_fight_enemy_contact_low_lich_and_other_camps_do_not_reset_combat(self):
        for reason in ('engaged','enemy','hurt','other_map','other_camp','cast'):
            pull,b,a,t,orders,ev=self.scene();blocked=set()
            if reason=='engaged':b.g.current_target=lambda u:a[1] if u is t else None
            if reason=='enemy':b.player_contact=[unit('hfoo',99,-200)]
            if reason=='hurt':a[0].hp=100
            if reason=='other_map':b.creeping.map_alias='NI'
            if reason=='other_camp':b.creeping.active['kind']='shop'
            if reason=='cast':blocked={a[0].handle}
            self.assertFalse(pull.tick(b,a,500,blocked),reason);self.assertFalse(orders)


if __name__=='__main__':unittest.main()
