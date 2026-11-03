import unittest

from learning.tactical_review import annotate, cases_from_events


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
