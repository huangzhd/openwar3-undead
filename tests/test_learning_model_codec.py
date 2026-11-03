import copy,json,unittest
from learning.model_codec import *
from learning.trajectory import ObservationBoundary
from test_learning_trajectory import fixture
from test_learning_actions import action


class ModelCodecTests(unittest.TestCase):
    def setUp(self):
        game,raw=fixture();self.obs=ObservationBoundary(101,1).project(game,raw)
        self.obs['tree_sightings']=[dict(handle=[88,7],type='LTlt',x=100,y=200,seen_clock=10)]
        self.context=dict(schema=SCHEMA,bounds=[-1000,1000,-1000,1000])
    def encode(self):return encode_observation(self.obs,self.context,'strict-p1-observation-v2')

    def test_all_operations_roundtrip_current_observation_pointers(self):
        encoded=self.encode()
        cases=[action('wait'),action('stop',unit=[11,7]),action('hold',unit=[11,7]),
               action('move',unit=[11,7],x=100,y=-200),action('attack_move',unit=[11,7],x=50,y=60),
               action('attack',unit=[11,7],target=[22,7]),action('gather_gold',unit=[11,7],target=[22,7]),
               action('gather_lumber',unit=[11,7],target=[88,7]),action('inspect_trees',x=100,y=200),
               action('build',unit=[11,7],code='uzig',x=96,y=96),action('train',unit=[11,7],code='ugho')]
        for value in cases:
            with self.subTest(op=value['op']):self.assertEqual(decode_decision(encoded,encode_action(encoded,value)),value)

    def test_numeric_input_omits_handles_pid_addresses_and_outcomes(self):
        data=json.dumps(self.encode().features)
        for name in ('handle','pid','addr','outcome','reward','order_target','opponent_gold'):self.assertNotIn(name,data)
        self.assertNotIn('100011',data)

    def test_production_uses_current_entity_pointer_and_preserves_unknowns(self):
        row=self.encode().features['production'][0]
        self.assertEqual(row['building'],0);self.assertEqual(row['kind'],[1,0,0])
        self.assertEqual(len(row['queue']),1)
        self.obs['production'][0]['progress']=None
        self.assertEqual(self.encode().features['production'][0]['progress'],dict(values=[0.],known=[0]))

    def test_unknown_resource_has_distinct_mask_from_known_zero(self):
        self.obs['resources']['gold']=None;a=self.encode().features['resources']
        self.obs['resources']['gold']=0;b=self.encode().features['resources']
        self.assertEqual(a['values'][0],b['values'][0]);self.assertEqual((a['known'][0],b['known'][0]),(0,1))

    def test_unseen_target_extra_fields_and_invalid_pointers_rejected(self):
        encoded=self.encode()
        with self.assertRaisesRegex(ValueError,'not_observed'):encode_action(encoded,action('attack',unit=[11,7],target=[33,7]))
        good=encode_action(encoded,action('stop',unit=[11,7]))
        for change in (dict(unit=-1),dict(unit=True),dict(unit=999),dict(force=True),dict(op=99)):
            with self.assertRaises(ValueError):decode_decision(encoded,good|change)

    def test_points_cannot_be_nan_outside_map_or_boolean(self):
        encoded=self.encode();good=encode_action(encoded,action('move',unit=[11,7],x=0,y=0))
        for point in ([float('nan'),0],[1.01,0],[True,0],[0]):
            with self.assertRaises(ValueError):decode_decision(encoded,good|dict(point=point))

    def test_predict_receives_only_features_and_cannot_mutate_binding(self):
        frame=dict(done=False,token=dict(player=1,pid=999,nonce='private'),observation=self.obs,action_context=self.context)
        original=copy.deepcopy(frame);calls=[]
        def predict(features):
            calls.append(copy.deepcopy(features));features['entities'].clear()
            return dict(schema=DECISION_SCHEMA,contract_sha256=model_contract()['sha256'],op=OPERATIONS.index('stop'),unit=0)
        command=prepare_command(frame,predict)
        self.assertEqual(frame,original);self.assertEqual(command['token'],frame['token'])
        self.assertEqual(command['action'],action('stop',unit=[11,7]));self.assertEqual(len(calls),1)
        self.assertNotIn('private',json.dumps(calls))

    def test_predict_failure_has_no_fallback_action(self):
        frame=dict(done=False,token=dict(player=1),observation=self.obs,action_context=self.context)
        def broken(features):raise RuntimeError('inference failure')
        with self.assertRaisesRegex(RuntimeError,'inference failure'):prepare_command(frame,broken)

    def test_model_contract_mismatch_cannot_reinterpret_action_indices(self):
        encoded=self.encode();decision=encode_action(encoded,action('train',unit=[11,7],code='ugho'))
        self.assertEqual(PRODUCTS[decision['product']],'ugho')
        decision['contract_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'model_contract_mismatch'):decode_decision(encoded,decision)
        contract=model_contract();contract['products'].reverse()
        self.assertEqual(model_contract()['products'],list(PRODUCTS))

    def test_unknown_observation_fields_and_legacy_economy_fail_closed(self):
        self.obs['enemy_gold']=999
        with self.assertRaises(ValueError):self.encode()
        del self.obs['enemy_gold'];self.context['schema']=LEGACY_SCHEMA
        encoded=self.encode()
        with self.assertRaises(ValueError):encode_action(encoded,action('train',unit=[11,7],code='uaco'))

if __name__=='__main__':unittest.main()
