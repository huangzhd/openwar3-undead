import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.controller import Controller
from undead.policy import Action,Situation,choose_rule
from undead.consumables import Consumables
from test_micro_loot import unit,dist
import test_opening_safety_0131 as emergency
import test_consumables as consumables

class SafetyTests(unittest.TestCase):
    def test_visible_destination_army_blocks_unsafe_defense(self):
        s=Situation(1140,threatened=True,army_hp=3000,local_enemy_hp=2000,base_enemy_hp=8000)
        self.assertEqual(choose_rule(s),Action.RETREAT)
        s.base_enemy_hp=2000
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.threatened=False;s.base_enemy_hp=8000
        self.assertEqual(choose_rule(s),Action.CREEP)

    def test_archived_visible_base_force_prevents_return_to_siege(self):
        import math
        d=json.loads((Path(__file__).parent/'fixtures/lr-late-0163.json').read_text())
        e=next(e for e in d['frames'] if 1139<e['clock']<1140)
        s=Situation(e['clock'],threatened=True,army_hp=e['army_hp'],local_enemy_hp=e['enemy_hp'])
        self.assertEqual(choose_rule(s),Action.DEFEND)
        s.base_enemy_hp=sum(u['hp'] for u in e['enemies'] if math.dist((u['x'],u['y']),d['home'])<=1600)
        self.assertEqual(choose_rule(s),Action.RETREAT)

    def test_safety_interrupts_full_controller_before_five_seconds(self):
        g,b,dk,allies,orders,clock=emergency.EmergencyTests().controller()
        g.enemies()[0].hp=5000
        b.last_decide=clock[0]-.1;b.action=Action.CREEP
        b.emergency_portal=lambda *a:True;b.protect_portal_allies=lambda *a:None
        b.tick(forced=Action.ATTACK)
        self.assertEqual(b.action,Action.RETREAT)

    def test_base_threat_outside_army_radius_interrupts_tick(self):
        g,b,dk,allies,orders,clock=emergency.EmergencyTests().controller()
        foe=g.enemies()[0];foe.x=-5000;foe.hp=8000;foe.visible_to=lambda me:True
        b.last_decide=clock[0]-.1;b.action=Action.ATTACK
        b.emergency_portal=lambda *a:True;b.protect_portal_allies=lambda *a:None
        b.tick(forced=Action.DEFEND)
        self.assertEqual(b.situation.local_enemy_hp,0)
        self.assertEqual(b.action,Action.RETREAT)

