import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from run_window import parse_deadline,ensure_time,DeadlineReached
import run_match
from session import Session

class WindowTests(unittest.TestCase):
    def test_expired_window_prevents_launch_and_records_aborted_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for f in ('session.py','run_match.py','game_preferences.py'):
                (root/f).write_text('fixture')
            started=[];closed=[]
            session=N(game=None,start=lambda **kw:started.append(True),stop=lambda:closed.append(True))
            with patch.multiple(run_match,ROOT=root,Session=lambda *a:session):
                result=run_match.run_match(until=1)
            self.assertEqual(started,[])
            self.assertTrue(closed)
            self.assertEqual((result['result'],result['reason']),('aborted','automation_deadline'))
            self.assertTrue(list((root/'artifacts').glob('*/result.json')))

    def test_session_rejects_cutoff_before_preferences_or_process_mutation(self):
        with patch('session.apply_defaults') as defaults,patch('session.farm.Farm') as farm:
            with self.assertRaises(DeadlineReached):Session().start(until=1)
            defaults.assert_not_called();farm.assert_not_called()

    def test_offset_required_and_exact_boundary_stops(self):
        with self.assertRaises(ValueError):parse_deadline('2026-10-09T00:00:00')
        end=parse_deadline('2026-10-09T00:00:00+08:00')
        with patch('run_window.time.time',return_value=end-.01):ensure_time(end)
        with patch('run_window.time.time',return_value=end):
            with self.assertRaises(DeadlineReached):ensure_time(end)
            ensure_time(None)
