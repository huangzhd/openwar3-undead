import copy
from types import MethodType, SimpleNamespace as N
import unittest

import bootstrap
import w3world
from openwar3 import Game
from learning import hero_skills
from learning.actions import HERO_SCHEMA, preflight, validate
from learning.effects import transition_facts
from learning.model_codec import decode_decision, encode_action, encode_observation
from learning.observation_schema import ObservationError, validate as check_observation
import test_learning_actions as primitives


class LearnSkillTests(unittest.TestCase):
    run_action = primitives.PrimitiveTests.run_action

    def setUp(self):
        primitives.PrimitiveTests.setUp(self)
        self.own.type = 'Udea'
        self.own.flags |= w3world.HERO
        self.own.abilities.append(N(code='AHer',level=1,cooldown=0))
        self.own.skill_points = self.own.level = 1
        self.seen.type = 'Ulic'
        self.seen.skill_points = 7
        self.game.learn = MethodType(Game.learn, self.game)
        self.action = primitives.action('learn_skill', unit=[11,7], skill='AUdc')
        self.raw.clock += 1
        self.rec.observe()
        self.decision = copy.deepcopy(self.rec.last_observation)

    def test_command_matches_sdk_and_only_own_points_enter_model(self):
        receipt = self.run_action(self.action)
        self.assertTrue(receipt['accepted'])
        self.assertEqual(self.decision['hero_skill_points'],[dict(unit=[11,7],points=1)])
        self.assertEqual(self.native.call_args.args[0][0].args[3],int.from_bytes(b'AUdc','big'))
        encoded=encode_observation(self.decision,dict(schema=self.action['schema'],bounds=self.executor.bounds),
                                   'strict-p1-observation-v5')
        self.assertEqual(decode_decision(encoded,encode_action(encoded,self.action)),self.action)
        self.assertEqual(encoded.features['entities'][0]['skill_points']['values'],[.1])
        self.assertNotIn('skill_points',encoded.features['entities'][1])
        forged=copy.deepcopy(self.decision)
        forged['hero_skill_points'][0]['unit']=[22,7]
        with self.assertRaises(ObservationError):check_observation(forged,'strict-p1-observation-v5')

    def test_stale_point_and_skill_prerequisites_never_submit(self):
        for skill,reason in [('AUfn','skill_not_in_hero_kit'),('AUan','hero_level_too_low')]:
            self.assertEqual(self.run_action(dict(self.action,skill=skill))['reason'],reason)
        self.own.skill_points=0
        self.assertEqual(self.run_action(self.action)['reason'],'no_skill_points')
        self.own.skill_points=1
        self.own.level=2
        self.assertEqual(self.run_action(self.action)['reason'],'skill_rank_unknown')
        self.own.abilities.append(N(code='AUdc',level=1,cooldown=0))
        self.assertEqual(self.run_action(self.action)['reason'],'hero_level_too_low')
        self.native.assert_not_called()

    def test_rank_cap_and_legacy_schema(self):
        self.own.level=7
        self.own.abilities.append(N(code='AUdc',level=3,cooldown=0))
        self.assertEqual(self.run_action(self.action)['reason'],'skill_at_max_rank')
        with self.assertRaises(ValueError):validate(dict(self.action,schema=HERO_SCHEMA))
        for skill in ('AHbz','Amov',42):
            with self.assertRaises(ValueError):validate(dict(self.action,skill=skill))
        self.native.assert_not_called()

    def test_partial_birth_publication_cannot_authorize_learning(self):
        self.own.flags &= ~w3world.HERO
        self.assertEqual(self.run_action(self.action)['reason'],'skill_points_unknown')
        self.own.flags |= w3world.HERO
        self.own.abilities=[]
        self.assertEqual(self.run_action(self.action)['reason'],'skill_points_unknown')
        self.native.assert_not_called()

    def test_missing_detail_or_unaccounted_spending_does_not_imply_rank_zero(self):
        before=copy.deepcopy(self.decision)
        u=before['units'][0]
        u['level']=3
        self.assertIsNone(hero_skills.learned_rank(u,'AUdc',1))
        u['abilities'].append(dict(code='AUau',level=2,cooldown=0))
        self.assertEqual(hero_skills.learned_rank(u,'AUdc',1),0)
        before['hero_skill_points'][0]['points']=None
        self.assertEqual(preflight(self.action,before,self.executor.bounds),'skill_points_unknown')

    def test_point_and_rank_evidence_are_separate_from_receipt(self):
        after=copy.deepcopy(self.decision)
        after['clock']+=1
        after['hero_skill_points'][0]['points']=0
        facts=transition_facts(self.action,self.decision,after)
        self.assertEqual((facts['skill_points_before'],facts['skill_points_after']),(1,0))
        self.assertIsNone(facts['skill_rank_after'])
        after['units'][0]['abilities'].append(dict(code='AUdc',level=1,cooldown=0))
        facts=transition_facts(self.action,self.decision,after)
        self.assertEqual((facts['skill_rank_before'],facts['skill_rank_after']),(0,1))
        self.assertFalse(facts['causally_attributed'])