class RecoveryTests(unittest.TestCase):
    def make(self):
        g=consumables.Game();dk,lich,third=g.heroes
        army=g.heroes+[unit('ucry',100+i,0) for i in range(6)]+[unit('uobs',200,0)]
        g.army=army
        for u in army:u.hp=u.hp_max;u.mana=200
        g.my_heroes=lambda:g.heroes;g.enemies=lambda:[];g.creeps=lambda:[]
        g.path_distance=dist;g.nearest=lambda units,p:units[0] if units else None
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=0,y=0);b.action=Action.ATTACK
        b.economy.revival_pending=lambda g:set();b.economy.ready=lambda g,code:[g.shop]
        b.creeping.safe_route=lambda *a:True;b.clear_full_shop_heroes=lambda *a:False
        moves=[];b.go=lambda army,point,now:moves.append(point)
        return g,b,army,dk,lich,moves

    def test_full_health_field_army_keeps_attacking_with_empty_dk_mana(self):
        for recovery in (False,True):
            g,b,army,dk,lich,moves=self.make();b.recovery_pending=recovery;dk.mana=0;lich.mana=0
            for u in army:u.x=5000
            b.creep_strength=army;g.bags[dk.handle][0]='stwp'
            self.assertTrue(b.prepare_attack(army,500))
            self.assertFalse(moves);self.assertFalse(g.orders)

    def test_actual_battle_damage_still_requires_recovery(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True
        for u in army:u.x=5000;u.hp=u.hp_max*.4
        b.creep_strength=army
        self.assertFalse(b.prepare_recovery(army,500));self.assertTrue(moves)

    def test_archived_low_mana_blocks_departure_even_with_scroll(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True
        rows=json.loads((Path(__file__).parent/'fixtures/lr-late-0163.json').read_text())['summaries']
        old=next(s for s in rows if 1038<s['clock']<1039)
        dk.mana=next(h['mana'] for h in old['heroes'] if h['type']=='Udea')
        g.bags[dk.handle][0]='stwp'
        self.assertFalse(b.prepare_attack(army,old['clock']))
        self.assertIn(('buy','pman'),g.orders)
        self.assertTrue(b.recovery_pending)

    def test_protected_dk_is_still_checked_before_departure(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True;dk.mana=0;g.gold=0
        g.bags[dk.handle][0]='stwp'
        self.assertFalse(b.prepare_attack([u for u in army if u is not dk],500))
        self.assertTrue(b.recovery_pending)

    def test_pulling_units_are_not_dropped_from_recovery_health(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True;b.creep_strength=army
        lich.hp=lich.hp_max*.3
        for u in army:
            if u.type=='ucry':u.hp=u.hp_max*.4
        self.assertFalse(b.prepare_recovery([u for u in army if u.type not in {'Ulic','ucry'}],500))
        self.assertTrue(b.recovery_pending)

    def test_replenished_army_releases_departure_and_clears_gate(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True;g.bags[dk.handle][0]='stwp'
        lich.mana=100
        self.assertFalse(b.prepare_attack(army,500))
        lich.mana=125;dk.mana=75
        self.assertTrue(b.prepare_attack(army,501));self.assertFalse(b.recovery_pending)

    def test_missing_fiends_statue_or_wounded_hero_hold_regroup(self):
        for missing in ('fiend','statue','health'):
            g,b,army,dk,lich,moves=self.make();b.recovery_pending=True
            if missing=='fiend':army.remove(next(u for u in army if u.type=='ucry'))
            elif missing=='statue':army.remove(next(u for u in army if u.type=='uobs'))
            else:lich.hp=lich.hp_max*.5
            self.assertFalse(b.prepare_recovery(army,500));self.assertTrue(moves)

    def test_current_combat_is_not_cancelled_by_recovery(self):
        g,b,army,dk,lich,moves=self.make();b.recovery_pending=True;dk.mana=0
        b.battle_enemies=[unit('hfoo',999,100)]
        self.assertTrue(b.prepare_recovery(army,500));self.assertFalse(g.orders);self.assertFalse(moves)

    def test_mana_purchase_guards_preserve_budget_and_inventory(self):
        for mode in ('revival','money','full','stock_time','unsafe','existing'):
            g,b,army,dk,lich,moves=self.make();dk.mana=0;now=500
            if mode=='revival':b.economy.revival_pending=lambda g:{'Nbrn'}
            elif mode=='money':g.gold=199
            elif mode=='full':g.bags[dk.handle]=['rat6']*6
            elif mode=='stock_time':now=400
            elif mode=='unsafe':g.enemies=lambda:[unit('hfoo',999,100)]
            else:g.bags[dk.handle][0]='pman'
            b.battle_shop.prepare_mana(b,army,dk,now)
            self.assertFalse(g.orders,mode)

    def test_purchase_receipt_without_inventory_is_bounded(self):
        g,b,army,dk,lich,moves=self.make();dk.mana=0
        g.buy=lambda shop,code:g.orders.append(('buy',code)) or True
        for now in range(500,530,4):
            b.battle_shop.observe(g,now);b.battle_shop.prepare_mana(b,army,dk,now)
        self.assertEqual(g.orders,[('buy','pman')]*3)
        self.assertFalse(b.prepare_recovery(army,530))

    def test_wrong_recipient_is_transferred_before_another_purchase(self):
        g,b,army,dk,lich,moves=self.make();dk.mana=0;g.bags[lich.handle][0]='pman'
        b.battle_shop.prepare_mana(b,army,dk,500)
        self.assertIn('pman',g.inventory(dk));self.assertNotIn('pman',g.inventory(lich))
        self.assertFalse(any(o[0]=='buy' for o in g.orders))

    def test_predeparture_mana_use_requires_real_consumption_and_gain(self):
        g,b,army,dk,lich,moves=self.make();dk.mana=10;g.bags[dk.handle][0]='pman'
        events=[];c=Consumables(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        g.effect=True;lock={}
        c.tick(g,army,[],500,lock,preparing=True)
        c.observe(g,501)
        self.assertEqual(dk.mana,160);self.assertNotIn('pman',g.inventory(dk))
        self.assertTrue(any(e['event']=='consumable_effect_observed' and e['consumed'] and e['gains'][0]['mana_gain']==150 for e in events))

if __name__=='__main__':unittest.main()
