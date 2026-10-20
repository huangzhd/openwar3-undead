import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import test_coil_telemetry_01150 as coil
from undead.game_view import SDKGame
from undead.controller import Controller
from undead.nc_combo import NCCombo
from undead.battle_shop import sellable,UNWANTED_AURAS


class HeroSpellRecoveryTests(unittest.TestCase):
    def scene(self,kind='Ulic',code='AUfn'):
        g,d,l,e,own,t,orders,logs=coil.CoilTelemetryTests().scene()
        g.tech_many=lambda codes:{c:0 for c in codes}
        h=l;h.type=kind;h.hp=h.hp_max;h.mana=500
        h.abilities=[N(code=code,level=1,cooldown=0,flags=0)]
        g.observe_coil(own,t[0],lambda event,**kw:logs.append(dict(event=event,**kw)))
        t[0]+=1;h.abilities=[N(code='AIar',level=1,cooldown=0,flags=0)]
        h.items=['afac',None,None,None,None,None]
        self.assertFalse(g.hero_spell_ready(h,code,t[0]))
        return g,h,e,own,t,orders,logs

    def sender(self,orders,accepted=True):
        return patch.object(SDKGame,'cast',side_effect=lambda u,s,**kw:
                            orders.append((s,kw.get('target').handle if kw.get('target') else None)) or accepted)

    def test_actual_afac_snapshot_resumes_regular_nova_without_selling_or_faking_cd(self):
        g,h,e,own,t,orders,logs=self.scene()
        samples=json.loads((Path(__file__).parent/'fixtures/lich_afac_005557.json').read_text(encoding='utf-8'))['samples']
        before=next(r for r in samples if any(a['code']=='AUfn' for a in r['hero']['abilities']))
        after=next(r for r in samples if [a['code'] for a in r['hero']['abilities']]==['AIar'])
        g._hero_spell_telemetry.states.clear()
        for row in (before,after):
            t[0]=row['clock'];h.mana=row['hero']['mana'];h.items=row['hero']['inventory']
            h.abilities=[N(**a) for a in row['hero']['abilities']]
            g.observe_coil(own,t[0],lambda event,**kw:logs.append(dict(event=event,**kw)))
        t[0]+=7.99;self.assertFalse(g.hero_spell_ready(h,'AUfn'))
        t[0]+=.01
        b=Controller(g,lambda *a,**kw:None)
        with self.sender(orders):b.fight([h],[e],t[0])
        self.assertEqual(orders,[('frostnova',e.handle)])
        self.assertIsNone(g.cooldown(h,'AUfn'))
        self.assertEqual([a['code'] for a in g.abilities(h)],['AIar'])
        self.assertIn('afac',g.inventory(h))
        self.assertNotIn('afac',UNWANTED_AURAS);self.assertFalse(sellable(h,'afac'))

    def test_nova_and_fork_finishers_use_remembered_learned_level(self):
        for kind,code,spell,delay in [('Ulic','AUfn','frostnova',8),('Nngs','ANfl','forkedlightning',11)]:
            g,h,e,own,t,orders,logs=self.scene(kind,code);t[0]+=delay;e.hp=50
            with self.sender(orders):NCCombo(lambda *a,**kw:None).try_cast(g,[h],[e],t[0],{})
            self.assertEqual(orders,[(spell,e.handle)])

    def test_regular_fork_and_direct_silence_armor_paths(self):
        for kind,code,spell,delay in [('Nngs','ANfl','forkedlightning',11),
                                      ('Nbrn','ANsi','silence',15),('Ulic','AUfu','frostarmor',2)]:
            g,h,e,own,t,orders,logs=self.scene(kind,code);t[0]+=delay
            with self.sender(orders):
                if code=='ANfl':Controller(g,lambda *a,**kw:None).fight([h],[e],t[0])
                else:self.assertTrue(g.cast(h,spell,target=e if code=='ANsi' else h))
            self.assertEqual(orders[0][0],spell)

    def test_receipts_only_stop_after_three_across_targets_items_and_long_wait(self):
        for kind,code,spell,delay in [('Ulic','AUfn','frostnova',8),('Nngs','ANfl','forkedlightning',11)]:
            g,h,e,own,t,orders,logs=self.scene(kind,code);t[0]+=delay
            with self.sender(orders):
                for i in range(3):
                    self.assertTrue(g.cast(h,spell,target=e))
                    self.assertFalse(g.cast(h,spell,target=own[0]))
                    t[0]+=delay+3
                h.items[0]='lhst';t[0]+=500
                self.assertFalse(g.cast(h,spell,target=e))
            self.assertEqual(len(orders),3)

    def test_mana_observation_allows_retry_but_preserves_full_cooldown_margin(self):
        for kind,code,spell,delay,cost in [('Ulic','AUfn','frostnova',8,125),
                                          ('Nngs','ANfl','forkedlightning',11,110)]:
            g,h,e,own,t,orders,logs=self.scene(kind,code);t[0]+=delay
            with self.sender(orders):
                self.assertTrue(g.cast(h,spell,target=e))
                t[0]+=1;h.mana-=cost-2
                self.assertFalse(g.hero_spell_ready(h,code))
                self.assertTrue(any(r.get('mana_spent') for r in logs))
                t[0]+=delay+1.99;self.assertFalse(g.hero_spell_ready(h,code))
                t[0]+=.01;self.assertTrue(g.cast(h,spell,target=e))

    def test_rejected_order_mana_loss_does_not_reset_failure_count(self):
        g,h,e,own,t,orders,logs=self.scene();t[0]+=8
        with self.sender(orders,False):self.assertFalse(g.cast(h,'frostnova',target=e))
        t[0]+=1;h.mana-=125;g.hero_spell_ready(h,'AUfn')
        self.assertFalse(any(r.get('mana_spent') for r in logs))
        self.assertEqual(g._hero_spells().states[(h.handle,'AUfn')]['failures'],1)

    def test_another_spell_invalidates_previous_mana_attribution(self):
        g,h,e,own,t,orders,logs=self.scene();t[0]+=8
        h.abilities.append(N(code='AUfu',level=1,cooldown=0,flags=0))
        with self.sender(orders):
            self.assertTrue(g.cast(h,'frostnova',target=e))
            t[0]+=1;self.assertTrue(g.cast(h,'frostarmor',target=h))
            t[0]+=1;h.mana-=125
            g.observe_coil(own,t[0],lambda event,**kw:logs.append(dict(event=event,**kw)))
        nova=g._hero_spells().states[(h.handle,'AUfn')]
        self.assertEqual(nova['failures'],1)
        self.assertIsNone(nova['pending'])
        self.assertFalse(any(r.get('mana_spent') and r.get('ability')=='AUfn' for r in logs))

    def test_missing_unknown_or_unusable_snapshot_never_guesses_skill(self):
        for why in ('unseen','empty','silence','dead','no_detail','enemy','handle','rewind','mana','lost'):
            g,h,e,own,t,orders,logs=self.scene();t[0]+=8
            if why=='unseen':g._hero_spells().states.clear()
            if why=='empty':h.abilities=[]
            if why=='silence':h.buffs=['BNsi']
            if why=='dead':h.alive=False
            if why=='no_detail':h.has_detail=False
            if why=='enemy':h.owner=1
            if why=='handle':h.handle=(9,9)
            if why=='rewind':t[0]=0
            if why=='mana':h.mana=124
            if why=='lost':g.observe_coil([],t[0],lambda *a,**kw:None)
            with self.sender(orders):self.assertFalse(g.cast(h,'frostnova',target=e),why)
            self.assertFalse(orders)

    def test_restored_unknown_positive_and_zero_cooldowns_override_fallback(self):
        g,h,e,own,t,orders,logs=self.scene();t[0]+=8
        h.abilities=[N(code='AUfn',level=2,cooldown=None,flags=0)]
        self.assertFalse(g.hero_spell_ready(h,'AUfn'))
        h.abilities[0].cooldown=4;self.assertFalse(g.hero_spell_ready(h,'AUfn'))
        h.abilities[0].cooldown=0;self.assertTrue(g.hero_spell_ready(h,'AUfn'))
        h.abilities[0].level=0;self.assertFalse(g.hero_spell_ready(h,'AUfn'))

    def test_arrow_toggles_use_memory_but_receipts_never_grant_unlimited_retries(self):
        for kind,code,order in [('Nngs','ANfa','coldarrows'),('Nbrn','ANba','blackarrowon')]:
            g,h,e,own,t,orders,logs=self.scene(kind,code)
            with self.sender(orders):
                for i in range(3):
                    self.assertTrue(g.cast(h,order))
                    self.assertFalse(g.cast(h,order))
                    t[0]+=20
                self.assertFalse(g.cast(h,order))
            self.assertEqual(len(orders),3)
            self.assertFalse(any(r.get('mana_spent') for r in logs))


if __name__=='__main__':unittest.main()
