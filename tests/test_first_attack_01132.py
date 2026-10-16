import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_battle_shop_0163 as shop_tests
from undead.controller import Controller
from undead.attack_supplies import AttackSupplies
from undead.illusion_front import IllusionFront,RealArmyView
from undead.policy import Action,Situation,attack_ready


class SuppliesTests(unittest.TestCase):
    def scene(self):
        g,b,shop,events=shop_tests.ShoppingTests().make()
        b.first_attack_all_in=True;b.battle_shop=shop;b.first_attack_supply=AttackSupplies(shop.log)
        g.dk.x=0
        def sell(hero,slot,target):
            code=g.bags[hero.handle][slot];g.bags[hero.handle][slot]=None;g.gold+=175
            g.orders.append(('sell',code));return True
        def buy(target,code):
            bag=g.bags[g.dk.handle];bag[bag.index(None)]=code;g.gold-=200
            g.orders.append(('buy',code));return True
        g.sell_item=sell;g.buy=buy
        return g,b,events

    def test_default_controller_disables_portal_and_repurchase(self):
        b=Controller(N(),lambda *a,**k:None)
        self.assertTrue(b.first_attack_all_in);self.assertFalse(b.economy.allow_tp)
        self.assertFalse(b.emergency_portal([],500))

    def test_sale_then_purchase_requires_real_dk_inventory(self):
        g,b,events=self.scene();s=b.first_attack_supply
        g.dk.mana=50;g.bags[g.lich.handle][0]='ocor'
        self.assertEqual(s.reserve(b,3),200)
        s.tick(b,g.heroes,[],500,3);self.assertFalse(s.confirmed)
        b.battle_shop.observe(g,501)
        s.tick(b,g.heroes,[],504,3);self.assertFalse(s.confirmed)
        b.battle_shop.observe(g,505)
        self.assertFalse(s.tick(b,g.heroes,[],508,3))
        self.assertTrue(s.confirmed)
        self.assertEqual(g.orders,[('sell','stwp'),('buy','pman')])
        self.assertEqual(s.reserve(b,3),0)

    def test_rejected_or_effectless_sale_cannot_report_ready(self):
        g,b,events=self.scene();g.sell_item=lambda *a:True;s=b.first_attack_supply
        for now in (500,504,508,512,592):
            b.battle_shop.observe(g,now);s.tick(b,g.heroes,[],now,3)
        self.assertFalse(s.confirmed);self.assertTrue(s.done)
        self.assertIn('stwp',g.inventory(g.dk));self.assertNotIn('pman',g.inventory(g.dk))

    def test_supply_does_not_sell_before_tier_three_or_under_attack(self):
        g,b,_=self.scene();s=b.first_attack_supply
        self.assertFalse(s.tick(b,g.heroes,[],300,2));self.assertFalse(g.orders)
        enemy=unit('hfoo',90,100);enemy.owner=1
        self.assertFalse(s.tick(b,g.heroes,[enemy],500,3));self.assertFalse(g.orders)

    def test_direct_lich_orb_does_not_skip_supply_preparation(self):
        s=Situation(500,tier=3,lich=True,orb=True,third_hero=True,supplies_ready=False)
        self.assertFalse(attack_ready(s))
        s.supplies_ready=True
        self.assertTrue(attack_ready(s))

    def test_defense_does_not_hoard_supply_gold(self):
        g,b,_=self.scene();b.action=Action.DEFEND
        self.assertEqual(b.first_attack_supply.reserve(b,3),0)

    def test_ordinary_shop_cannot_sell_portal_or_illusion_wand(self):
        g,b,_=self.scene();g.bags[g.dk.handle][1]='will'
        for code in ('stwp','will'):
            self.assertFalse(b.battle_shop.transact(g,g.dk,code,'sell',500,b.cast_until,g.home))
        self.assertFalse(g.orders)


