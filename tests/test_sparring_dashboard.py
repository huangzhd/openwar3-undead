import json
import os
from pathlib import Path
import tempfile
import unittest

from sparring_dashboard import DashboardModel, EventTail


class Backend:
    def __init__(self, pid):
        self.state = dict(epoch=1, clock=40, speed=100, camera=1650, background=False)
        self.calls = []
        self.closed = False

    def read(self):
        return dict(self.state)

    def set(self, kind, value):
        self.calls.append((kind, value))
        return True

    def close(self):
        self.closed = True


class DashboardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.a = self.root / 'artifacts'
        self.run = self.a / '20261029-123000'
        self.run.mkdir(parents=True)
        self.session = dict(processes=[dict(pid=123, created=1000, name='War3-73.exe')])
        self.save_session()
        manifest = self.run / 'source-manifest.json'
        manifest.write_text('{}')
        os.utime(manifest, (990, 990))
        self.events = self.run / 'events.jsonl'
        self.events.write_text(json.dumps(dict(event='match_settings', settings=dict(mode='bot_vs_bot', opponent_profile='human-rifle'))) + '\n')
        self.now = 10
        self.model = DashboardModel(self.root, Backend, lambda row: True, lambda: self.now)
        self.addCleanup(self.model.close)

    def save_session(self):
        (self.a / 'session.json').write_text(json.dumps(self.session))

    def test_observed_confirmation_not_receipt(self):
        s = self.model.poll()
        pending = self.model.request(s['token'], 'speed', 400)
        self.assertEqual(pending['speed'], 100)
        self.assertIsNotNone(pending['pending'])
        self.model.backend.state['speed'] = 400
        confirmed = self.model.poll()
        self.assertIsNone(confirmed['pending'])
        audit = [json.loads(x) for x in (self.run / 'spectator-controls.jsonl').read_text().splitlines()]
        self.assertEqual([r['status'] for r in audit], ['accepted', 'confirmed'])
        self.assertEqual(audit[-1]['actual'], 400)

    def test_old_session_and_epoch_requests_cannot_write(self):
        token = self.model.poll()['token']
        backend = self.model.backend
        backend.state['epoch'] = 2
        with self.assertRaises(RuntimeError):
            self.model.request(token, 'speed', 800)
        self.assertEqual(backend.calls, [])
        self.assertTrue(backend.closed)
        self.session['closed'] = True
        self.save_session()
        with self.assertRaises(RuntimeError):
            self.model.request(token, 'camera', 6000)

    def test_bounds_and_unconfirmed_timeout(self):
        token = self.model.poll()['token']
        for kind, value in [('speed', 900), ('speed', True), ('camera', 6001), ('camera', 499), ('stop', 1)]:
            with self.assertRaises(ValueError):
                self.model.request(token, kind, value)
        self.assertEqual(self.model.backend.calls, [])
        self.model.request(token, 'camera', 6000)
        self.now += 6
        s = self.model.poll()
        self.assertIsNone(s['pending'])
        self.assertEqual(s['camera'], 1650)
        self.assertIn('尚未确认', s['message'])

    def test_completed_match_does_not_accept_control(self):
        token = self.model.poll()['token']
        backend = self.model.backend
        (self.run / 'result.json').write_text('{"result":"loss"}')
        with self.assertRaises(RuntimeError):
            self.model.request(token, 'speed', 200)
        self.assertEqual(backend.calls, [])

    def test_partial_utf8_lines_and_replacement(self):
        tail = EventTail()
        line = json.dumps(dict(event='summary', text='木材', clock=50), ensure_ascii=False).encode() + b'\n'
        with self.events.open('ab') as f:
            f.write(line[:-3])
        self.assertNotIn('summary', tail.read(self.events))
        with self.events.open('ab') as f:
            f.write(line[-3:])
        self.assertEqual(tail.read(self.events)['summary']['text'], '木材')
        self.events.write_text('{"event":"summary","clock":2}\n')
        self.assertEqual(tail.read(self.events)['summary']['clock'], 2)

    def test_human_practice_and_old_run_are_not_bound(self):
        self.events.write_text('{"event":"match_settings","settings":{"mode":"human_vs_dayuan"}}\n')
        self.assertIsNone(self.model.poll()['token'])


if __name__ == '__main__':
    unittest.main()
