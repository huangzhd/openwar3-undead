import unittest

from learning.outcome import classify_outcome


class OutcomeTests(unittest.TestCase):
    def test_only_matching_independent_terminal_can_reward(self):
        for outcome, reason, reward in (
                ('win', 'all_enemy_buildings_destroyed', 1),
                ('loss', 'all_own_buildings_destroyed', -1)):
            for confirmed in (False, True, 1):
                result = classify_outcome(outcome, reason, natural_confirmed=confirmed)
                self.assertEqual(result['reward'], reward if confirmed is True else None)
                self.assertEqual(result['terminated'], confirmed is True)
                self.assertEqual(result['truncated'], confirmed is not True)
        for outcome, reason in (('win', 'all_own_buildings_destroyed'),
                                ('loss', 'manual_surrender'), ('unknown', None)):
            result = classify_outcome(outcome, reason, natural_confirmed=True)
            self.assertIsNone(result['reward'])
            self.assertFalse(result['terminated'])

    def test_failure_abort_cutoff_and_disconnect_preserve_distinct_meanings(self):
        cases = [
            ('loss', 'manual_surrender', 'user_abort'),
            ('aborted', 'user_stop', 'user_abort'),
            ('aborted', 'manual_restart', 'user_abort'),
            ('aborted', 'environment_close', 'user_abort'),
            ('timeout', 'game_time_limit', 'time_limit'),
            ('aborted', 'automation_deadline', 'time_limit'),
            ('timeout', 'stage_time_limit', 'runtime_failure'),
            ('error', 'JassError(secret diagnostic)', 'runtime_failure'),
            ('aborted', 'human_game_closed', 'process_exit'),
            ('aborted', 'game_epoch_changed', 'epoch_changed'),
            ('aborted', 'practice_match_changed', 'epoch_changed'),
            ('unknown', 'not_started', 'incomplete'),
        ]
        for outcome, reason, category in cases:
            with self.subTest(reason=reason):
                result = classify_outcome(outcome, reason, natural_confirmed=True)
                self.assertEqual(result['classification'], category)
                self.assertTrue(result['truncated'])
                self.assertIsNone(result['reward'])
        failure = classify_outcome('error', 'JassError(secret diagnostic)')
        self.assertEqual(failure['reason'], 'other')


if __name__ == '__main__':
    unittest.main()
