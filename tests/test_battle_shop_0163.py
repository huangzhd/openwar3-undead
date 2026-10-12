import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_strategy_0140 as strategy
import test_consumables as consumables
from undead.battle_shop import BattleShop,RINGS
from undead.damage import DamageTrend
from undead.micro import Micro
from undead.consumables import Consumables
from undead.policy import Action

class Game:
    dist=staticmethod(dist);path_distance=staticmethod(dist)
    def __init__(self):
        self.dk=unit('Udea',1,2000);self.lich=unit('Ulic',2,1900);self.dark=unit('Nbrn',3,1950)
        self.heroes=[self.dk,self.lich,self.dark];self.home=unit('utom',4,0);self.shop=unit('ngme',5,2200)
        for u in [*self.heroes,self.home,self.shop]:u.alive=True;u.visible_to=lambda me:True
        self.bags={h.handle:[None]*6 for h in self.heroes};self.bags[self.dk.handle][0]='stwp'
        self.gold=500;self.gathered=0;self.orders=[];self.pending_heroes=set()
    def me(self):return 0
    def my_heroes(self):return self.heroes
    def inventory(self,u):return self.bags[u.handle]
    def unit(self,h):return next((u for u in [*self.heroes,self.home,self.shop] if u.handle==h),None)
    def units(self,side,codes):return [u for u in [self.shop] if u.type in codes]
    def resources(self):return dict(gold=self.gold,gold_gathered=self.gathered)
    def give_item(self,h,slot,to):
        c=self.bags[h.handle][slot];self.bags[h.handle][slot]=None
        bag=self.bags[to.handle];bag[bag.index(None)]=c;self.orders.append(('give',h.type,to.type,c));return True
    def sell_item(self,h,slot,shop):
        c=self.bags[h.handle][slot];self.bags[h.handle][slot]=None;self.gold+=RINGS[c]
        self.orders.append(('sell',h.type,c));return True
    def buy(self,shop,c):
        h=self.dk if shop is self.home else self.lich;bag=self.bags[h.handle]
        bag[bag.index(None)]=c;self.gold-=375 if c=='ocor' else 150
        self.orders.append(('buy',h.type,c));return True

