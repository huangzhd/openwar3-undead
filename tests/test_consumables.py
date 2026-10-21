import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from test_upgrades_portal import UpgradeGame
from undead.consumables import Consumables,ScrollSupply,ITEMS
from undead.economy import Economy

class Game:
    dist=staticmethod(dist)
    def __init__(self):
        self.heroes=[unit('Udea',1,0,120),unit('Ulic',2,100,150),unit('Nbrn',3,150,600)]
        self.army=self.heroes+[unit('ucry',4,100,200)]
        self.bags={h.handle:[None]*6 for h in self.heroes};self.orders=[];self.cd={};self.bs={}
        self.food=50;self.gold=1000;self.effect=False;self.shop=unit('utom',20,0)
    def inventory(self,u):return self.bags[u.handle]
    def unit(self,h):return next((u for u in self.army if u.handle==h),None)
    def buffs(self,u):return self.bs.get(u.handle,[])
    def cooldown(self,u,a):return self.cd.get((u.handle,a),0)
    def resources(self):return dict(food_used=self.food,gold=self.gold)
    def use_item(self,h,slot):
        code=self.bags[h.handle][slot];self.orders.append(('use',h.type,code))
        if self.effect:
            self.bags[h.handle][slot]=None
            _,heal,mana,radius,buff=ITEMS[code]
            for u in self.army if radius else [h]:
                if radius and (u.type=='uobs' or self.dist(h,u)>radius):continue
                u.hp=min(u.hp_max,u.hp+heal);u.mana=min(u.mana_max,u.mana+mana)
                if buff:self.bs[u.handle]=[buff]
        return True
    def buy(self,shop,code):
        self.orders.append(('buy',code));self.gold-=250
        bag=self.bags[self.heroes[0].handle];bag[bag.index(None)]=code
        return True
    def give_item(self,h,slot,to):
        self.orders.append(('give',h.type,to.type));code=self.bags[h.handle][slot]
        self.bags[h.handle][slot]=None;bag=self.bags[to.handle];bag[bag.index(None)]=code
        return True

