import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import bot,run_match
from run_window import positive_minutes
from undead.policy import Situation

class MatchLimitTests(unittest.TestCase):
    def play(self,limit=None,stop=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('session.py','run_match.py','game_preferences.py'):
                (root/name).write_text('fixture')
            count=0;clock=0;wall=0;ticks=[];closed=[]
            def snapshot(**kw):
                nonlocal count,clock,wall
                clock=[1799,1801,3601,3603][count];count+=1;wall+=1100
                if stop and count==4:(root/'artifacts/STOP').write_text('requested')
                return N(clock=clock,in_game=True,speed_pct=400,publish_count=count,me=0)
            def raw():
                owners=[0,1] if count<4 else [0]
                return N(in_game=True,units=[N(alive=True,type='htow',owner=o) for o in owners])
            g=N(snapshot=snapshot,events=lambda:[],world=N(read=raw),clock=lambda:clock,
                my_units=lambda:[],resources=lambda:{},all_production=lambda *a:[],
                my_heroes=lambda:[],tech_many=lambda codes:{c:0 for c in codes})
            policy=N(tick=lambda:ticks.append(clock),situation=Situation(0),observe_events=lambda e:None)
            session=N(game=g,start=lambda:g,stop=lambda:closed.append(True))
            with patch.multiple(run_match,ROOT=root,Session=lambda *a:session,Controller=lambda *a:policy,
                    DebugConsole=lambda *a:N(speed=N(observe=lambda s:None),observe=lambda *a,**k:None,close=lambda:None)), \
                 patch.object(run_match.time,'monotonic',lambda:wall),patch.object(run_match.time,'sleep',lambda s:None):
                result=run_match.run_match(max_game_seconds=limit)
            saved=json.loads(next((root/'artifacts').glob('*/result.json')).read_text())
            self.assertEqual(saved,result);self.assertTrue(closed)
            return result,ticks

    def test_default_continues_past_old_game_and_wall_limits_until_real_terminal(self):
        result,ticks=self.play()
        self.assertEqual(ticks,[1799,1801,3601])
        self.assertEqual((result['result'],result['reason']),('win','all_enemy_buildings_destroyed'))
        self.assertEqual(result['game_seconds'],3603)
        self.assertGreater(result['wall_seconds'],2100)

    def test_explicit_limit_above_thirty_minutes_still_stops(self):
        result,ticks=self.play(limit=3600)
        self.assertEqual(ticks,[1799,1801])
        self.assertEqual((result['result'],result['reason']),('timeout','game_time_limit'))

    def test_stop_still_works_after_old_limits(self):
        result,ticks=self.play(stop=True)
        self.assertEqual(ticks,[1799,1801,3601])
        self.assertEqual((result['result'],result['reason']),('aborted','user_stop'))

    def test_cli_omits_limit_or_forwards_explicit_long_limit_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra,expected in [([],None),(['--minutes','90'],5400)]:
                with patch.object(bot,'ROOT',Path(tmp)),patch('sys.argv',['bot.py','play',*extra]), \
                     patch.object(run_match,'run_match',return_value={'result':'win'}) as play:
                    self.assertEqual(bot.main(),0)
                    self.assertEqual(play.call_args.args[1],expected)
        for value in ['0','-1','nan','inf','bad']:
            with self.subTest(value=value),self.assertRaises(ValueError):positive_minutes(value)