class ShoppingTests(unittest.TestCase):
    def make(self):
        g=Game();events=[];shop=BattleShop(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        b=N(g=g,action=Action.CREEP,teleport=None,situation=N(threatened=False),cast_until={},
            micro=N(pulling=set(),dk_support=None,dk_recovering=None),formation=N(reset=lambda:None),formation_at=0,
            creeping=N(safe_route=lambda *a:True),economy=N(ready=lambda g,c:[g.home],revival_pending=lambda g:g.pending_heroes),
            go_raw=lambda a,p,t:g.orders.extend(('move',h.type,p) for h in a),
            go=lambda a,p,t:g.orders.extend(('group',h.type,p) for h in a),set_intent=lambda s:None)
        return g,b,shop,events

    def test_dk_collects_ring_sells_buys_orb_and_returns_to_moving_lich(self):
        g,b,s,events=self.make();g.bags[g.lich.handle][0]='rde1'
        s.orb_tick(b,g.heroes,[],1,3);s.observe(g,2)
        self.assertIn('rde1',g.inventory(g.dk));self.assertNotIn('rde1',g.inventory(g.lich))
        reserved=s.orb_tick(b,g.heroes,[],5,3)
        self.assertEqual(reserved,{g.dk.handle});self.assertEqual(g.orders[-1],('move','Udea',(0,0)))
        g.dk.x=0;s.orb_tick(b,g.heroes,[],9,3);s.observe(g,10)
        self.assertEqual(g.orders[-1],('sell','Udea','rde1'))
        self.assertTrue(any(e['event']=='shop_transaction_confirmed' and e['kind']=='sell' for e in events))
        s.orb_tick(b,g.heroes,[],13,3);s.observe(g,14)
        self.assertIn('ocor',g.inventory(g.dk))
        g.lich.x=2300;s.orb_tick(b,g.heroes,[],17,3)
        self.assertEqual(g.orders[-1],('move','Udea',(2300,0)))
        g.dk.x=2300;s.orb_tick(b,g.heroes,[],21,3);s.observe(g,22)
        self.assertFalse(s.orb_tick(b,g.heroes,[],25,3));self.assertIn('ocor',g.inventory(g.lich))
        self.assertFalse(any(o[0]=='group' for o in g.orders))

    def test_courier_stalls_or_defense_releases_assignment_without_repeat_loop(self):
        for why in ('stall','defend','route'):
            g,b,s,_=self.make();s.orb_tick(b,g.heroes,[],1,3)
            if why=='defend':b.action=Action.DEFEND
            if why=='route':g.path_distance=lambda *a:None
            s.orb_tick(b,g.heroes,[],30,3)
            self.assertIsNone(s.orb)
            old=len(g.orders);s.orb_tick(b,g.heroes,[],31,3);self.assertEqual(len(g.orders),old)

    def test_team_orb_and_full_lich_do_not_cause_duplicate_purchase(self):
        for why in ('team','full'):
            g,b,s,_=self.make()
            if why=='team':g.bags[g.dark.handle][0]='ocor'
            else:g.bags[g.lich.handle]=['rat6']*6
            s.orb_tick(b,g.heroes,[],1,3);self.assertFalse(g.orders)

    def test_ring_disappearance_with_only_mining_income_is_not_sale_proof(self):
        g,b,s,ev=self.make();g.bags[g.dk.handle][1]='rde1'
        g.sell_item=lambda h,slot,target:g.bags[h.handle].__setitem__(slot,None) or True
        s.transact(g,g.dk,'rde1','sell',1,b.cast_until,g.home)
        g.gold+=100;g.gathered+=100;s.observe(g,5)
        self.assertEqual(ev[-1]['event'],'shop_transaction_unconfirmed')
        self.assertFalse(s.transact(g,g.dk,'rat6','sell',6,b.cast_until,g.home))

    def test_dk_mana_wand_sale_requires_inventory_and_net_gold(self):
        for refund in (0,100,200):
            g,b,s,events=self.make();g.bags[g.dk.handle][1]='woms';g.dk.x=0
            def sell(hero,slot,shop):
                g.bags[hero.handle][slot]=None;g.gold+=refund
                g.orders.append(('sell',hero.type,'woms'));return True
            g.sell_item=sell
            self.assertTrue(s.sell_nearby(b,g.heroes,[],500))
            g.gold+=20;g.gathered+=20;s.observe(g,504)
            self.assertNotIn('woms',g.inventory(g.dk))
            self.assertEqual(events[-1]['event'],'shop_transaction_confirmed' if refund else 'shop_transaction_unconfirmed')
            self.assertEqual(events[-1]['refund_excluding_gathering'],refund)

    def test_other_hero_wand_and_unapproved_equipment_stay(self):
        g,b,s,events=self.make();g.bags[g.lich.handle][0]='woms';g.bags[g.dk.handle][1]='rat6'
        self.assertFalse(s.sell_nearby(b,g.heroes,[],500));self.assertFalse(g.orders)
        self.assertFalse(s.transact(g,g.lich,'woms','sell',500,b.cast_until,g.shop))
        self.assertIn('woms',g.inventory(g.lich));self.assertIn('rat6',g.inventory(g.dk))

    def test_potion_purchase_is_observed_on_lich_and_not_rebought(self):
        g,b,s,ev=self.make();b.action=Action.ATTACK;g.bags[g.lich.handle][0]='ocor';g.lich.x=2200
        self.assertFalse(s.prepare_potion(b,g.heroes,[],500));s.observe(g,501)
        self.assertTrue(s.prepare_potion(b,g.heroes,[],504));self.assertIn('pnvl',g.inventory(g.lich))
        self.assertEqual([x for x in g.orders if x[0]=='buy'],[('buy','Ulic','pnvl')])

    def test_unsafe_hidden_or_unreachable_shop_does_not_pin_attack(self):
        for why in ('hidden','enemy','route','revive'):
            g,b,s,_=self.make();g.bags[g.lich.handle][0]='ocor';foes=[]
            if why=='hidden':g.shop.visible_to=lambda me:False
            if why=='enemy':foes=[unit('hfoo',20,2000)]
            if why=='route':g.path_distance=lambda *a:None
            if why=='revive':g.pending_heroes={'Nbrn'}
            self.assertTrue(s.prepare_potion(b,g.heroes,foes,500));self.assertFalse(g.orders)

    def test_unavailable_potion_stock_has_bounded_attempts_and_releases_army(self):
        g,b,s,ev=self.make();g.lich.x=2200;g.bags[g.lich.handle][0]='ocor'
        g.buy=lambda shop,code:g.orders.append(('rejected',code)) or False
        released=False
        for t in range(500,541,4):
            s.observe(g,t)
            released=s.prepare_potion(b,g.heroes,[],t) or released
        self.assertTrue(released)
        self.assertLessEqual(len([o for o in g.orders if o[0]=='rejected']),3)

class BurstTests(unittest.TestCase):
    def test_lich_replays_observed_burst_and_pulls_before_fixed_threshold(self):
        dk=unit('Udea',1,0);dk.mana=37;lich=unit('Ulic',2,100,544);lich.hp_max=575
        enemy=unit('ucry',3,400);m=Micro(lambda *a,**kw:None)
        args=([dk,lich],[enemy],783.73,lambda u:lich.handle,dist,lambda *p:True,(-5000,0))
        m.plan(*args);lich.hp=355
        moves=m.plan(*args[:2],786.355,*args[3:])
        self.assertGreater(lich.hp/lich.hp_max,.45);self.assertIn(lich.handle,moves)
        self.assertGreater(dist(moves[lich.handle],enemy),dist(lich,enemy))

    def test_old_damage_healing_and_single_sample_do_not_predict_burst(self):
        h=unit('Ulic',1,0,500);d=DamageTrend();d.observe([h],1);self.assertFalse(d.urgent(h))
        h.hp=300;d.observe([h],2);self.assertTrue(d.urgent(h))
        h.hp=500;d.observe([h],3);self.assertFalse(d.urgent(h))
        h.hp=300;d.observe([h],10);self.assertFalse(d.urgent(h))
        d.observe([],11);self.assertFalse(d.samples)

    def test_burst_triggers_transport_above_twenty_percent_but_no_threat_does_not(self):
        g,b,dk,allies,orders,e=strategy.Strategy0140Tests().portal()
        b.micro.damage.observe([dk],99);dk.hp=350;b.micro.damage.observe([dk],100)
        self.assertTrue(b.emergency_portal([dk,*allies],100));self.assertTrue(orders)
        g,b,dk,allies,orders,e=strategy.Strategy0140Tests().portal()
        b.micro.damage.observe([dk],99);dk.hp=350;b.micro.damage.observe([dk],100);e.x=3000
        self.assertFalse(b.emergency_portal([dk,*allies],100));self.assertFalse(orders)

class Consumable163Tests(unittest.TestCase):
    def test_lich_invulnerability_needs_low_dk_mana_and_handles_burst(self):
        for mana,expected in [(75,False),(74,True)]:
            g=consumables.Game();dk,h,_=g.heroes;dk.mana=mana;h.hp=350;g.bags[h.handle][0]='pnvl'
            c=Consumables(lambda *a,**kw:None)
            c.tick(g,g.army,[unit('hfoo',90,200)],1,{},urgent={h.handle})
            self.assertEqual(bool(g.orders),expected)

    def test_replenishment_waits_for_safety_and_buff_prevents_duplicates(self):
        g=consumables.Game();h=g.heroes[0];g.bags[h.handle][0]='rej3';c=Consumables(lambda *a,**kw:None)
        c.tick(g,g.army,[unit('hfoo',90,200)],1,{});self.assertFalse(g.orders)
        c.tick(g,g.army,[],5,{});self.assertEqual(g.orders,[('use','Udea','rej3')])
        g.bs[h.handle]=['BIrg'];c.tick(g,g.army,[],9,{})
        self.assertEqual(len(g.orders),1)

    def test_death_book_requires_combat_and_actual_new_summons_to_confirm(self):
        g=consumables.Game();h=g.heroes[0];h.hp=500;g.bags[h.handle][0]='fgsk';events=[]
        g.units=lambda side,codes:[u for u in g.army if u.type in codes]
        c=Consumables(lambda e,**kw:events.append(dict(event=e,**kw)))
        c.tick(g,g.army,[],1,{});self.assertFalse(g.orders)
        enemy=unit('hfoo',90,200);enemy.owner=1
        c.tick(g,g.army,[enemy],5,{})
        self.assertEqual(g.orders,[('use','Udea','fgsk')]);g.bags[h.handle][0]=None
        c.observe(g,6);self.assertFalse(any(e['event']=='consumable_effect_observed' for e in events))
        g.army.append(unit('nsce',99,100));c.observe(g,7)
        self.assertEqual(events[-1]['event'],'consumable_effect_observed')

if __name__=='__main__':unittest.main()
