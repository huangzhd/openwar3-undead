import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

import bootstrap
from openwar3 import Game as SDKGame
from undead.game_view import Game
from undead.player_visibility import PlayerVisibility
from run_guard import RunGuard, RunInterrupted
import run_guard


def client():
    raw = N(in_game=True, me=0, epoch=1, clock=10., speed_pct=400)
    dev = N(pid=101, world=N(read=Mock(return_value=raw)), close=Mock(),
            jass=N(Player=Mock(side_effect=lambda p:100+p),
                   IsVisibleToPlayer=Mock(side_effect=lambda x,y,p:p==100)))
    return dev, raw


class PlayerVisibilityTests(unittest.TestCase):
    def test_rule_p1_does_not_use_observer_query_even_when_it_returns_true(self):
        dev, raw = client()
        game = object.__new__(Game);game.pid=101;game.player=1;game.fair=True;game.world=dev.world
        with patch('undead.game_view.SDKGame',return_value=dev):game.bind_player_visibility()
        with patch.object(SDKGame,'visible',return_value=True) as old:
            self.assertIs(game.visible(3840,3328),False)
            old.assert_not_called()
        dev.jass.Player.assert_called_once_with(1)
        dev.jass.IsVisibleToPlayer.assert_called_once_with(3840.,3328.,101)

    def test_p2_uses_its_own_slot_and_player_handle_is_reused_only_in_same_epoch(self):
        dev, raw = client();oracle = PlayerVisibility(dev,101,1,player=2)
        oracle.query(1,2);oracle.query(3,4)
        dev.jass.Player.assert_called_once_with(2)
        self.assertEqual(dev.jass.IsVisibleToPlayer.call_args.args[-1],102)
        raw.epoch=2
        self.assertIsNone(oracle.query(1,2)['visible'])
        self.assertEqual(dev.jass.IsVisibleToPlayer.call_count,2)

    def test_unbound_changed_slot_or_pid_and_native_errors_never_fall_back(self):
        game=object.__new__(Game);game.pid=101;game.player=1
        with patch.object(SDKGame,'visible',return_value=True) as old:
            self.assertIsNone(game.visible(1,2))
            dev,raw=client();game._player_visibility=PlayerVisibility(dev,101,1)
            dev.jass.IsVisibleToPlayer.side_effect=RuntimeError('native unavailable')
            self.assertIsNone(game.visible(1,2))
            game.player=2;self.assertIsNone(game.visible(1,2))
            game.player=1;game.pid=102;self.assertIsNone(game.visible(1,2))
            old.assert_not_called()

    def test_local_player_mode_retains_existing_sdk_query(self):
        game=object.__new__(Game);game.player=None
        with patch.object(SDKGame,'visible',return_value=True) as old:
            self.assertTrue(game.visible(1,2));old.assert_called_once_with(1,2)

    def test_native_error_is_unknown_but_cutoff_propagates(self):
        dev,raw=client();oracle=PlayerVisibility(dev,101,1)
        dev.jass.IsVisibleToPlayer.side_effect=RunInterrupted('game_time_limit',180)
        with self.assertRaises(RunInterrupted):oracle.query(1,2)

    def test_binding_failure_closes_dev_client_and_normal_close_still_closes_player_lane(self):
        dev,raw=client();game=object.__new__(Game)
        game.pid=101;game.player=1;game.fair=True;game.world=dev.world
        with patch('undead.game_view.SDKGame',return_value=dev), \
             patch('undead.player_visibility.PlayerVisibility',side_effect=ValueError('binding failed')):
            with self.assertRaises(ValueError):game.bind_player_visibility()
        dev.close.assert_called_once()
        game._player_visibility=N(close=Mock(side_effect=RuntimeError('close failed')))
        with patch.object(SDKGame,'close') as original:
            with self.assertRaises(RuntimeError):game.close()
            original.assert_called_once()


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'timing.jsonl'
        self.raw=N(in_game=True,me=0,epoch=1,clock=10.,speed_pct=400)
        self.game=N(world=N(read=Mock(return_value=self.raw)),lane=N(run=Mock(return_value=['receipt'])))
        self.wall=100.;self.mono=0.
        clock=N(time=lambda:self.wall,perf_counter=lambda:self.mono)
        self.clock_patch=patch.object(run_guard,'time',clock);self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)

    def guard(self,**kwargs):
        guard=RunGuard(self.game,self.path,**kwargs);guard.attach(self.game,'P1')
        self.addCleanup(guard.close)
        return guard

    def test_live_clock_blocks_native_call_despite_stale_controller_snapshot(self):
        original=self.game.lane.run;guard=self.guard(game_limit=11)
        self.raw.clock=11
        with self.assertRaises(RunInterrupted) as caught:self.game.lane.run(['move'])
        self.assertEqual(caught.exception.reason,'game_time_limit')
        original.assert_not_called()
        guard.close();self.game.lane.run(['cleanup'])
        original.assert_called_once_with(['cleanup'])

    def test_wait_timeout_is_capped_by_remaining_game_time(self):
        original=self.game.lane.run;guard=self.guard(game_limit=10.2)
        self.assertEqual(self.game.lane.run(['query'],timeout=5),['receipt'])
        self.assertAlmostEqual(original.call_args.kwargs['timeout'],.05)

    def test_stage_budget_cannot_be_swallowed_by_strategy_exception_fallback(self):
        guard=self.guard(stage_seconds=2)
        with self.assertRaises(RunInterrupted) as caught:
            with guard.stage('controller_tick'):
                self.mono=2.1
                try:self.game.world.read()
                except Exception:self.fail('cutoff swallowed by generic strategy handler')
        self.assertEqual(caught.exception.reason,'stage_time_limit')
        guard.close()
        rows=[json.loads(s) for s in self.path.read_text().splitlines()]
        self.assertTrue(any(r['event']=='cutoff' and r['stage']=='controller_tick' for r in rows))
        self.assertGreater(rows[-1]['statistics']['stage:controller_tick']['max_seconds'],2)

    def test_slow_read_detected_after_return_and_timed_not_mislabeled(self):
        def slow():self.mono+=3;return self.raw
        guard=self.guard(stage_seconds=2)
        # The stage's original checkpoint read is deliberately slow.
        guard.read=slow
        with self.assertRaises(RunInterrupted):
            with guard.stage('controller_tick'):pass
        self.assertGreaterEqual(guard.stats['checkpoint_read']['max_seconds'],3)

    def test_clock_jump_mid_native_call_stops_before_next_order(self):
        original=self.game.lane.run
        def native(calls,timeout):self.raw.clock=181.;return ['receipt']
        original.side_effect=native
        self.guard(game_limit=180)
        with self.assertRaises(RunInterrupted):self.game.lane.run(['first'])
        with self.assertRaises(RunInterrupted):self.game.lane.run(['second'])
        self.assertEqual(original.call_count,1)

    def test_wall_deadline_stops_with_frozen_game_clock(self):
        self.guard(until=101)
        self.wall=101
        with self.assertRaises(RunInterrupted) as caught:self.game.lane.run(['move'])
        self.assertEqual(caught.exception.reason,'automation_deadline')

    def test_epoch_change_rejects_old_game_and_close_restores_all_hooks(self):
        original_read=self.game.world.read;original_run=self.game.lane.run
        guard=self.guard();self.raw.epoch=2
        with self.assertRaises(RunInterrupted) as caught:self.game.world.read()
        self.assertEqual(caught.exception.reason,'game_epoch_changed')
        guard.close();guard.close()
        self.assertIs(self.game.world.read,original_read);self.assertIs(self.game.lane.run,original_run)


if __name__=='__main__':unittest.main()
