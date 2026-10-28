import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

import human_practice
import run_match
import sparring
from undead.policy import Situation


class HumanPracticeRunnerTests(unittest.TestCase):
    def run_frames(self, frames, sparring_profile=None):
        """Drive the real runner loop; each frame is one process/window poll."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('session.py', 'run_match.py', 'game_preferences.py'):
                (root / name).write_text('fixture', encoding='utf-8')
            state = N(wall=0, frame=None, clock=1, epoch=73, reads=[], events=[],
                      orders=[], human_orders=[], starts=[], stopped=False, meter_closed=False,
                      closed=False, reads_after_close=[], opponent_orders=[])
            pending = iter(frames)
            initial = N(clock=1, epoch=73, in_game=True, speed_pct=100, publish_count=1, me=1)

            def alive():
                if state.closed:
                    return False
                frame = next(pending, None)
                if frame is None:
                    return False
                state.frame = frame
                state.wall = frame['wall']
                if frame.get('stop'):
                    (root / 'artifacts' / 'STOP').write_text('stop', encoding='utf-8')
                state.closed = not frame.get('alive', True)
                return frame.get('alive', True)

            def require_live_read(name):
                if state.closed and state.frame.get('reject_reads'):
                    state.reads_after_close.append(name)
                    raise RuntimeError('The game mapping has been closed')

            def snapshot(**kwargs):
                frame = state.frame
                state.reads.append(None if frame is None else frame['wall'])
                if frame is None:
                    return initial
                if frame.get('missing'):
                    return None
                state.clock = frame.get('clock', state.clock)
                return N(clock=state.clock, epoch=frame.get('epoch', state.epoch),
                         in_game=frame.get('in_game', True), speed_pct=100,
                         publish_count=frame.get('pub', 1), me=frame.get('me', 1))

            def events():
                state.events.append(state.wall)
                return []

            def raw_world():
                frame = state.frame
                if frame.get('raw_missing'):
                    return None
                return N(in_game=frame.get('raw_in_game', True),
                         epoch=frame.get('raw_epoch', state.epoch),
                         me=frame.get('raw_me', 0), terminal=frame.get('terminal'))

            def clock():
                require_live_read('clock')
                return state.clock

            def my_units():
                require_live_read('my_units')
                return []

            def send_order():
                # A gameplay operation records its recipient and original session.
                state.orders.append((g.player, state.epoch, state.clock, state.wall))
                if g.player == 0:
                    state.human_orders.append(state.clock)
                state.trace('attachment_commands_submitted', player=g.player, clock=state.clock)

            g = N(player=1, snapshot=snapshot, events=events,
                  world=N(read=raw_world), clock=clock,
                  my_units=my_units, resources=lambda: {}, all_production=lambda *args: [],
                  my_heroes=lambda: [], tech_many=lambda codes: {code: 0 for code in codes},
                  issue_order=send_order)

            def start():
                state.starts.append(g)
                return g

            def stop():
                state.stopped = True

            session = N(start=start, stop=stop, alive=alive,
                        active=lambda: state.frame.get('active', True), game=g,
                        settings={'controlled_player': 1, 'human_player': 0}, map_catalog=None)
            def tick_opponent(epoch):
                if not state.frame.get('opponent_ready',True):return False
                state.opponent_orders.append((2,epoch,state.clock,state.wall))
                return True
            session.start_opponent=lambda log:None
            session.tick_opponent=tick_opponent
            controllers = []

            def controller(game, log, enemy_race):
                controllers.append(game)
                return N(tick=game.issue_order, observe_events=lambda batch: None, situation=Situation(0))

            def meter(game, trace):
                self.assertIs(game, g)
                state.trace = trace
                return N(summary=lambda now: {'accepted_actions': len(state.orders)},
                         close=lambda: setattr(state, 'meter_closed', True))

            ordinary = Mock(side_effect=AssertionError('Ordinary Session would control P0'))
            console = Mock(side_effect=AssertionError('Bot HUD would capture human input'))
            with patch.multiple(run_match, ROOT=root, Session=ordinary, Controller=controller,
                                DebugConsole=console, ActionMeter=meter,
                                Referee=lambda: N(observe=lambda raw, *args: raw.terminal)), \
                 patch.object(human_practice, 'HumanPracticeSession', return_value=session), \
                 patch.object(human_practice, 'source_files', return_value=[]), \
                 patch.object(sparring, 'SparringSession', return_value=session), \
                 patch.object(sparring, 'source_files', return_value=[]), \
                 patch.object(run_match.time, 'monotonic', lambda: state.wall), \
                 patch.object(run_match.time, 'sleep', lambda seconds: None), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = run_match.run_match(speed=100, human_practice=sparring_profile is None,
                                             enemy_race=2,sparring=sparring_profile)
            folder = root / 'artifacts' / result['id']
            saved = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
            logged = [json.loads(line) for line in (folder / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(saved, result)
            self.assertIs(controllers[0], g)
            self.assertEqual(controllers, [g])
            self.assertEqual(state.starts, [g])
            self.assertTrue(state.stopped)
            self.assertTrue(state.meter_closed)
            self.assertFalse(state.human_orders)
            ordinary.assert_not_called()
            console.assert_not_called()
            return result, logged, state

    def test_two_bot_runner_stops_both_in_background_and_at_terminal_result(self):
        result,events,state=self.run_frames([
            {'wall':1,'clock':1}, {'wall':10,'active':False},
            {'wall':11,'clock':2}, {'wall':12,'clock':3,'terminal':('win','all_enemy_buildings_destroyed')},
        ],sparring_profile='human-rifle')
        self.assertEqual(state.orders,[(1,73,1,1),(1,73,2,11)])
        self.assertEqual(state.opponent_orders,[(2,73,1,1),(2,73,2,11)])
        self.assertEqual(result['mode'],'bot_vs_bot')
        self.assertEqual(result['observer_player'],0)
        self.assertNotIn('human_player',result)
        self.assertEqual(result['opponent']['controller'],'human-rifle')
        self.assertFalse(result['auto_restart'])

    def test_missing_opponent_snapshot_does_not_give_dayuan_free_ticks(self):
        _,_,state=self.run_frames([
            {'wall':1,'clock':1,'opponent_ready':False},
            {'wall':2,'clock':2}, {'wall':3,'alive':False},
        ],sparring_profile='human-fast-expand')
        self.assertEqual(state.orders,[(1,73,2,2)])
        self.assertEqual(state.opponent_orders,[(2,73,2,2)])

    def test_only_dayuan_player_receives_orders_and_game_exit_does_not_restart(self):
        result, events, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 2, 'clock': 2, 'pub': 2},
            {'wall': 3, 'alive': False},
        ])
        self.assertEqual([(player, epoch, clock) for player, epoch, clock, _ in state.orders],
                         [(1, 73, 1), (1, 73, 2)])
        self.assertEqual((result['result'], result['reason']), ('aborted', 'human_game_closed'))
        self.assertEqual(result['accepted_actions'], 2)
        self.assertFalse(result['auto_restart'])
        submitted = [row for row in events if row['event'] == 'practice_commands_submitted']
        self.assertEqual([(row['player'], row['clock']) for row in submitted], [(1, 1), (1, 2)])

    def test_long_background_and_stale_publication_resume_same_game_without_extra_orders(self):
        result, events, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 30, 'active': False},
            {'wall': 90, 'active': False},
            {'wall': 91, 'clock': 1},
            {'wall': 115, 'clock': 1},
            {'wall': 116, 'clock': 2},
            {'wall': 117, 'alive': False},
        ])
        self.assertEqual(state.reads, [None, 1, 91, 115, 116])
        self.assertEqual(state.events, [1, 91, 115, 116])
        self.assertEqual(state.orders, [(1, 73, 1, 1), (1, 73, 2, 116)])
        self.assertEqual((result['result'], result['reason']), ('aborted', 'human_game_closed'))
        self.assertEqual(result['game_seconds'], 2)
        resumed = next(row for row in events if row['event'] == 'clock_resumed')
        self.assertGreater(resumed['waited_wall_seconds'], 10)

    def test_changed_player_or_match_stops_before_ordering_the_new_snapshot(self):
        for changed in ({'me': 0}, {'epoch': 74}, {'in_game': False},
                        {'raw_me': 1}, {'raw_epoch': 74}, {'raw_in_game': False}):
            with self.subTest(changed=changed):
                result, _, state = self.run_frames([
                    {'wall': 1, 'clock': 1},
                    {'wall': 2, 'clock': 2, **changed},
                ])
                self.assertEqual(state.orders, [(1, 73, 1, 1)])
                self.assertEqual(result['reason'], 'practice_match_changed')
                self.assertFalse(result['auto_restart'])

    def test_stop_remains_effective_while_game_is_in_background(self):
        result, _, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 30, 'active': False, 'stop': True},
            {'wall': 31, 'active': False},
        ])
        self.assertEqual(state.orders, [(1, 73, 1, 1)])
        self.assertEqual(state.reads, [None, 1])
        self.assertEqual(result['reason'], 'user_stop')

    def test_missing_raw_world_suppresses_cached_orders_then_recovers(self):
        result, _, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 2, 'clock': 2, 'raw_missing': True},
            {'wall': 3, 'clock': 3},
            {'wall': 4, 'alive': False},
        ])
        self.assertEqual(state.orders, [(1, 73, 1, 1), (1, 73, 3, 3)])
        self.assertEqual(state.events, [1, 3])
        self.assertEqual(result['reason'], 'human_game_closed')

    def test_closed_mapping_does_not_turn_normal_exit_into_an_error(self):
        result, _, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 2, 'clock': 2},
            {'wall': 3, 'alive': False, 'reject_reads': True},
        ])
        self.assertEqual((result['result'], result['reason']), ('aborted', 'human_game_closed'))
        self.assertEqual(result['game_seconds'], 2)
        self.assertEqual(result['units_at_end_basis'], 'last_summary_before_process_exit')
        self.assertFalse(state.reads_after_close)

    def test_terminal_game_finishes_without_sending_another_order_or_restarting(self):
        result, events, state = self.run_frames([
            {'wall': 1, 'clock': 1},
            {'wall': 2, 'clock': 2, 'terminal': ('win', 'all_enemy_buildings_destroyed')},
        ])
        self.assertEqual(state.orders, [(1, 73, 1, 1)])
        self.assertEqual((result['result'], result['reason']), ('win', 'all_enemy_buildings_destroyed'))
        self.assertIn('terminal_confirmed', [row['event'] for row in events])
        self.assertFalse(result['auto_restart'])


if __name__ == '__main__':
    unittest.main()
