import copy
import unittest
from types import MethodType, SimpleNamespace as N

import bootstrap
import w3fast
from openwar3 import Game
from openwar3.game import rawcode
from learning.actions import LEGACY_SCHEMA, validate, preflight
from learning.economy_actions import catalog
import test_learning_actions as helpers
from test_learning_actions import action
from test_learning_trajectory import unit


class EconomicPrimitiveTests(unittest.TestCase):
    run_action = helpers.PrimitiveTests.run_action
    rows = helpers.PrimitiveTests.rows

    def setUp(self):
        helpers.PrimitiveTests.setUp(self)
        self.own.abilities += [N(code=c, level=1, cooldown=0) for c in ('AUbu', 'Aaha')]
        self.hall = unit(1, 44, type='unpl', has_detail=True, items=[None]*6,
                         abilities=[N(code='Aque', level=1, cooldown=0)])
        self.mine = unit(1, 55, type='ugol')
        self.raw.units += [self.hall, self.mine]
        self.raw.players[1].gold=500;self.raw.players[1].lumber=150
        self.raw.production=[]
        self.game.map=lambda:N(bounds=(-1000,1000,-1000,1000),buildable=lambda x,y:True)
        self.game.can_do=lambda unit,code:0
        for method in ('gather','build','train'):
            setattr(self.game,method,MethodType(getattr(Game,method),self.game))
        self.game._then=Game._then
        self.refresh()

    def refresh(self):
        self.raw.clock+=.1;self.raw.publish_count+=1
        self.rec.observe();self.decision=copy.deepcopy(self.rec.last_observation)

    def test_gold_build_train_use_exact_sdk_encoding_and_native_links(self):
        cases=[(action('gather_gold',unit=[11,7],target=[55,7]),'target',852018,self.own,self.mine),
               (action('build',unit=[11,7],code='uzig',x=98,y=-110),'build',rawcode('uzig'),self.own,None),
               (action('train',unit=[44,7],code='uaco'),'immediate',rawcode('uaco'),self.hall,None)]
        for value,op,code,source,target in cases:
            with self.subTest(op=value['op']):
                receipt=self.run_action(value)
                self.assertTrue(receipt['accepted'])
                normalized=validate(value)
                expected=w3fast.command(op,source,code,target=target,
                    x=normalized.get('x'),y=normalized.get('y'))
                call=self.native.call_args.args[0][0]
                self.assertEqual(call.op,expected.op);self.assertEqual(call.args,expected.args)
                self.assertEqual(len(receipt['native_request_ids']),1)
                self.assertEqual(receipt['effect'],'unverified')
        build=next(r for r in self.rows() if r['event']=='request' and r['action']['op']=='build')['action']
        self.assertEqual((build['x'],build['y']),(96.,-96.))

    def test_v1_stays_six_actions_and_unknown_codes_never_send(self):
        self.assertEqual(validate(dict(schema=LEGACY_SCHEMA,op='wait'))['schema'],LEGACY_SCHEMA)
        for value in (dict(action('train',unit=[44,7],code='uaco'),schema=LEGACY_SCHEMA),
                      action('train',unit=[44,7],code='unp1'),action('build',unit=[11,7],code='hbar',x=0,y=0),
                      action('train',unit=[44,7],code=[])):
            with self.subTest(value=value),self.assertRaises(ValueError):self.run_action(value)
        self.native.assert_not_called()

    def test_resource_food_producer_and_prerequisite_negatives(self):
        values=[(action('train',unit=[44,7],code='uaco'),'insufficient_gold',dict(gold=74)),
                (action('build',unit=[11,7],code='uzig',x=0,y=0),'insufficient_lumber',dict(lumber=49)),
                (action('train',unit=[44,7],code='uaco'),'insufficient_food',dict(food_used=12)),
                (action('train',unit=[44,7],code='ugho'),'wrong_producer',{}),
                (action('gather_gold',unit=[11,7],target=[22,7]),'gold_target_not_owned_ready_mine',{})]
        for value,reason,changes in values:
            observation=copy.deepcopy(self.decision);observation['resources'].update(changes)
            self.assertEqual(preflight(value,observation,self.executor.bounds),reason)
        self.hall.type='usep';self.refresh()
        self.assertEqual(preflight(action('train',unit=[44,7],code='ucry'),self.decision,self.executor.bounds),
                         'ready_graveyard_required')
        self.raw.units.append(unit(1,66,type='ugrv'));self.refresh()
        self.assertEqual(preflight(action('train',unit=[44,7],code='ucry'),self.decision,self.executor.bounds),'allowed')
        self.native.assert_not_called()

    def test_same_clock_resource_spend_and_queue_change_are_revalidated(self):
        self.raw.players[1].gold=0
        result=self.run_action(action('train',unit=[44,7],code='uaco'))
        self.assertEqual(result['reason'],'insufficient_gold')
        self.raw.players[1].gold=500
        self.raw.production=[N(building=self.hall.handle,kind='queue',queue=['uaco']*7,progress=1)]
        result=self.run_action(action('train',unit=[44,7],code='uaco'))
        self.assertEqual(result['reason'],'producer_queue_full');self.native.assert_not_called()

    def test_unknown_or_constructing_producer_and_engine_query_fail_closed(self):
        value=action('train',unit=[44,7],code='uaco')
        self.raw.production=[N(building=self.hall.handle,kind='construction',queue=[],progress=.9)]
        self.assertEqual(self.run_action(value)['reason'],'producer_not_ready')
        self.raw.production=[]
        for verdict,reason in ((None,'engine_prerequisites_unknown'),(183,'engine_prerequisites_rejected')):
            self.game.can_do=lambda *a,v=verdict:v
            self.assertEqual(self.run_action(value)['reason'],reason)
        self.native.assert_not_called()

    def test_build_requires_visible_point_full_footprint_and_public_terrain(self):
        value=action('build',unit=[11,7],code='uzig',x=0,y=0)
        self.game.visible.return_value=None
        self.assertEqual(self.run_action(value)['reason'],'build_point_not_visible')
        self.game.visible.return_value=True
        self.assertEqual(self.run_action(dict(value,x=960))['reason'],'footprint_outside_map')
        self.game.map=lambda:N(buildable=lambda x,y: x < 0)
        self.assertEqual(self.run_action(value)['reason'],'terrain_not_buildable')
        self.native.assert_not_called()

    def test_unknown_own_resources_and_hidden_economy_cannot_grant_legality(self):
        value=action('train',unit=[44,7],code='uaco')
        self.raw.players[1].known=False
        self.raw.players[2].gold=999999
        self.hidden.type='ugrv';self.hidden.owner=2
        self.assertEqual(self.run_action(value)['reason'],'resources_unknown')
        self.native.assert_not_called()

    def test_public_catalog_has_frozen_costs_not_strategy_budgets(self):
        costs=catalog()
        self.assertEqual(costs['uaco']['gold'],75)
        self.assertEqual(costs['ugho']['food'],2)
        self.assertEqual(costs['usep']['gold'],200)
        self.assertNotIn('reserve',str(costs))

    def test_hall_upgrade_charges_increment_and_checks_current_form(self):
        from learning.actions import SPELL_SCHEMA
        from learning.dataset import native_payload
        from learning.model_codec import encode_observation,encode_action,decode_decision
        self.hall.abilities.append(N(code='Aupg',level=1,cooldown=0))
        altar=unit(1,66,type='uaod')
        self.raw.units.append(altar)
        for before,after,gold,wood in [('unpl','unp1',320,210),('unp1','unp2',325,230)]:
            self.hall.type=before
            self.raw.players[1].gold=gold
            self.raw.players[1].lumber=wood
            self.refresh()
            cmd=action('upgrade_hall',unit=[44,7],code=after)
            self.assertTrue(self.run_action(cmd)['accepted'])
            self.assertEqual(self.native.call_args.args[0][0].args[3],native_payload(cmd)['code'])
            encoded=encode_observation(self.decision,dict(schema=cmd['schema'],bounds=self.executor.bounds),
                                       'strict-p1-observation-v5')
            self.assertEqual(decode_decision(encoded,encode_action(encoded,cmd)),cmd)
            if after=='unp2':
                altar.owner=2
                self.assertEqual(self.run_action(cmd)['reason'],'ready_altar_required')
                altar.owner=1
            with self.assertRaises(ValueError):validate(dict(cmd,schema=SPELL_SCHEMA))
            self.raw.players[1].lumber-=1
            self.assertEqual(self.run_action(cmd)['reason'],'insufficient_lumber')
            self.raw.players[1].lumber=wood
            self.hall.type=after
            self.assertEqual(self.run_action(cmd)['reason'],'wrong_hall_upgrade_source')

    def test_hall_busy_or_infeasible_cannot_replace_production(self):
        self.raw.players[1].lumber=250
        self.hall.abilities.append(N(code='Aupg',level=1,cooldown=0))
        self.refresh()
        cmd=action('upgrade_hall',unit=[44,7],code='unp1')
        for kind,queue,reason in [('queue',['uaco'],'hall_production_busy'),('upgrade',['unp1'],'hall_not_ready'),
                                  (None,[],'hall_production_busy')]:
            self.raw.production=[N(building=self.hall.handle,kind=kind,queue=queue,progress=.1)]
            self.assertEqual(self.run_action(cmd)['reason'],reason)
        self.raw.production=[]
        self.game.can_do=lambda *args:183
        self.assertEqual(self.run_action(cmd)['reason'],'engine_prerequisites_rejected')
        self.native.assert_not_called()


if __name__=='__main__':unittest.main()
