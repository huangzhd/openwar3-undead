import copy
import json
import unittest
from types import SimpleNamespace as N

import bootstrap
import w3fast
import w3world
from openwar3.game import rawcode
from learning.actions import SCHEMA, ECONOMY_SCHEMA, LEGACY_SCHEMA, validate, preflight
from learning.dataset import native_payload
from learning.effects import transition_facts
from learning.model_codec import encode_observation, encode_action, decode_decision
from learning.economy_actions import HERO_CODES
import test_learning_economy_actions as economy
from test_learning_actions import action
from test_learning_trajectory import unit


class HeroPrimitiveTests(unittest.TestCase):
    run_action = economy.EconomicPrimitiveTests.run_action
    rows = economy.EconomicPrimitiveTests.rows
    refresh = economy.EconomicPrimitiveTests.refresh

    def setUp(self):
        economy.EconomicPrimitiveTests.setUp(self)
        self.hall.type='uaod'
        self.base=unit(1,66,type='unpl')
        self.raw.units.append(self.base)
        self.raw.players[1].food_cap=30
        self.refresh()

    def hero(self,code='Udea'):
        return action('train_hero',unit=[44,7],code=code)

    def test_four_heroes_dispatch_real_sdk_and_roundtrip_model_labels(self):
        context=dict(schema=SCHEMA,bounds=self.executor.bounds)
        encoded=encode_observation(self.decision,context,'strict-p1-observation-v5')
        for code in HERO_CODES:
            with self.subTest(code=code):
                value=self.hero(code);receipt=self.run_action(value)
                self.assertTrue(receipt['accepted'])
                call=self.native.call_args.args[0][0]
                expected=w3fast.command('immediate',self.hall,rawcode(code))
                self.assertEqual(call.args,expected.args)
                self.assertEqual(decode_decision(encoded,encode_action(encoded,value)),value)
                request=next(r for r in reversed(self.rows()) if r['event']=='request')
                self.assertEqual(request['action'],value)
                native=[json.loads(s) for s in (self.path/'trajectory.jsonl').read_text().splitlines()]
                payload=next(r['action'] for r in reversed(native) if r['event']=='action_request')
                self.assertEqual(payload,native_payload(value))
                self.assertEqual(receipt['effect'],'unverified')

    def test_legacy_schemas_and_generic_train_cannot_gain_hero_products(self):
        for value in (dict(self.hero(),schema=ECONOMY_SCHEMA),dict(self.hero(),schema=LEGACY_SCHEMA),
                      action('train',unit=[44,7],code='Udea'),self.hero('Nbrn'),self.hero('Hpal'),
                      dict(self.hero(),revive=True)):
            with self.assertRaises(ValueError):self.run_action(value)
        old=encode_observation(self.decision,dict(schema=ECONOMY_SCHEMA,bounds=self.executor.bounds),
                               'strict-p1-observation-v5')
        with self.assertRaisesRegex(ValueError,'operation_not_supported'):encode_action(old,self.hero())
        self.native.assert_not_called()

    def test_existing_dead_or_queued_hero_blocks_recruitment(self):
        hero=unit(1,77,type='Udea');self.raw.units.append(hero)
        for alive in (True,False):
            hero.flags=w3world.ALIVE if alive else 0;self.refresh()
            self.assertEqual(self.run_action(self.hero())['reason'],'hero_already_observed')
        self.raw.units.remove(hero);self.refresh()
        # Change after decision, on the same clock: another altar queued this hero.
        self.raw.production=[N(building=self.base.handle,kind='queue',queue=['Udea'],progress=.2)]
        self.assertEqual(self.run_action(self.hero())['reason'],'hero_already_queued')
        self.native.assert_not_called()

    def test_tier_limit_counts_other_heroes_and_pending_recruitment(self):
        self.raw.units.append(unit(1,77,type='Nbrn'));self.refresh()
        self.assertEqual(self.run_action(self.hero())['reason'],'hero_tech_limit')
        self.base.type='unp1';self.refresh()
        self.assertEqual(preflight(self.hero(),self.decision,self.executor.bounds),'allowed')
        self.raw.production=[N(building=self.hall.handle,kind='queue',queue=['Ulic'],progress=.1)]
        self.assertEqual(self.run_action(self.hero())['reason'],'hero_tech_limit')
        self.base.type='unp2';self.refresh()
        self.assertEqual(preflight(self.hero(),self.decision,self.executor.bounds),'allowed')
        self.native.assert_not_called()

    def test_resources_food_and_altar_rechecked_before_dispatch(self):
        for field,value,reason in (('gold',424,'insufficient_gold'),('lumber',99,'insufficient_lumber'),
                                   ('food_cap',5,'insufficient_food')):
            previous=getattr(self.raw.players[1],field)
            setattr(self.raw.players[1],field,value)
            self.assertEqual(self.run_action(self.hero())['reason'],reason)
            setattr(self.raw.players[1],field,previous)
        self.hall.type='usep'
        self.assertEqual(self.run_action(self.hero())['reason'],'wrong_producer')
        self.hall.type='uaod';self.hall.hp=1
        self.assertEqual(self.run_action(self.hero())['reason'],'producer_not_ready')
        self.native.assert_not_called()

    def test_unknown_roster_and_queue_cannot_grant_hero_slot(self):
        unknown=unit(1,77,type=None);self.raw.units.append(unknown);self.refresh()
        self.assertEqual(self.run_action(self.hero())['reason'],'hero_roster_unknown')
        self.raw.units.remove(unknown);self.refresh()
        self.raw.production=[N(building=self.hall.handle,kind='queue',queue=[None],progress=.1)]
        self.assertEqual(self.run_action(self.hero())['reason'],'hero_queue_unknown')
        self.native.assert_not_called()

    def test_engine_rejects_unobserved_dead_hero_and_unknown_feasibility(self):
        for verdict,reason in ((221,'engine_prerequisites_rejected'),(185,'engine_prerequisites_rejected'),
                               (None,'engine_prerequisites_unknown'),(True,'engine_prerequisites_rejected')):
            self.game.can_do=lambda *args,v=verdict:v
            self.assertEqual(self.run_action(self.hero())['reason'],reason)
        self.native.assert_not_called()

    def test_later_birth_and_queue_are_facts_not_causal_success(self):
        after=copy.deepcopy(self.decision)
        after['clock']+=55
        hero=self.rec.boundary.unit(unit(1,77,type='Udea'))
        after['units'].append(hero)
        after['production']=[dict(building=[44,7],kind='queue',queue=['Udea'],progress=.2)]
        facts=transition_facts(self.hero(),self.decision,after)
        self.assertEqual(facts['matching_new_own_handles'],[[77,7]])
        self.assertTrue(facts['producer_queue_observed']);self.assertFalse(facts['causally_attributed'])
        hero['owner']=2
        self.assertEqual(transition_facts(self.hero(),self.decision,after)['matching_new_own_handles'],[])


if __name__=='__main__':unittest.main()