class ConsumableTests(unittest.TestCase):
    def setUp(self):
        self.g=Game();self.events=[];self.lock={}
        self.c=Consumables(lambda event,**kw:self.events.append(dict(event=event,**kw)))
    def step(self,now=1,foes=(),blocked=(),coil_needed=False,attacking=False):self.c.tick(self.g,self.g.army,foes,now,self.lock,blocked,coil_needed,attacking)
    def test_critical_invulnerability_precedes_potion_and_buff_prevents_repeat(self):
        g=self.g;dk=g.heroes[0];g.bags[dk.handle][:2]=['pghe','pnvu']
        self.step(1,[unit('hfoo',9,100)])
        self.assertEqual(g.orders,[('use','Udea','pnvu')]);self.assertGreater(self.lock[dk.handle],1)
        g.bs[dk.handle]=['Bvul'];self.step(5,[unit('hfoo',9,100)])
        self.assertEqual(g.orders[-1],('use','Udea','pghe'))
        self.assertTrue(any(e['event']=='consumable_effect_observed' and e['code']=='pnvu' for e in self.events))
    def test_no_waste_at_high_health_or_no_threat_or_unknown_cooldown(self):
        g=self.g;dk=g.heroes[0];g.bags[dk.handle][:3]=['pghe','pnvu','ankh'];dk.hp=500
        self.step();self.assertFalse(g.orders)
        dk.hp=100;g.cd[(dk.handle,'AIh2')]=None;self.step(5);self.assertFalse(g.orders)
        g.cd[(dk.handle,'AIh2')]=12;self.step(10,[unit('hfoo',9,2000)]);self.assertFalse(g.orders)
    def test_receipt_is_not_effect_and_retries_stop(self):
        g=self.g;g.bags[g.heroes[0].handle][0]='pghe'
        for t in range(1,30,4):self.step(t)
        self.assertEqual(len(g.orders),3)
        self.assertFalse(any(e['event']=='consumable_effect_observed' for e in self.events))
        self.assertTrue(any(e['event']=='consumable_effect_unconfirmed' for e in self.events))
    def test_healing_consumption_and_health_change_are_both_observed(self):
        g=self.g;g.effect=True;g.bags[g.heroes[0].handle][0]='pghe';self.step();self.step(2.5)
        self.assertEqual(g.heroes[0].hp,600)
        self.assertTrue(any(e['event']=='consumable_effect_observed' and e['consumed'] for e in self.events))
    def test_group_heal_excludes_statues_distant_units_and_prevents_same_tick_duplicates(self):
        g=self.g;dk,lich,_=g.heroes;g.bags[dk.handle][0]='shea';g.bags[lich.handle][0]='shea'
        for u in g.army:u.hp=u.hp_max
        dk.hp=200;g.army += [unit('uobs',9,10,1),unit('ucry',10,1000,1)]
        self.step();self.assertFalse(g.orders)
        lich.hp=200;self.step(5)
        self.assertEqual(g.orders,[('use','Udea','shea')])
        targets=self.events[-1]['targets'];self.assertNotIn((9,0),targets);self.assertNotIn((10,0),targets)
    def test_low_mana_potion_and_cast_or_teleport_protection(self):
        g=self.g;h=g.heroes[0];g.bags[h.handle][0]='pgma';h.mana=0
        self.step(blocked=[h.handle],coil_needed=True);self.assertFalse(g.orders)
        self.lock[h.handle]=8;self.step(5,coil_needed=True);self.assertFalse(g.orders)
        self.step(9,coil_needed=True);self.assertEqual(g.orders,[('use','Udea','pgma')])
    def test_mana_stone_restores_low_dk_mana_without_waiting_for_heal_target(self):
        g=self.g;dk=g.heroes[0];dk.mana=10;dk.mana_max=400
        g.bags[dk.handle][0]='mnst';g.effect=True
        self.step()
        self.assertEqual(g.orders,[('use','Udea','mnst')])
        self.assertEqual(dk.mana,310);self.assertNotIn('mnst',g.bags[dk.handle])
        self.step(7,coil_needed=True)
        effect=next(e for e in self.events if e['event']=='consumable_effect_observed')
        self.assertTrue(effect['consumed']);self.assertEqual(effect['gains'][0]['mana_gain'],300)
        self.assertEqual(len(g.orders),1)

    def test_restoration_and_combat_scrolls_avoid_existing_buffs(self):
        g=self.g;h=g.heroes[0];g.bags[h.handle][0]='sres';g.heroes[1].mana=0
        self.step();self.assertEqual(g.orders[-1],('use','Udea','sres'))
        g.bags[h.handle][0]='sror';self.step(6);self.assertEqual(len(g.orders),1)
        for u in g.army:g.bs[u.handle]=['Broa']
        foe=unit('hfoo',9,100);foe.owner=1
        self.step(10,[foe],attacking=True);self.assertEqual(len(g.orders),1)
        g.bs.clear();self.step(15,[foe],attacking=True);self.assertEqual(g.orders[-1],('use','Udea','sror'))

    def test_consumed_item_does_not_block_later_items_reusing_same_address(self):
        g=self.g;h=g.heroes[0];h.item_addrs=[12345,0,0,0,0,0];g.effect=True
        for t in (1,10,20,30):
            h.hp=120;g.bags[h.handle][0]='pghe';self.step(t);self.step(t+2)
            self.assertGreater(h.hp,500)
        self.assertEqual(len(g.orders),4)
    def test_group_scroll_can_save_one_critical_hero_under_threat(self):
        g=self.g;h=g.heroes[0]
        for u in g.army:u.hp=u.hp_max
        h.hp=100;g.bags[h.handle][0]='shea';self.step()
        self.assertFalse(g.orders)
        self.step(5,[unit('hfoo',9,100)])
        self.assertEqual(g.orders,[('use','Udea','shea')])
    def test_mana_potion_does_not_delay_dk_when_he_can_already_cast_coil(self):
        g=self.g;h=g.heroes[0];g.bags[h.handle][0]='pgma';h.mana=90
        self.step(coil_needed=True);self.assertFalse(g.orders)
        h.mana=74;h.mana_max=255;self.step(5,coil_needed=True);self.assertEqual(g.orders,[('use','Udea','pgma')])

    def test_combat_buff_does_not_block_another_heroes_emergency_group_heal(self):
        g=self.g;dk,lich,dark=g.heroes;g.bags[dk.handle][0]='spro';g.bags[lich.handle][0]='shea'
        self.step(1,[unit('hfoo',9,100)])
        self.assertEqual(g.orders,[('use','Udea','spro'),('use','Ulic','shea')])
        g.bags[dark.handle][0]='spro';self.step(1.5,[unit('hfoo',9,100)])
        self.assertEqual(len(g.orders),2)

    def test_blue_potion_goes_to_low_mana_dk_without_a_coil_target(self):
        g=self.g;dk,lich,_=g.heroes;g.bags[dk.handle][0]='pman';g.bags[lich.handle][0]='pgma';dk.mana=lich.mana=0
        self.step();self.assertEqual(g.orders,[('use','Udea','pman')])

    def test_roar_only_in_attack_phase_near_opponent_not_creeps(self):
        g=self.g;g.bags[g.heroes[0].handle][0]='sror';foe=unit('hfoo',9,100);foe.owner=1
        self.step(1,[foe]);self.assertFalse(g.orders)
        foe.owner=12;self.step(5,[foe],attacking=True);self.assertFalse(g.orders)
        foe.owner=1;foe.x=2000;self.step(9,[foe],attacking=True);self.assertFalse(g.orders)
        foe.x=100;self.step(13,[foe],attacking=True);self.assertEqual(g.orders,[('use','Udea','sror')])

