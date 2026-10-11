import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import psutil
import session
from undead.debug_console import DebugConsole,initialize_ui
import test_debug_console as display
from test_speed_control import FakeUI


class ColdUI:
    """SDK-shaped lazy UI: cold input and canvas setup exceed the old 5s wait."""
    def __init__(self,input_delay=13,canvas_delay=12,reject=False):
        self.wall=0;self.calls=[];self.cached=None;self.reject=reject
        self.delays={74:input_delay,73:canvas_delay}
        helper=display.MeterTests();self._w3fast=helper.game()._w3fast
        self._w3fast.OP.update(input_enable=74,canvas_enable=73)
        self.sender=self.send;self.lane=N(commands=self.sender)
        self.clock=lambda:1.5
    def send(self,calls,timeout=.25):
        for c in calls:
            self.calls.append((c.op,timeout))
            delay=self.delays.get(c.op,0)
            self.wall+=min(timeout,delay)
            if delay>timeout or self.reject:raise TimeoutError('runtime did not answer')
        return [N(ok=True) for c in calls]
    @property
    def ui(self):
        if self.cached is None:
            self.lane.commands([N(op=74)],timeout=5)
            self.lane.commands([N(op=73)],timeout=5)
            self.cached=FakeUI()
        return self.cached


class UIStartupTests(unittest.TestCase):
    def test_cold_start_reaches_console_and_restores_normal_command_timeouts(self):
        old=ColdUI()
        with self.assertRaises(TimeoutError):old.ui
        g=ColdUI();events=[]
        c=DebugConsole(g,lambda event,**data:events.append(event),clock=lambda:g.wall)
        self.assertEqual(g.wall,25)
        self.assertEqual(g.calls,[(74,45),(73,32)])
        self.assertEqual(c.meter.total,0)
        g.lane.commands([N(op=1)])
        self.assertEqual(g.calls[-1],(1,.25))
        self.assertEqual(c.meter.total,1)
        c.close();self.assertIs(g.lane.commands,g.sender)
        self.assertEqual(events,['ui_initializing','ui_ready'])

    def test_unresponsive_ui_is_bounded_and_sender_restored_without_meter(self):
        g=ColdUI(input_delay=60);events=[]
        with self.assertRaises(TimeoutError):
            DebugConsole(g,lambda event,**data:events.append(event),clock=lambda:g.wall)
        self.assertEqual(g.wall,45)
        self.assertIs(g.lane.commands,g.sender)
        self.assertNotIn('ui_ready',events)

    def test_second_enable_shares_budget_and_does_not_restart_it(self):
        g=ColdUI(input_delay=30,canvas_delay=20)
        with self.assertRaises(TimeoutError):initialize_ui(g,lambda *a,**k:None,lambda:g.wall)
        self.assertEqual(g.wall,45)
        self.assertEqual(g.calls,[(74,45),(73,15)])
        self.assertIs(g.lane.commands,g.sender)


class CleanupTests(unittest.TestCase):
    def exercise(self,mode):
        with tempfile.TemporaryDirectory() as tmp:
            s=session.Session();s.record=Path(tmp)/'session.json'
            s.owned=[dict(pid=11,created=1,name='war3_launch.exe'),dict(pid=12,created=2,name='War3-71.exe')]
            live={11,12};kills=[];wall=[0]
            def sleep(seconds):wall[0]+=seconds
            def kill(pid):
                kills.append(pid)
                if mode=='denied_live':raise psutil.AccessDenied(pid)
                if pid==11:
                    live.discard(11)
                    if mode=='job_exit':live.discard(12)
                elif mode=='exit_race':
                    live.discard(12);raise psutil.AccessDenied(12)
                else:live.discard(pid)
            def process(pid):
                if pid not in live:raise psutil.NoSuchProcess(pid)
                if mode=='identity_denied' and pid==12:raise psutil.AccessDenied(pid)
                return N(create_time=lambda:999 if mode=='reused' and pid==12 else pid-10,
                         name=lambda:'war3_launch.exe' if pid==11 else 'War3-71.exe',kill=lambda:kill(pid))
            if mode=='close_error':
                def close():raise RuntimeError('client close failed')
                s.game=N(end_game=lambda:None,close=close)
            with patch.object(session.psutil,'Process',side_effect=process), \
                 patch.object(session.time,'monotonic',side_effect=lambda:wall[0]), \
                 patch.object(session.time,'sleep',side_effect=sleep):
                if mode in ('denied_live','identity_denied','close_error'):
                    with self.assertRaises(RuntimeError):s.stop()
                else:s.stop()
            return kills,json.loads(s.record.read_text()),s.owned

    def test_launcher_job_exit_is_confirmed_without_killing_vanished_game(self):
        kills,record,owned=self.exercise('job_exit')
        self.assertEqual(kills,[11]);self.assertTrue(record['closed']);self.assertFalse(owned)
    def test_access_denied_during_actual_exit_is_rechecked(self):
        kills,record,owned=self.exercise('exit_race')
        self.assertEqual(kills,[11,12]);self.assertTrue(record['closed']);self.assertFalse(owned)
    def test_real_access_denial_keeps_session_open(self):
        kills,record,owned=self.exercise('denied_live')
        self.assertFalse(record['closed']);self.assertEqual(len(record['processes']),2)
    def test_reused_pid_is_never_killed(self):
        kills,record,owned=self.exercise('reused')
        self.assertEqual(kills,[11]);self.assertTrue(record['closed'])
    def test_unknown_identity_is_retained_and_never_killed(self):
        kills,record,owned=self.exercise('identity_denied')
        self.assertEqual(kills,[11]);self.assertFalse(record['closed'])
        self.assertEqual(record['processes'][0]['pid'],12)
    def test_client_close_failure_still_cleans_processes_and_preserves_error(self):
        kills,record,owned=self.exercise('close_error')
        self.assertEqual(kills,[11,12]);self.assertTrue(record['closed']);self.assertFalse(owned)
