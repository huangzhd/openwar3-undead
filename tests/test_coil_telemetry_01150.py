"""Synthetic SDK snapshots reproduce a known skill disappearing at slot capacity.

The upstream raw NI 202904 artifacts are not on this machine; do not label
this fixture a captured replay or the slot-cap explanation a proven cause.
"""
import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
import bootstrap
from undead.game_view import Game, SDKGame
from undead.controller import Controller
from undead.nc_combo import NCCombo
from test_micro_loot import unit, dist
import test_battle_shop_0163 as shop


class CoilTelemetryTests(unittest.TestCase):
    def scene(self):
        dk=unit('Udea',1,0,600);lich=unit('Ulic',2,80,200)
        foe=unit('Obla',3,300,100)
        own=[dk,lich];all_units={u.handle:u for u in [*own,foe]}
        for u in all_units.values():
            u.owner=0 if u in own else 1;u.alive=True;u.has_detail=True
            u.handle_lo,u.handle_hi=u.handle;u.items=[None]*6;u.buffs=[];u.abilities=[]
            u.ability=lambda code,u=u:next((a for a in u.abilities if a.code==code),None)
        dk.abilities=[N(code='AUdc',level=2,cooldown=0,flags=0)]
        g=Game.__new__(Game);clock=[530.33];orders=[];logs=[]
        g.snapshot=lambda *a,**k:N(by_handle=all_units,unit_by_handle=all_units.get)
        g.clock=lambda:clock[0];g.me=lambda:0;g.dist=dist
        g.units=lambda owner,codes:[u for u in own if u.type in codes]
        g.creeps=lambda:[]
        g.enemies=lambda:[foe];g.current_target=lambda u:None
        g.my_heroes=lambda:own
        log=lambda event,**kw:logs.append(dict(event=event,**kw))
        g.observe_coil(own,clock[0],log)
        return g,dk,lich,foe,own,clock,orders,logs

    def truncate(self,g,dk,clock):
        clock[0]=545.83
        dk.items[0]='sbch'
        # 12 different equipment/internal skills, no AUdc/AUau/AInv.
        dk.abilities=[N(code=f'AI{i:02}',level=1,cooldown=0,flags=0) for i in range(12)]
        self.assertFalse(g.coil_ready(dk,clock[0]))
        clock[0]+=6

    def send(self,orders):
        return patch.object(SDKGame,'cast',side_effect=lambda u,s,**kw:orders.append((s,kw['target'].handle)) or True)

    def test_missing_telemetry_resumes_real_heal_path_without_faking_cd(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        b=Controller(g,lambda *a,**k:None);b.player_contact=[e]
        with self.send(orders):b.heal_allies(own,t[0])
        self.assertEqual(orders,[('deathcoil',l.handle)])
        self.assertIsNone(g.cooldown(d,'AUdc'))
        self.assertFalse(any(a['code']=='AUdc' for a in g.abilities(d)))
        self.assertEqual(logs[-1]['event'],'coil_telemetry_fallback_attempt')
        self.assertIsNone(logs[-1]['cooldown'])
        self.assertIn('sbch',g.inventory(d))

    def test_damage_and_finisher_both_use_recovery(self):
        for mode in ('damage','finisher','rescue'):
            g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t);l.hp=600
            b=Controller(g,lambda *a,**k:None)
            with self.send(orders):
                if mode=='damage':
                    e.owner=12;e.type='nmrl';e.is_hero=False;d.mana=d.mana_max
                    b.fight([d],[e],t[0])
                elif mode=='finisher':
                    NCCombo(lambda *a,**k:None).try_cast(g,[d],[e],t[0],{})
                else:
                    l.hp=150;b.player_contact=[e]
                    self.assertTrue(b.rescue_coil_ready(d,t[0]))
                    b.heal_allies(own,t[0],[l])
            self.assertEqual(orders,[('deathcoil',l.handle if mode=='rescue' else e.handle)],mode)

    def test_receipt_alone_stops_after_three_attempts_across_targets(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        with self.send(orders):
            for i in range(3):
                self.assertTrue(g.cast(d,'deathcoil',target=l if i%2 else e))
                self.assertFalse(g.cast(d,'deathcoil',target=l))
                t[0]+=9
            self.assertFalse(g.cast(d,'deathcoil',target=l))
            t[0]+=120;self.assertFalse(g.cast(d,'deathcoil',target=e))
        self.assertEqual(len(orders),3)
        self.assertFalse(any(x.get('mana_spent') for x in logs))

    def test_observed_mana_spend_allows_later_cast_but_keeps_full_spacing(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        with self.send(orders):
            self.assertTrue(g.cast(d,'deathcoil',target=l))
            t[0]+=1;d.mana-=74
            self.assertFalse(g.coil_ready(d,t[0]))
            self.assertTrue(any(x.get('mana_spent') for x in logs))
            t[0]+=7.9;self.assertFalse(g.coil_ready(d,t[0]))
            t[0]+=.1;self.assertTrue(g.cast(d,'deathcoil',target=e))
        self.assertEqual(len(orders),2)

    def test_rejected_commands_never_reset_budget_on_unrelated_mana_loss(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        with patch.object(SDKGame,'cast',return_value=False) as cast:
            for i in range(3):
                d.mana=300
                self.assertFalse(g.cast(d,'deathcoil',target=l))
                t[0]+=1;d.mana-=75;g.coil_ready(d,t[0]);t[0]+=8
            self.assertFalse(g.cast(d,'deathcoil',target=e))
        self.assertEqual(cast.call_count,3)
        self.assertFalse(g.coil_ready(d,t[0]+120))
        self.assertFalse(any(x.get('mana_spent') for x in logs))

    def test_present_but_unknown_cooldown_is_not_treated_as_truncation(self):
        g,d,l,e,own,t,orders,logs=self.scene()
        d.abilities[0].cooldown=None
        self.assertFalse(g.coil_ready(d,t[0]))
        t[0]+=120;self.assertFalse(g.coil_ready(d,t[0]))

    def test_remembered_long_cooldown_survives_missing_rows(self):
        g,d,l,e,own,t,orders,logs=self.scene()
        d.abilities[0].cooldown=30;g.observe_coil(own,t[0],lambda *a,**k:None)
        self.truncate(g,d,t)
        self.assertFalse(g.coil_ready(d,t[0]))
        t[0]=560.33;self.assertTrue(g.coil_ready(d,t[0]))

    def test_normal_cast_just_before_truncation_cannot_duplicate(self):
        g,d,l,e,own,t,orders,logs=self.scene()
        with self.send(orders):self.assertTrue(g.cast(d,'deathcoil',target=l))
        d.abilities=[N(code=f'AI{i:02}',level=1,cooldown=0,flags=0) for i in range(12)]
        t[0]+=1;d.mana-=74;self.assertFalse(g.coil_ready(d,t[0]))
        t[0]+=6;self.assertFalse(g.coil_ready(d,t[0]))
        t[0]+=2;self.assertTrue(g.coil_ready(d,t[0]))

    def test_unknown_unlearned_empty_or_disabled_never_become_ready(self):
        for case in ('unseen','level_zero','empty','silenced','dead','no_detail','enemy','new_handle','rewind'):
            g,d,l,e,own,t,orders,logs=self.scene()
            if case=='unseen':g._coil_telemetry=None;del g._coil_telemetry
            if case=='level_zero':
                d.abilities[0].level=0;g.observe_coil(own,t[0],lambda *a,**k:None)
            self.truncate(g,d,t)
            if case=='empty':d.abilities.clear()
            if case=='silenced':d.buffs=['BNsi']
            if case=='dead':d.alive=False
            if case=='no_detail':d.has_detail=False
            if case=='enemy':d.owner=1
            if case=='new_handle':d.handle=(1,2)
            if case=='rewind':t[0]=0
            self.assertFalse(g.coil_ready(d,t[0]),case)

    def test_live_cooldown_and_unlearned_level_override_memory(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        d.abilities=[N(code='AUdc',level=3,cooldown=4,flags=0)]
        self.assertFalse(g.coil_ready(d,t[0]));self.assertEqual(g.coil_level(d),3)
        d.abilities[0].cooldown=0;self.assertTrue(g.coil_ready(d,t[0]))
        d.abilities[0].level=0;g.observe_coil(own,t[0],lambda *a,**k:None)
        self.truncate(g,d,t);self.assertFalse(g.coil_ready(d,t[0]))

    def test_lost_hero_discards_history_and_unknown_cd_does_not_defer_escape(self):
        g,d,l,e,own,t,orders,logs=self.scene();self.truncate(g,d,t)
        b=Controller(g,lambda *a,**k:None)
        self.assertFalse(b.wait_for_rescue_coil(d,l,t[0]))
        g.observe_coil([],t[0],lambda *a,**k:None)
        t[0]+=10;self.assertFalse(g.coil_ready(d,t[0]))


class VampiricAuraSaleTests(unittest.TestCase):
    def test_sell_any_holder_requires_inventory_loss_and_refund(self):
        for who in ('dk','lich','dark'):
            for result in ('receipt','removed','sold'):
                g,b,s,events=shop.ShoppingTests().make();h=getattr(g,who);h.x=0
                g.bags[h.handle][1]='sbch'
                def sell(hero,slot,target):
                    if result!='receipt':g.bags[hero.handle][slot]=None
                    if result=='sold':g.gold+=200
                    return True
                g.sell_item=sell
                self.assertTrue(s.sell_nearby(b,g.heroes,[],10));s.observe(g,14)
                self.assertEqual(events[-1]['event'],'shop_transaction_confirmed' if result=='sold' else 'shop_transaction_unconfirmed')

    def test_sale_does_not_send_army_home_or_trade_under_threat(self):
        g,b,s,events=shop.ShoppingTests().make();g.dk.x=1000;g.bags[g.dk.handle][1]='sbch'
        self.assertFalse(s.sell_nearby(b,g.heroes,[],10));self.assertFalse(g.orders)
        g.dk.x=0;enemy=unit('ogru',99,100)
        self.assertFalse(s.sell_nearby(b,g.heroes,[enemy],11));self.assertFalse(g.orders)


if __name__=='__main__':unittest.main()