class IllusionTests(unittest.TestCase):
    def scene(self,spawn=True):
        dk=unit('Udea',1,0,600);lich=unit('Ulic',2,-100);enemy=unit('ucry',90,900);enemy.owner=1
        own=[dk,lich];bag=['will']+[None]*5;events=[];orders=[]
        manager=IllusionFront(lambda e,**kw:events.append(dict(event=e,**kw)))
        def cast(h,slot,target):
            self.assertIs(target,dk)
            orders.append(('wand',target.handle))
            if spawn:
                clone=unit('Udea',len(own)+10,dk.x+60);clone.buffs=['BIil'];own.append(clone)
            if sum(o[0]=='wand' for o in orders)==3:bag[0]=None
            return True
        raw=N(my_heroes=lambda:own,my_units=lambda:own,my_army=lambda:own,
            units=lambda side,codes:[u for u in own if u.type in codes],unit=lambda h:next((u for u in own if u.handle==h),None),
            inventory=lambda h:bag if h is lich else [None]*6,me=lambda:0,dist=dist,
            path_distance=dist,buffs=lambda u:getattr(u,'buffs',[]),cooldown=lambda *a:0,
            use_item=cast,attack_move=lambda u,x,y:orders.append(('screen',u.handle,(x,y))) or True,
            enemies=lambda:[enemy],current_target=lambda e:None)
        b=N(g=RealArmyView(raw,manager.handles),action=Action.ATTACK,micro=N(pulling=set()),cast_until={})
        return b,manager,raw,dk,lich,enemy,own,events,orders

    def test_three_observed_copies_screen_without_replacing_real_dk(self):
        b,s,g,dk,lich,e,own,events,orders=self.scene()
        for now in (500,503,506):
            s.tick(b,b.g.my_heroes(),[e],now);s.observe(g,now+1)
        s.tick(b,b.g.my_heroes(),[e],509)
        self.assertEqual(s.created,3);self.assertEqual(b.g.my_heroes(),[dk,lich])
        self.assertEqual(b.g.units('me',{'Udea'}),[dk])
        self.assertEqual(len([o for o in orders if o[0]=='wand']),3)
        screens=[o for o in orders if o[0]=='screen'][-3:]
        self.assertEqual(len({o[2] for o in screens}),3)
        self.assertTrue(all(o[1]!=dk.handle and o[2][0]>dk.x for o in screens))

    def test_receipt_without_new_units_never_fabricates_copies(self):
        b,s,g,dk,lich,e,own,events,orders=self.scene(False)
        s.tick(b,own,[e],500);s.observe(g,505)
        self.assertEqual(s.created,0);self.assertFalse(s.handles)
        self.assertTrue(any(e['event']=='dk_illusion_unconfirmed' for e in events))

    def test_no_wand_spent_on_creeps_or_distant_march(self):
        b,s,g,dk,lich,e,own,events,orders=self.scene()
        e.owner=12;s.tick(b,own,[e],500)
        e.owner=1;e.x=5000;s.tick(b,own,[e],503)
        b.action=Action.CREEP;e.x=500;s.tick(b,own,[e],506)
        self.assertFalse(orders)

    def test_existing_real_hero_handles_are_not_misidentified(self):
        b,s,g,dk,lich,e,own,events,orders=self.scene(False)
        s.tick(b,own,[e],500);s.observe(g,501)
        self.assertFalse(s.handles);self.assertEqual(b.g.my_heroes(),[dk,lich])

    def test_front_order_alone_is_not_tanking_evidence(self):
        b,s,g,dk,lich,e,own,events,orders=self.scene()
        s.tick(b,own,[e],500);s.observe(g,501);s.observe(g,502)
        self.assertFalse(any(e['event']=='dk_illusion_pressure_observed' for e in events))
        clone=own[-1];clone.hp-=40;g.current_target=lambda e:clone
        s.observe(g,503)
        evidence=[e for e in events if e['event']=='dk_illusion_pressure_observed']
        self.assertEqual(evidence[-1]['hp_delta'],-40)
        self.assertEqual(evidence[-1]['visible_targeters'],[e.handle])


if __name__=='__main__':unittest.main()
