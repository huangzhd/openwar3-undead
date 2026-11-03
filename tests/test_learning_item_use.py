from types import MethodType,SimpleNamespace as N
import json
import unittest

import bootstrap
from openwar3 import Game
from learning.actions import SHOP_SCHEMA,validate
from learning.dataset import native_payload
from learning.model_codec import encode_action,encode_observation,decode_decision
import test_learning_economy_actions as helpers
from test_learning_actions import action


class ItemUseTests(unittest.TestCase):
    run_action=helpers.EconomicPrimitiveTests.run_action
    rows=helpers.EconomicPrimitiveTests.rows
    refresh=helpers.EconomicPrimitiveTests.refresh

    def setUp(self):
        helpers.EconomicPrimitiveTests.setUp(self)
        self.own.type='Udea'
        self.own.abilities.extend(N(code=c,level=1,cooldown=0) for c in ('AInv','AHer','AItp','AIh1'))
        self.own.items=[None,'phea',None,None,'stwp',None]
        self.game.use_item=MethodType(Game.use_item,self.game)
        self.value=action('use_item_point',unit=[11,7],item='stwp',slot=4,x=self.hall.x,y=self.hall.y)
        self.refresh()

    def test_slot_and_mode_roundtrip_from_actual_sdk_and_actor(self):
        for value in (self.value,action('use_item_now',unit=[11,7],slot=1,item='phea')):
            self.assertTrue(self.run_action(value)['accepted'])
            reply=[json.loads(s) for s in (self.path/'trajectory.jsonl').read_text().splitlines()]
            native=next(r['action'] for r in reversed(reply) if r['event']=='action_request')
            self.assertEqual(native,native_payload(value))
            self.assertEqual(self.native.call_args.args[0][0].args[9:11],[value['slot'],int(value is self.value)])
            encoded=encode_observation(self.decision,dict(schema=value['schema'],bounds=self.executor.bounds),'strict-p1-observation-v5')
            self.assertEqual(decode_decision(encoded,encode_action(encoded,value)),value)

    def test_same_clock_slot_swap_or_hall_loss_never_sends_order(self):
        self.own.items[4],self.own.items[1]='phea','stwp'
        self.assertEqual(self.run_action(self.value)['reason'],'expected_item_not_in_slot')
        self.own.items[4]='stwp'
        self.hall.owner=2
        self.assertEqual(self.run_action(self.value)['reason'],'portal_requires_ready_own_hall_point')
        self.hall.owner=1
        self.own.abilities[-2].cooldown=4
        self.assertEqual(self.run_action(self.value)['reason'],'item_cooldown_not_ready')
        self.native.assert_not_called()

    def test_cannot_send_arbitrary_slot_mode_point_or_unsupported_item(self):
        for change in (dict(slot=True),dict(slot=-1),dict(slot=6),dict(mode=2),dict(target=[22,7]),
                       dict(schema=SHOP_SCHEMA),dict(item='rnec'),dict(op='use_item_now')):
            with self.assertRaises(ValueError):validate(self.value|change)
        self.assertEqual(self.run_action(self.value|dict(x=self.hall.x+64))['reason'],'portal_requires_ready_own_hall_point')
        self.native.assert_not_called()
