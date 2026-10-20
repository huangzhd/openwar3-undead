import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_coil_telemetry_01150 as coil
import test_chime_poison_01155 as chime
from undead.controller import Controller
from undead.nc_combo import NCCombo
from undead.policy import Action


class SparseRecoveryTests(unittest.TestCase):
    def scene(self,code='lhst'):
        scene=coil.CoilTelemetryTests().scene()
        g,d,l,e,own,t,orders,logs=scene
        rows=json.loads((Path(__file__).parent/'fixtures/aura_telemetry_210543.json').read_text(encoding='utf-8'))['cases']
        case=next(c for c in rows if c['item']==code)
        d.items=case['holding']['inventory']
        d.abilities=[N(**a) for a in case['holding']['abilities']]
        self.assertFalse(g.coil_ready(d,t[0]))
        t[0]+=5.99;self.assertFalse(g.coil_ready(d,t[0]))
        t[0]+=.01
        return scene

    def test_actual_single_aura_snapshot_allows_heal_and_finisher(self):
        for item in ('lhst','sbch'):
            for mode in ('heal','finisher'):
                g,d,l,e,own,t,orders,logs=self.scene(item)
                b=Controller(g,lambda *a,**k:None);b.player_contact=[e]
                with coil.CoilTelemetryTests().send(orders):
                    if mode=='heal':b.heal_allies(own,t[0])
                    else:l.hp=l.hp_max;NCCombo(lambda *a,**k:None).try_cast(g,[d],[e],t[0],{})
                self.assertEqual(orders,[('deathcoil',l.handle if mode=='heal' else e.handle)])
                self.assertIsNone(g.cooldown(d,'AUdc'))
                self.assertEqual([a['code'] for a in g.abilities(d)],['AIad' if item=='lhst' else 'AIav'])

    def test_sparse_failure_cap_survives_item_change_and_long_wait(self):
        g,d,l,e,own,t,orders,logs=self.scene()
        with coil.CoilTelemetryTests().send(orders):
            for i in range(3):
                self.assertTrue(g.cast(d,'deathcoil',target=l))
                t[0]+=8.9;self.assertFalse(g.cast(d,'deathcoil',target=e))
                t[0]+=.1
            d.items[0]='sbch';d.abilities=[N(code='AIav',level=1,cooldown=0,flags=0)]
            t[0]+=500
            self.assertFalse(g.cast(d,'deathcoil',target=e))
        self.assertEqual(orders,[('deathcoil',l.handle)]*3)

    def test_mana_evidence_allows_next_attempt_but_not_early_cast(self):
        g,d,l,e,own,t,orders,logs=self.scene()
        with coil.CoilTelemetryTests().send(orders):
            self.assertTrue(g.cast(d,'deathcoil',target=l))
            t[0]+=1;d.mana-=74
            self.assertFalse(g.coil_ready(d,t[0]))
            t[0]+=7.9;self.assertFalse(g.coil_ready(d,t[0]))
            t[0]+=.1;self.assertTrue(g.cast(d,'deathcoil',target=e))
        self.assertTrue(any(x.get('mana_spent') for x in logs))

    def test_insufficient_mana_silence_and_restored_cooldown_still_block(self):
        for why in ('mana','silence','cooldown'):
            g,d,l,e,own,t,orders,logs=self.scene()
            if why=='mana':d.mana=74
            if why=='silence':d.buffs=['BNsi']
            if why=='cooldown':d.abilities=[N(code='AUdc',level=2,cooldown=4,flags=0)]
            with coil.CoilTelemetryTests().send(orders):
                self.assertFalse(g.cast(d,'deathcoil',target=l),why)
            self.assertFalse(orders)


class AuraSaleTests(unittest.TestCase):
    def scene(self,who='dk',codes=('lhst',)):
        g,b,s,ev=chime.ChimeCourierTests().scene()
        for h in g.heroes:g.bags[h.handle]=[None]*6
        h=getattr(g,who)
        for i,c in enumerate(codes):g.bags[h.handle][i]=c
        return g,b,s,ev,h

    def test_either_aura_on_any_hero_dispatches_sells_and_rejoins(self):
        for who in ('dk','lich','dark'):
            for code in ('sbch','lhst'):
                g,b,s,ev,h=self.scene(who,(code,))
                self.assertEqual(s.bone_chime_tick(b,g.heroes,[],10),{h.handle})
                self.assertEqual(g.orders,[('move',h.type,(0,0))])
                h.x=0;s.bone_chime_tick(b,g.heroes,[],20);s.observe(g,24)
                self.assertNotIn(code,g.inventory(h))
                self.assertTrue(any(e['event']=='shop_transaction_confirmed' for e in ev))
                others=[a for a in g.heroes if a is not h]
                for a in others:a.x=2500
                s.bone_chime_tick(b,g.heroes,[],24)
                self.assertEqual(g.orders[-1],('move',h.type,(2500,0)))
                h.x=2400;self.assertFalse(s.bone_chime_tick(b,g.heroes,[],30))

    def test_both_auras_sold_in_same_visit_before_returning(self):
        g,b,s,ev,h=self.scene(codes=('sbch','lhst'));h.x=0
        for t in (10,14):
            s.bone_chime_tick(b,g.heroes,[],t);s.observe(g,t+3)
        self.assertEqual(g.orders,[('sell','Udea','sbch'),('sell','Udea','lhst')])
        self.assertFalse(any(c in {'sbch','lhst'} for c in g.inventory(h)))
        s.bone_chime_tick(b,g.heroes,[],18)
        self.assertEqual(g.orders[-1][0],'move')

    def test_aura_sale_preempts_supply_travel_without_rebuying_items(self):
        g,b,s,ev,h=self.scene()
        g.bags[h.handle][1]='ocor'
        s.orb=dict(hero=h.handle,started=0);s.rod=dict(hero=g.lich.handle,started=0)
        self.assertEqual(s.bone_chime_tick(b,g.heroes,[],10),{h.handle})
        self.assertIsNone(s.orb);self.assertIsNone(s.rod)
        self.assertIn('ocor',g.inventory(h))
        self.assertEqual(g.orders,[('move','Udea',(0,0))])

    def test_nearest_safe_visible_reachable_shop_is_selected(self):
        g,b,s,ev,h=self.scene();g.shop.x=2100
        s.bone_chime_tick(b,g.heroes,[],10)
        self.assertEqual(s.bone_chime['shop'],g.shop.handle)
        g,b,s,ev,h=self.scene();g.shop.x=2100;g.shop.visible_to=lambda me:False
        s.bone_chime_tick(b,g.heroes,[],10)
        self.assertEqual(g.orders,[('move','Udea',(0,0))])

    def test_sale_budget_per_holder_item_and_other_holder_can_still_sell(self):
        g,b,s,ev,h=self.scene()
        s.bone_chime_sales[(h.handle,'lhst')]=3
        g.bags[g.lich.handle][0]='sbch'
        self.assertEqual(s.bone_chime_tick(b,g.heroes,[],10),{g.lich.handle})
        self.assertEqual(g.orders,[('move','Ulic',(0,0))])

    def test_committed_attack_continues_while_holder_sells(self):
        g,b,s,ev,h=self.scene();s.bone_chime_tick(b,g.heroes,[],10)
        bot=Controller(g,lambda *a,**k:None);bot.battle_shop=s
        bot.attack_committed=True;bot.action=Action.ATTACK;g.orders.clear()
        self.assertTrue(bot.prepare_attack([g.lich,g.dark],11))
        self.assertFalse(g.orders)


if __name__=='__main__':unittest.main()
