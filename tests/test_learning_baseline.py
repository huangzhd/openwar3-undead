import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from learning.baseline import inspect_run, inventory


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_folder(self, name, opponent='human-rifle', code='frozen', outcome='win'):
        folder = self.root / name
        (folder / 'source').mkdir(parents=True)
        (folder / 'source' / 'bot.py').write_text(code, encoding='utf-8')
        result = dict(id=name, mode='bot_vs_bot', result=outcome,
                      speed_history=[dict(clock=0,percent=100)],
                      reason='all_enemy_buildings_destroyed' if outcome=='win' else 'load failed',
                      opponent=dict(controller=opponent), launch_settings=dict(
                          mode='bot_vs_bot', fair=True, observer_player=0, controlled_player=1,
                          opponent_player=2, native_ai_paused=True, map_sha256='map-a'))
        (folder / 'result.json').write_text(json.dumps(result), encoding='utf-8')
        (folder / 'source-manifest.json').write_text(json.dumps({
            'bot.py': hashlib.sha256(code.encode()).hexdigest()}), encoding='utf-8')
        (folder/'source-audit.json').write_text(json.dumps(dict(files=1,mismatches=[],source_unchanged=True,
            session_closed=True,active_processes=[])),encoding='utf-8')
        (folder / 'events.jsonl').write_text(json.dumps(dict(event='terminal_confirmed',
            result=outcome, reason=result['reason']))+'\n', encoding='utf-8')
        return folder

    def test_runtime_error_and_tampered_source_never_qualify(self):
        failed = inspect_run(self.run_folder('failed', outcome='error'))
        self.assertEqual(failed['classification'], 'runtime_failure')
        self.assertFalse(failed['terminal_candidate'])
        folder = self.run_folder('tampered')
        (folder/'source'/'bot.py').write_text('changed', encoding='utf-8')
        checked = inspect_run(folder)
        self.assertIn('bot.py', checked['broken_sources'])
        self.assertFalse(checked['terminal_candidate'])

    def test_receipt_and_setup_required_and_never_auto_approve(self):
        folder = self.run_folder('complete')
        self.assertTrue(inspect_run(folder)['terminal_candidate'])
        self.assertFalse(inventory([folder])['training_actor_approved'])
        (folder/'events.jsonl').write_text('', encoding='utf-8')
        self.assertFalse(inspect_run(folder)['terminal_candidate'])
        result = json.loads((folder/'result.json').read_text())
        result['launch_settings']['fair'] = False
        (folder/'result.json').write_text(json.dumps(result), encoding='utf-8')
        self.assertIn('setup_verification_missing', inspect_run(folder)['issues'])

    def test_distinct_policy_revisions_cannot_complete_a_shared_baseline(self):
        rifle = self.run_folder('rifle')
        expansion = self.run_folder('expand', 'human-fast-expand', code='different')
        report = inventory([rifle, expansion])
        self.assertEqual(len(report['baselines']), 2)
        self.assertTrue(all(not row['both_opponents_recorded'] for row in report['baselines']))
        same = self.run_folder('same', 'human-fast-expand')
        self.assertTrue(inventory([rifle, same])['baselines'][0]['both_opponents_recorded'])

    def test_kfai_requires_native_ai_isolation_and_retains_unverified_fairness(self):
        folder=self.run_folder('kfai','kfai-human')
        self.assertIn('setup_verification_missing',inspect_run(folder)['issues'])
        result=json.loads((folder/'result.json').read_text())
        result['launch_settings'].update(native_ai_paused=False,native_ai_paused_players=[1],
            opponent_fairness='native_KFAI_unverified',active_player_slots=[0,1,2],
            verified_players=[dict(slot=1,controller=1,race=3),dict(slot=2,controller=1,race=1)])
        (folder/'result.json').write_text(json.dumps(result),encoding='utf-8')
        row=inspect_run(folder)
        self.assertTrue(row['terminal_candidate'])
        self.assertEqual(row['opponent_fairness'],'native_KFAI_unverified')
        self.assertFalse(inventory([folder])['training_actor_approved'])
        result['launch_settings']['native_ai_paused_players']=[1,2]
        (folder/'result.json').write_text(json.dumps(result),encoding='utf-8')
        self.assertFalse(inspect_run(folder)['terminal_candidate'])

    def test_speed_changes_and_missing_cleanup_do_not_complete_baseline(self):
        a=self.run_folder('one','human-rifle');b=self.run_folder('four','human-fast-expand')
        result=json.loads((b/'result.json').read_text())
        result['speed_history']=[dict(clock=0,percent=400)]
        (b/'result.json').write_text(json.dumps(result),encoding='utf-8')
        self.assertEqual(len(inventory([a,b])['baselines']),2)
        result['speed_history'] += [dict(clock=30,percent=100)]
        (b/'result.json').write_text(json.dumps(result),encoding='utf-8')
        self.assertTrue(inspect_run(b)['speed_condition'].startswith('variable:'))
        (a/'source-audit.json').unlink()
        self.assertFalse(inspect_run(a)['terminal_candidate'])
        result['speed_history']=[]
        (b/'result.json').write_text(json.dumps(result),encoding='utf-8')
        self.assertFalse(inspect_run(b)['terminal_candidate'])
