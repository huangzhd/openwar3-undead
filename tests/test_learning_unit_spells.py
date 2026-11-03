import copy
from types import MethodType, SimpleNamespace as N
import unittest

import bootstrap
from openwar3 import Game
from learning.actions import LEARN_SCHEMA, validate
from learning.dataset import native_payload
from learning.effects import transition_facts
from learning.model_codec import encode_observation, encode_action, decode_decision
from learning.observation_schema import validate as check_observation, ObservationError
import test_learning_actions as primitives


class UnitSpellTests(unittest.TestCase):
    run_action = primitives.PrimitiveTests.run_action

    def setUp(self):
        primitives.PrimitiveTests.setUp(self)
        self.game.cast = MethodType(Game.cast,self.game)
        self.own.type='Ulic'
        self.own.mana=200.
        self.own.abilities.extend([N(code=c,level=1,cooldown=0.) for c in ('AUfn','AUfu')])
        self.own.buffs=['private_unknown']
        self.seen.buffs=['BUfa']
        self.value=primitives.action('cast_unit',unit=[11,7],target=[11,7],skill='AUfu')
        self.refresh()

    def refresh(self):
        self.raw.clock+=1
        self.rec.observe()
        self.decision=copy.deepcopy(self.rec.last_observation)

    def test_friendly_armor_and_visible_enemy_nova_have_exact_target_and_order(self):
        for spell,target in [('AUfu',self.own),('AUfn',self.seen),('AUdc',self.seen)]:
            if spell=='AUdc':
                self.own.type='Udea'
                self.own.abilities.append(N(code=spell,level=1,cooldown=0.))
                self.refresh()
            action=dict(self.value,skill=spell,target=list(target.handle))
            receipt=self.run_action(action)
            self.assertTrue(receipt['accepted'])
            call=self.native.call_args.args[0][0]
            self.assertEqual(call.args[3],native_payload(action)['code'])
            self.assertEqual(call.args[4:7],[target.addr,*target.handle])
            encoded=encode_observation(self.decision,dict(schema=action['schema'],bounds=self.executor.bounds),
                                       'strict-p1-observation-v5')
            self.assertEqual(decode_decision(encoded,encode_action(encoded,action)),action)

    def test_same_clock_range_mana_cooldown_and_control_rechecked(self):
        value=dict(self.value,skill='AUfn',target=list(self.seen.handle))
        for obj,key,v,reason in [(self.seen,'x',1200,'spell_target_out_of_range'),
                                 (self.own,'mana',124,'spell_mana_insufficient_or_unknown'),
                                 (self.own.abilities[-2],'cooldown',1,'spell_not_ready'),
                                 (self.own.abilities[-2],'cooldown',None,'spell_not_ready'),
                                 (self.own,'buffs',['BNsi'],'caster_disabled')]:
            original=getattr(obj,key);setattr(obj,key,v)
            self.assertEqual(self.run_action(value)['reason'],reason)
            setattr(obj,key,original)
        self.seen.visible_mask=1
        self.assertEqual(self.run_action(value)['reason'],'spell_target_not_observed_alive')
        self.native.assert_not_called()

    def test_wrong_target_and_legacy_action_rejected(self):
        for value,reason in [(dict(self.value,skill='AUfn'),'invalid_nova_target'),
                             (dict(self.value,target=list(self.seen.handle)),'invalid_armor_target'),
                             (dict(self.value,skill='AUdc'),'wrong_spell_caster')]:
            self.assertEqual(self.run_action(value)['reason'],reason)
        for changes in [dict(skill='AUan'),dict(schema=LEARN_SCHEMA),dict(order=852225)]:
            with self.assertRaises(ValueError):validate(self.value|changes)
        self.native.assert_not_called()

    def test_own_status_only_and_frost_armor_facts(self):
        self.assertEqual(self.decision['own_spell_status'],[dict(unit=[11,7],buffs=[])])
        after=copy.deepcopy(self.decision)
        after['own_spell_status'][0]['buffs']=['BUfa']
        after['units'][0]['mana']-=40
        facts=transition_facts(self.value,self.decision,after)
        self.assertFalse(facts['target_frost_armor_before'])
        self.assertTrue(facts['target_frost_armor_after'])
        self.assertEqual(facts['caster_mana_after'],160.)
        self.assertFalse(facts['causally_attributed'])
        after['own_spell_status'][0]['unit']=list(self.seen.handle)
        with self.assertRaises(ObservationError):check_observation(after,'strict-p1-observation-v5')
