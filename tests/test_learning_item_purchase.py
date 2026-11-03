import copy
from types import MethodType,SimpleNamespace as N
import unittest

import bootstrap
from openwar3 import Game
from learning.actions import RESEARCH_SCHEMA, validate
from learning.dataset import native_payload
from learning.effects import transition_facts
from learning.model_codec import encode_action,encode_observation,decode_decision
import test_learning_economy_actions as helpers
from test_learning_actions import action
from test_learning_trajectory import unit


class PurchaseTests(unittest.TestCase):
    run_action=helpers.EconomicPrimitiveTests.run_action
    rows=helpers.EconomicPrimitiveTests.rows
    refresh=helpers.EconomicPrimitiveTests.refresh

    def setUp(self):
        helpers.EconomicPrimitiveTests.setUp(self)
        self.hall.type='utom'
        self.hall.abilities.append(N(code='Apit',level=1,cooldown=0))
        self.own.type='Udea'
        self.own.abilities.extend(N(code=c,level=1,cooldown=0) for c in ('AInv','AHer'))
        self.mine.has_detail=True
        self.mine.items=[None]*6
        self.game._one=MethodType(Game._one,self.game)
        self.game.buy=MethodType(Game.buy,self.game)
        self.value=action('buy_item',unit=[44,7],target=[11,7],item='rnec')
        self.refresh()

    def test_sdk_shop_selects_recipient_but_model_retains_intent(self):
        self.assertTrue(self.run_action(self.value)['accepted'])
        call=self.native.call_args.args[0][0]
        payload=native_payload(self.value)
        self.assertEqual(call.args[:7],[self.hall.addr,44,7,payload['code'],0,0,0])
        self.assertIsNone(payload['target'])
        encoded=encode_observation(self.decision,dict(schema=self.value['schema'],bounds=self.executor.bounds),
                                   'strict-p1-observation-v5')
        self.assertEqual(decode_decision(encoded,encode_action(encoded,self.value)),self.value)
        with self.assertRaises(ValueError):validate(self.value|dict(schema=RESEARCH_SCHEMA))

    def test_resource_tier_and_merchant_capability_fail_closed(self):
        self.raw.players[1].gold=149
        self.assertEqual(self.run_action(self.value)['reason'],'insufficient_gold')
        self.raw.players[1].gold=500
        self.assertEqual(self.run_action(self.value|dict(item='ocor'))['reason'],'item_prerequisites_missing')
        self.hall.abilities=[]
        self.assertEqual(self.run_action(self.value)['reason'],'shop_not_ready')
        self.native.assert_not_called()

    def test_other_inventory_bearer_and_bag_changes_cannot_misdirect_buy(self):
        other=unit(1,99,type='Nbrn')
        self.raw.units.append(other)
        self.assertEqual(self.run_action(self.value)['reason'],'shop_recipient_ambiguous')
        other.x=1500
        self.own.items=['rnec']*6
        self.assertEqual(self.run_action(self.value)['reason'],'hero_inventory_unavailable_or_full')
        self.own.items=[None]*6;self.own.x=1500
        self.assertEqual(self.run_action(self.value)['reason'],'intended_hero_not_in_purchase_range')
        self.native.assert_not_called()

    def test_actual_inventory_gain_is_independent_of_receipt_and_intent(self):
        after=copy.deepcopy(self.decision)
        hero=next(u for u in after['units'] if u['handle']==[11,7])
        hero['inventory'][2]='rnec'
        facts=transition_facts(self.value,self.decision,after)
        self.assertTrue(facts['intended_item_gain_observed'])
        self.assertEqual(facts['observed_item_gainers'],[[11,7]])
        self.assertFalse(facts['causally_attributed'])
        hero['inventory']=None
        self.assertFalse(transition_facts(self.value,self.decision,after)['intended_item_gain_observed'])
