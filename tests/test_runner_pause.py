import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from undead.policy import Situation
import run_match

class PauseTests(unittest.TestCase):
    def test_long_pause_keeps_same_game_then_resumes_without_duplicate_bot_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'session.py').write_text('fixture')
            (root/'run_match.py').write_text('fixture')
            (root/'game_preferences.py').write_text('fixture')
            (root/'undead').mkdir()
            (root/'data').mkdir()
            (root/'data/camps.json').write_text('{"camps": []}')
            snapshots=iter([1,1,1,1,1,1,1,2,3])
            count=0;clock=0;wall=0;ticks=[];closed=[];pumped=[]
            def monotonic():
                nonlocal wall
                wall+=10
                return wall
            def snapshot(**kw):
                nonlocal count,clock
                clock=next(snapshots);count+=1
                return N(clock=clock,in_game=True,speed_pct=400,publish_count=count,me=0)
            g=N(snapshot=snapshot,events=lambda:pumped.append(clock),world=N(read=lambda:None),
                is_building=lambda u:False,clock=lambda:clock,my_units=lambda:[],resources=lambda:{},
                all_production=lambda *a:[],my_heroes=lambda:[],tech_many=lambda codes:{c:0 for c in codes})
            bot=N(tick=lambda:ticks.append(clock),situation=Situation(0),observe_events=lambda events:None)
            session=N(start=lambda:g,stop=lambda:closed.append(True))
            with patch.multiple(run_match,ROOT=root,Session=lambda *a:session,Controller=lambda *a:bot,
                                DebugConsole=lambda *a:N(speed=N(observe=lambda s:None),observe=lambda *a,**kw:None,close=lambda:None),Referee=lambda:N(observe=lambda *a:None)), \
                 patch.object(run_match.time,'monotonic',monotonic),patch.object(run_match.time,'sleep',lambda *a:None):
                result=run_match.run_match(max_game_seconds=3)
            events=[json.loads(x) for x in next((root/'artifacts').glob('*/events.jsonl')).read_text().splitlines()]
            saved=next((root/'artifacts').glob('*/source/data/camps.json'))
            self.assertEqual(json.loads(saved.read_text()),{'camps': []})
            self.assertEqual(result['reason'],'game_time_limit')
            self.assertEqual(ticks,[1,2])
            self.assertTrue(closed)
            self.assertGreater(len(pumped),len(ticks))
            resumed=next(e for e in events if e['event']=='clock_resumed')
            self.assertGreater(resumed['waited_wall_seconds'],60)

class FrozenTerminalTests(unittest.TestCase):
    def run_frozen(self,terminal=None,until=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('session.py','run_match.py','game_preferences.py'):
                (root/name).write_text('fixture')
            count=0;wall=0;clock=0;ticks=[];closed=[]
            def snapshot(**kw):
                nonlocal count,clock
                count+=1;clock=1 if count==1 else 1.5
                return N(clock=clock,in_game=True,speed_pct=400,publish_count=count,me=0)
            def raw():
                sides=[0,1] if count<3 or terminal is None else [0 if terminal=='win' else 1]
                return N(in_game=True,units=[N(alive=True,type='htow',owner=owner) for owner in sides])
            def sleep(seconds):
                nonlocal wall
                wall+=seconds
            g=N(snapshot=snapshot,events=lambda:None,world=N(read=raw),is_building=lambda u:True,
                clock=lambda:clock,my_units=lambda:[],resources=lambda:{},all_production=lambda *a:[],
                my_heroes=lambda:[],tech_many=lambda codes:{c:0 for c in codes})
            bot=N(tick=lambda:ticks.append(clock),situation=Situation(0),observe_events=lambda events:None)
            session=N(game=g,start=lambda **kw:g,stop=lambda:closed.append(True))
            with patch.multiple(run_match,ROOT=root,Session=lambda *a:session,Controller=lambda *a:bot,
                                DebugConsole=lambda *a:N(speed=N(observe=lambda s:None),observe=lambda *a,**kw:None,close=lambda:None)), \
                 patch.object(run_match.time,'monotonic',lambda:wall), \
                 patch.object(run_match.time,'time',lambda:wall), \
                 patch.object(run_match.time,'sleep',sleep):
                result=run_match.run_match(max_game_seconds=30,until=until)
            events=[json.loads(x) for x in next((root/'artifacts').glob('*/events.jsonl')).read_text().splitlines()]
            self.assertEqual(ticks,[1,1.5]) # no duplicate orders during engine/user pause
            self.assertTrue(closed)
            self.assertLess(wall,2)
            return result,events

    def test_final_building_loss_is_detected_when_clock_freezes_between_referee_ticks(self):
        for outcome in ('win','loss'):
            with self.subTest(outcome=outcome):
                result,events=self.run_frozen(terminal=outcome)
                self.assertEqual(result['result'],outcome)
                self.assertEqual(result['game_seconds'],1.5)
                self.assertIn('terminal_confirmed',[e['event'] for e in events])

    def test_user_pause_without_terminal_still_respects_absolute_cutoff(self):
        result,events=self.run_frozen(until=1)
        self.assertEqual((result['result'],result['reason']),('aborted','automation_deadline'))
        self.assertNotIn('terminal_confirmed',[e['event'] for e in events])

if __name__=='__main__':unittest.main()
