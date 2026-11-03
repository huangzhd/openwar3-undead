import copy
import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock

from test_learning_economy_actions import EconomicPrimitiveTests as _Economy
from test_learning_actions import action
from test_learning_trajectory import unit
from learning.actions import HALL_SCHEMA, validate
from learning.dataset import native_payload
from learning.model_codec import encode_action,encode_observation,decode_decision
from learning.observation_schema import validate as check_observation,ObservationError
from learning.research import costs

_setup=_Economy.setUp
_refresh=_Economy.refresh
_rows=_Economy.rows
_run=_Economy.run_action
del _Economy


class ResearchTests(unittest.TestCase):
    refresh=_refresh
    rows=_rows
    run_action=_run

    def setUp(self):
        _setup(self)
        self.crypt=self.hall
        self.crypt.type='ugrv'
        self.base=unit(1,79,type='unpl')
        self.raw.units.append(self.base)
        self.game.tech=Mock(return_value=0)
        self.cmd=action('research',unit=[44,7],code='Rura',level=1)
        self.read=action('inspect_research',code='Rura')
        self.refresh()

    def inspect(self,code='Rura'):
        r=self.run_action(action('inspect_research',code=code))
        self.refresh()
        return r

    def test_explicit_p1_query_and_zero_is_valid_unknown_is_not(self):
        self.assertEqual(self.run_action(self.cmd)['reason'],'research_level_unknown')
        r=self.inspect()
        self.assertEqual((r['status'],r['native_request_ids']),('observation_only',[]))
        self.game.tech.assert_called_with('Rura',player=1)
        self.assertEqual(self.decision['research_levels']['Rura']['level'],0)
        self.game.tech.return_value=None
        self.assertEqual(self.inspect()['reason'],'research_level_unknown')
        self.assertIsNone(self.decision['research_levels']['Rura']['level'])
        self.native.assert_not_called()

    def test_goal_level_changed_or_stale_cannot_spend_on_next_upgrade(self):
        self.inspect()
        self.game.tech.return_value=1
        self.assertEqual(self.run_action(self.cmd)['reason'],'research_level_changed')
        self.raw.clock+=9;self.refresh()
        self.assertEqual(self.run_action(self.cmd)['reason'],'research_level_stale')
        self.native.assert_not_called()

    def test_exact_cost_next_level_tier_and_same_clock_queue(self):
        self.game.tech.return_value=1
        self.inspect()
        cmd=self.cmd|dict(level=2)
        self.assertEqual(self.run_action(cmd)['reason'],'research_prerequisites_missing')
        self.base.type='unp1';self.refresh()
        self.raw.players[1].lumber=124
        self.assertEqual(self.run_action(cmd)['reason'],'insufficient_lumber')
        self.raw.players[1].lumber=125
        self.raw.production=[N(building=self.crypt.handle,kind='queue',queue=['Rura'],progress=.3)]
        self.assertEqual(self.run_action(cmd)['reason'],'research_production_busy')
        self.raw.production=[]
        self.game.can_do=lambda *args:183
        self.assertEqual(self.run_action(cmd)['reason'],'engine_prerequisites_rejected')
        self.native.assert_not_called()
        self.game.can_do=lambda *args:0
        r=self.run_action(cmd)
        self.assertTrue(r['accepted'])
        self.assertEqual(self.native.call_args.args[0][0].args[3],native_payload(cmd)['code'])
        encoded=encode_observation(self.decision,dict(schema=cmd['schema'],bounds=self.executor.bounds),'strict-p1-observation-v5')
        for a in (self.read,cmd):
            self.assertEqual(decode_decision(encoded,encode_action(encoded,a)),a)

    def test_web_needs_ready_graveyard_tier_two_and_known_level(self):
        self.crypt.type='usep';self.base.type='unp1'
        self.inspect('Ruwb')
        cmd=self.cmd|dict(code='Ruwb')
        self.assertEqual(self.run_action(cmd)['reason'],'research_prerequisites_missing')
        self.raw.units.append(unit(1,84,type='ugrv'))
        self.refresh()
        self.assertTrue(self.run_action(cmd)['accepted'])
        with self.assertRaises(ValueError):validate(cmd|dict(level=2))
        with self.assertRaises(ValueError):validate(cmd|dict(schema=HALL_SCHEMA))
        with self.assertRaises(ValueError):validate(cmd|dict(level=True))

    def test_research_observations_reject_future_or_out_of_range_levels(self):
        self.inspect()
        for changes in [dict(clock=self.decision['clock']+1),dict(level=4),dict(level=True),dict(player=2)]:
            obs=copy.deepcopy(self.decision)
            obs['research_levels']['Rura'].update(changes)
            with self.assertRaises(ObservationError):check_observation(obs,'strict-p1-observation-v5')