class ScrollTests(unittest.TestCase):
    def setUp(self):
        self.g=Game();self.events=[];self.lock={};self.s=ScrollSupply(lambda event,**kw:self.events.append(dict(event=event,**kw)))
        for h in self.g.heroes:h.hp=h.hp_max
    def step(self,t=1,reserve=0,safe=True):self.s.tick(self.g,self.g.heroes,[self.g.shop],t,reserve,self.lock,safe)
    def test_actual_fifty_and_five_hundred_after_reserve(self):
        g=self.g;g.food=49;self.step();self.assertFalse(g.orders)
        g.food=50;g.gold=999;self.step(5,500);self.assertFalse(g.orders)
        g.gold=1000;self.step(9,500);self.assertEqual(g.orders,[('buy','shea')]);self.assertEqual(g.gold,750)
    def test_one_at_a_time_lich_first_then_balance_and_cap_three(self):
        g=self.g;g.gold=2000
        for t in range(1,40,4):self.step(t)
        self.assertEqual([b.count('shea') for b in g.bags.values()],[1,1,1])
        self.assertEqual(g.gold,1250)
        self.assertEqual(sum(e['event']=='healing_scroll_purchase_confirmed' for e in self.events),3)
    def test_no_purchase_in_danger_full_bag_or_reserved_orb_slot(self):
        self.step(safe=False);self.assertFalse(self.g.orders)
        lich=self.g.heroes[1];self.g.bags[lich.handle]=['rin1']*5+[None]
        self.step(5);self.assertFalse(self.g.orders)
        self.g.bags[lich.handle]=['ocor']+['rin1']*4+[None]
        self.step(9);self.assertEqual(self.g.orders,[('buy','shea')])
    def test_receipt_only_purchase_is_bounded_and_not_confirmed(self):
        g=self.g;g.buy=lambda *a:g.orders.append(('receipt',)) or True
        for t in range(1,60,4):self.step(t)
        self.assertEqual(len(g.orders),3)
        self.assertFalse(any(e['event']=='healing_scroll_purchase_confirmed' for e in self.events))
    def test_restore_scrolls_count_toward_balanced_cap(self):
        for b in self.g.bags.values():b[0]='sres'
        for t in range(1,30,4):self.step(t)
        self.assertEqual([b.count('sres') for b in self.g.bags.values()],[1,1,1])
        self.assertFalse(any(o[0]=='buy' for o in self.g.orders))
    def test_budget_reserves_core_replacements_tech_portal_and_absent_heroes(self):
        g=UpgradeGame();e=Economy(lambda *a,**k:None);e.ever_heroes={h.type for h in g.my_heroes()}
        e.upkeep_released=True
        baseline=e.optional_reserve(g,500)
        g.own=[u for u in g.own if u.type!='uobs']
        self.assertEqual(e.optional_reserve(g,500)-baseline,400)
        g.invs['Udea']=[None]*6;self.assertEqual(e.optional_reserve(g,500)-baseline,750)
        g.own=[u for u in g.own if u.type!='Ulic'];self.assertEqual(e.optional_reserve(g,500),float('inf'))

    def test_controller_only_buys_incidentally_at_home_without_changing_route(self):
        from undead.controller import Controller
        from undead.policy import Action
        g=self.g;c=Controller(g,lambda *a,**k:None);c.home=unit('unp2',99,-5000)
        c.economy.optional_reserve=lambda *a:0;c.action=Action.RETREAT
        c.shop_goal=(700,800)
        c.restock_scrolls(1,g.heroes,[g.shop]);self.assertFalse(g.orders)
        c.home.x=0;g.shop.type='ngme';c.economy.upkeep_released=True
        c.restock_scrolls(5,g.heroes,[g.shop]);self.assertFalse(g.orders)
        g.shop.type='utom';c.restock_scrolls(9,g.heroes,[g.shop])
        self.assertEqual(g.orders,[('buy','shea')]);self.assertEqual(c.shop_goal,(700,800))


