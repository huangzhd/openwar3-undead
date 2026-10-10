import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import session
from bootstrap import ROOT


class CapturedLaunch(Exception):pass


class OpponentTests(unittest.TestCase):
    def test_requested_opponent_reaches_launcher_arguments(self):
        for race,difficulty in [(3,3),(4,3),(2,3),(1,2)]:
            with self.subTest(race=race),tempfile.TemporaryDirectory() as tmp:
                s=session.Session(400,race,difficulty);s.record=Path(tmp)/'session.json'
                captured=[]
                def launch(farm,n):
                    captured.extend(session.farm.launch_args('game.exe',n,farm.base(),1600,False,'30,30,1024,768'))
                    raise CapturedLaunch()
                with patch.object(session,'apply_defaults',return_value={}), \
                     patch.object(session.farm.w3paths,'inst_dir',return_value=tmp), \
                     patch.object(session.farm.Farm,'launch',autospec=True,side_effect=launch):
                    with self.assertRaises(CapturedLaunch):s.start()
                self.assertEqual(captured[captured.index('--enemy-race')+1],str(race))
                self.assertEqual(captured[captured.index('--difficulty')+1],str(difficulty))
                self.assertEqual((s.settings['enemyRace'],s.settings['difficulty']),(race,difficulty))

    def test_stale_next_game_override_cannot_start_wrong_opponent(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'next_game.json').write_text(json.dumps({'enemyRace':1,'difficulty':2}))
            s=session.Session(400,2,3);s.record=Path(tmp)/'session.json'
            with patch.object(session,'apply_defaults',return_value={}), \
                 patch.object(session.farm.w3paths,'inst_dir',return_value=tmp), \
                 patch.object(session.farm.Farm,'launch') as launch:
                with self.assertRaisesRegex(RuntimeError,'overrides'):s.start()
                launch.assert_not_called()

    def test_series_does_not_combine_human_and_orc_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i,race in enumerate([1,2,2]):
                out=Path(tmp,'artifacts',str(i));out.mkdir(parents=True)
                result=dict(id=str(i),version='fixture',result='win',opponent=dict(race=race,difficulty=3))
                (out/'result.json').write_text(json.dumps(result))
                (out/'source-manifest.json').write_text('{}')
                (out/'events.jsonl').write_text(json.dumps(dict(event='terminal_confirmed',result='win',clock=1)))
            subprocess.run([sys.executable,'-B',str(ROOT/'review_p1.py'),'fixture'],cwd=tmp,check=True,capture_output=True)
            series=json.loads(Path(tmp,'artifacts/p1-normal-series-fixture.json').read_text())
            self.assertEqual(series['valid_consecutive'],2)
            self.assertFalse(series['passed'])
