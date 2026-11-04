import unittest
from copy import deepcopy

from learning.tactical_review import annotate, cases_from_events, execution_chains
from learning.trajectory import UNIT_FIELDS


class ExecutionChainTests(unittest.TestCase):
    def fixture(self):
        unit = dict(handle=[1,2], type='Udea', owner=1, alive=True,
                    inventory=['rnec',None,None,None,None,None],
                    abilities=[dict(code='AIrd',level=1,cooldown=0)],
                    **{k:0 for k in UNIT_FIELDS})
        obs = dict(player=1, clock=10, resources=None, units=[unit], production=[], last_seen=[])
        later = deepcopy(obs); later['clock']=11
        later['units'][0]['abilities'][0]['cooldown']=21
        skel=deepcopy(unit);skel.update(handle=[3,4],type='uske')
        later['units'].append(skel)
        return [dict(event='observation',id=1,observation=obs),
                dict(event='action_request',id=7,observation_id=1,clock=10,
                     action=dict(op='use_item',unit=[1,2],target=None)),
                dict(event='action_receipt',id=7,accepted=True,status=0),
                dict(event='observation',id=2,observation=later)]

    def chains(self, rows, fingerprint='hash'):
        return execution_chains(rows,'episode',fingerprint,'strict-p1-observation-v1')

    def test_observed_summon_is_not_causal_label_or_reconstructed_action(self):
        chain, = self.chains(self.fixture())
        self.assertEqual(chain['observable_changes']['newly_observed_own_units'][0]['handle'],[3,4])
        self.assertEqual(chain['observable_changes']['source_after']['abilities'][0]['cooldown'],21)
        self.assertFalse(chain['observable_changes']['causally_attributed'])
        self.assertEqual(chain['effect'],'unverified')
        self.assertIsNone(chain['selection_link'])
        self.assertNotIn('slot',chain['action'])

    def test_missing_receipt_and_timeout_remain_unknown(self):
        rows=self.fixture();del rows[2]
        chain,=self.chains(rows)
        self.assertEqual(chain['receipt_state'],'unknown')
        self.assertIsNone(chain['observable_changes'])
        rows=self.fixture();rows[2]['status']=99
        self.assertEqual(self.chains(rows)[0]['receipt_state'],'unknown')

    def test_rejection_and_no_later_observation_remain_reviewable(self):
        rows=self.fixture();rows[2]['accepted']=False
        chain,=self.chains(rows[:-1])
        self.assertEqual(chain['receipt_state'],'rejected')
        self.assertTrue(chain['needs_review'])
        self.assertIsNone(chain['after_clock'])
        rows[-1]['observation']['clock']=13
        self.assertIsNone(self.chains(rows)[0]['observable_changes'])

    def test_duplicates_future_references_and_non_p1_rejected(self):
        for mutation in ('duplicate','future','player','clock'):
            rows=self.fixture()
            if mutation=='duplicate':rows.insert(3,deepcopy(rows[2]))
            if mutation=='future':rows[1]['observation_id']=2
            if mutation=='player':rows[-1]['observation']['player']=0
            if mutation=='clock':rows[-1]['observation']['clock']=9
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):self.chains(rows)

    def test_intervening_requests_are_exposed(self):
        rows=self.fixture(); req=deepcopy(rows[1]);req['id']=8
        rows.insert(3,req)
        self.assertEqual(self.chains(rows)[0]['intervening_request_ids'],[8])

    def test_environment_note_is_bound_to_trajectory_and_stays_separate(self):
        chain,=self.chains(self.fixture())
        report=dict(cases=[],execution_chains=[chain])
        note=dict(id=chain['id'],judgment='environment',explanation='matched slot experiment')
        annotate(report,[note])
        self.assertEqual(chain['human_review']['judgment'],'environment')
        self.assertEqual(chain['attribution'],'undetermined')
        changed,=self.chains(self.fixture(),'changed')
        with self.assertRaises(ValueError):annotate(dict(cases=[],execution_chains=[changed]),[note])


class TacticalReviewTests(unittest.TestCase):
    def test_concurrent_scout_and_army_keep_separate_context_and_outcomes(self):
        events = [
            dict(clock=1, event='decision', actual='CREEP', p2_gold=800, heroes=1),
            dict(clock=2, event='creep_goal', camp='lr-6'),
            dict(clock=3, event='scout_assigned', handle=[8, 9]),
            dict(clock=4, event='scout_search_started', point=[10, 20]),
            dict(clock=5, event='practice_commands_submitted', batch_id=1, commands=[
                dict(index=i, op='point', args=[1, unit, 9, 851986]) for i, unit in enumerate([8, 7, 8])]),
            dict(clock=6, event='practice_commands_completed', batch_id=1, receipts=[
                dict(index=0, ok=True), dict(index=1, ok=False)]),
            dict(clock=7, event='scout_search_finished', point=[20, 30], reason='arrived'),
            dict(clock=8, event='creep_area_cleared', camp='lr-6'),
            dict(clock=9, event='decision', actual='ATTACK', heroes=2),
            dict(clock=10, event='scout_search_finished', point=[10, 20], reason='no_progress_or_budget'),
        ]
        army, camp, scout, _ = cases_from_events(events, 'episode', 'hash')
        self.assertEqual(camp['army_decision_id'], army['id'])
        self.assertEqual(camp['end']['status'], 'area_observed_clear')
        self.assertEqual(scout['decision_context'], dict(clock=1, heroes=1))
        self.assertIsNone(scout['candidates'])
        self.assertEqual(scout['movement_receipts'], dict(accepted=1, unknown=1, rejected=0))
        self.assertEqual(scout['end']['clock'], 10)
        self.assertTrue(scout['needs_review'])
        self.assertEqual(scout['attribution'], 'undetermined')

    def test_human_judgment_bound_to_original_log(self):
        events = [dict(clock=1, event='decision', actual='CREEP')]
        case, = cases_from_events(events, 'episode', 'original')
        other, = cases_from_events(events, 'episode', 'different-log')
        note = dict(id=case['id'], judgment='execution', explanation='绕行点使侍僧远离目标')
        with self.assertRaises(ValueError):
            annotate(dict(cases=[other]), [note])
        with self.assertRaises(ValueError):
            annotate(dict(cases=[case]), [note, note])
        self.assertNotIn('human_review', case)
        annotate(dict(cases=[case]), [note])
        self.assertEqual(case['human_review']['source'], 'human_review')
        self.assertEqual(case['whole_game_cause'], 'not_established')