class BluePotionTests(unittest.TestCase):
    def test_pickup_prioritizes_farther_dk(self):
        import test_lich_items_0129 as cases
        for code in ('pman','pgma'):
            g,loot,heroes,picked,ground,_=cases.LichOutputTests().game(code)
            heroes[0].x=700;heroes[1].x=0;loot.tick(g,heroes,[],1)
            self.assertEqual(picked,['Udea'])
    def test_safe_handoff_to_dk_requires_observed_inventory_change(self):
        import test_equipment as cases
        for code in ('pman','pgma'):
            case=cases.EquipmentTests();g,e,events=case.setup_game();g.inv[g.lich.handle][0]=code
            self.assertTrue(e.tick(g,g.heroes,[],1,{}))
            self.assertFalse(any(n=='equipment_transfer_confirmed' for n,_ in events))
            case.observed_transfer(g);e.tick(g,g.heroes,[],4,{})
            self.assertIn(code,g.inv[g.dk.handle]);self.assertNotIn(code,g.inv[g.lich.handle])
            self.assertTrue(any(n=='equipment_transfer_confirmed' for n,_ in events))
    def test_blue_handoff_never_displaces_full_dk_or_crosses_combat(self):
        import test_equipment as cases
        g,e,_=cases.EquipmentTests().setup_game();g.inv[g.lich.handle][0]='pgma';g.inv[g.dk.handle]=['stwp']*6
        self.assertFalse(e.tick(g,g.heroes,[],1,{}));self.assertFalse(g.transfers)
        g.inv[g.dk.handle][1]=None
        self.assertFalse(e.tick(g,g.heroes,[unit('hfoo',9,100)],5,{}));self.assertFalse(g.transfers)
    def test_coil_need_requires_ready_learned_spell_legal_near_target_and_low_mana(self):
        from undead.controller import Controller
        from undead.policy import Action
        g=Game();dk,lich,_=g.heroes;dk.mana=0
        g.units=lambda owner,codes:[u for u in g.army if u.type in codes]
        g.abilities=lambda h:[dict(code='AUdc',level=1)]
        g.current_target=lambda h:None
        c=Controller(g,lambda *a,**k:None)
        c.player_contact=[unit('hfoo',90,100)]
        self.assertTrue(c.coil_needed(dk))
        for u in g.army:u.hp=u.hp_max
        self.assertFalse(c.coil_needed(dk))
        foe=unit('hfoo',9,100);g.current_target=lambda h:foe;c.battle_enemies=[foe]
        self.assertTrue(c.coil_needed(dk))
        foe.type='ucry';self.assertFalse(c.coil_needed(dk))
        foe.type='hfoo';foe.x=900;self.assertFalse(c.coil_needed(dk))
        foe.x=100;c.action=Action.RETREAT;self.assertFalse(c.coil_needed(dk))
        lich.hp=100;self.assertTrue(c.coil_needed(dk))
        dk.mana=75;self.assertFalse(c.coil_needed(dk))
        dk.mana=0;g.cd[(dk.handle,'AUdc')]=2;self.assertFalse(c.coil_needed(dk))
        g.cd[(dk.handle,'AUdc')]=None;self.assertFalse(c.coil_needed(dk))
        g.cd[(dk.handle,'AUdc')]=0;g.abilities=lambda h:[];self.assertFalse(c.coil_needed(dk))
