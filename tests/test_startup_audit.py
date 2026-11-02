import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock, patch
from startup_audit import StartupAudit


class StartupAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.raw = N(in_game=True, me=0, epoch=7, clock=2.)
        self.session = N(game=N(world=N(read=lambda:self.raw)), settings={},
                         active=Mock(return_value=True), startup_log=Mock())
        def sleep(seconds):
            self.now += seconds
            if self.session.active():self.raw.clock += seconds
        clock = N(monotonic=lambda:self.now, sleep=sleep)
        self.patch = patch('startup_audit.time', clock)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.audit = StartupAudit(self.session, 1.)

    def test_no_native_before_foreground_and_clock_progress(self):
        self.session.active.return_value = False
        native = Mock()
        client = N(jass=N(call=native))
        with self.audit.trace_client(client):
            with self.assertRaises(TimeoutError):client.jass.call('PauseCompAI', 1, True)
        native.assert_not_called()
        self.assertIs(client.jass.call, native)

    def test_foreground_progress_then_native_failure_is_not_retried(self):
        self.audit.wait_ready()
        native = Mock(side_effect=RuntimeError('GetLocalPlayer timeout'))
        client = N(jass=N(call=native))
        with self.audit.trace_client(client):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                client.jass.call('PauseCompAI', 1, True)
        native.assert_called_once_with('PauseCompAI', 1, True)
        failed = [c for c in self.session.startup_log.call_args_list if c.args[0]=='startup_native_failed']
        self.assertIn('GetLocalPlayer', failed[0].kwargs['error'])
        self.assertIs(client.jass.call, native)

    def test_background_sparring_accepts_advancing_clock_and_executes_native(self):
        self.session.background_allowed=True
        self.session.active.return_value=False
        def sleep(seconds):
            self.now+=seconds;self.raw.clock+=seconds
        native=Mock(return_value=123);client=N(jass=N(call=native))
        with patch('startup_audit.time.sleep',side_effect=sleep):self.audit.wait_ready()
        with self.audit.trace_client(client):
            self.assertEqual(client.jass.call('Player',1),123)
        native.assert_called_once_with('Player',1)

    def test_epoch_change_rejects_next_native(self):
        self.audit.wait_ready();self.raw.epoch = 8
        native = Mock();client = N(jass=N(call=native))
        with self.audit.trace_client(client):
            with self.assertRaisesRegex(RuntimeError, 'epoch'):client.jass.call('Player', 1)
        native.assert_not_called()

    def test_stalled_foreground_clock_times_out_and_preserves_failed_stage(self):
        with patch('startup_audit.time.sleep', side_effect=lambda seconds:setattr(self,'now',self.now+seconds)):
            with self.assertRaises(TimeoutError):
                with self.audit.stage('foreground_clock_readiness'):self.audit.wait_ready()
        self.assertEqual(self.session.settings['startup_stage'], 'foreground_clock_readiness')
        self.assertTrue(any(c.args[0]=='startup_stage_failed' for c in self.session.startup_log.call_args_list))

    def test_delayed_speed_requires_exact_value_and_keeps_original_epoch(self):
        self.session.speed=400
        snapshot=N(speed_pct=100,epoch=7,clock=1.)
        self.assertFalse(self.audit.speed_ready(snapshot))
        self.now=.2;snapshot.speed_pct=200
        self.assertFalse(self.audit.speed_ready(snapshot))
        self.now=.4;snapshot.speed_pct=400;snapshot.clock=1.4
        self.assertTrue(self.audit.speed_ready(snapshot))
        events=self.session.startup_log.call_args_list
        self.assertEqual([c.args[0] for c in events],['startup_speed_wait','startup_speed_ready'])
        self.assertEqual(events[-1].kwargs['waited_wall_seconds'],.4)
        snapshot.epoch=8
        with self.assertRaisesRegex(RuntimeError,'epoch'):self.audit.speed_ready(snapshot)

    def test_pending_speed_times_out_even_without_another_snapshot(self):
        self.session.speed=400;self.audit.deadline=120
        self.assertFalse(self.audit.speed_ready(N(speed_pct=100,epoch=7,clock=1.)))
        self.now=5
        with self.assertRaisesRegex(TimeoutError,'speed'):self.audit.check_deadline()
        self.assertFalse(any(c.args[0]=='startup_speed_ready' for c in self.session.startup_log.call_args_list))

    def test_speed_wait_never_extends_outer_startup_deadline(self):
        self.session.speed=400
        self.assertFalse(self.audit.speed_ready(N(speed_pct=100,epoch=7,clock=1.)))
        self.now=1
        with self.assertRaisesRegex(TimeoutError,'readiness'):self.audit.speed_ready(N(speed_pct=400,epoch=7,clock=2.))


if __name__ == '__main__':unittest.main()
