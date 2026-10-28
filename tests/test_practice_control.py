import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

import practice_control as control
import human_practice
import run_match
import undead.maps


class PracticeControlTests(unittest.TestCase):
    @contextlib.contextmanager
    def model(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=control.PracticeModel(Path(tmp))
            created={}
            launches=[]
            def process(pid=None):
                if pid not in created:raise control.psutil.NoSuchProcess(pid or 0)
                return N(create_time=lambda:created[pid])
            def spawn(command,**options):
                pid=700+len(launches)
                created[pid]=100+len(launches)
                launches.append((command,options))
                return N(pid=pid)
            with patch.object(control,'active_processes',return_value=[]), \
                 patch.object(control,'current_display',return_value=dict(width=2560,height=1440)), \
                 patch.object(control.psutil,'Process',side_effect=process), \
                 patch.object(control.subprocess,'Popen',side_effect=spawn), \
                 patch.object(human_practice,'source_files',return_value=[]), \
                 patch.object(undead.maps,'resolve_map',return_value=(None,None)):
                yield model,created,launches

    def test_selection_reaches_hidden_worker_and_survives_panel_reopening(self):
        for race,map_alias in ((1,'TR'),(2,'LR'),(3,'TM'),(4,'NI')):
            with self.subTest(race=race,map=map_alias),self.model() as (model,created,launches):
                state=model.start(map_alias,race)
                command,options=launches[0]
                self.assertEqual(command[command.index('--race')+1],str(race))
                self.assertEqual(command[command.index('--map')+1],map_alias)
                self.assertEqual(command[command.index('--run')+1],state['token'])
                self.assertEqual(options['creationflags'],control.subprocess.CREATE_NO_WINDOW)
                self.assertEqual(options['cwd'],model.root)
                reopened=control.PracticeModel(model.root)
                self.assertEqual(reopened.settings(),dict(map_alias=map_alias,human_race=race))
                current=reopened.poll()
                self.assertTrue(current['busy'])
                self.assertFalse(current['can_start'])
                self.assertEqual(current['phase'],'launching')

    def test_second_panel_cannot_start_while_first_worker_is_alive(self):
        with self.model() as (model,created,launches):
            original=model.start('LR',2)
            other=control.PracticeModel(model.root)
            with self.assertRaises(RuntimeError):other.start('TM',4)
            self.assertEqual(len(launches),1)
            self.assertEqual(control.read_json(model.state_path)['token'],original['token'])
            self.assertEqual(other.settings(),dict(map_alias='LR',human_race=2))

    def test_pending_registration_existing_game_and_launch_lock_block_all_spawns(self):
        with self.model() as (model,created,launches):
            control.atomic_json(model.state_path,dict(token='pending',phase='launching',launch_ready=False,
                                                      updated=control.time.time()))
            with self.assertRaises(RuntimeError):model.start('LR',2)
            self.assertEqual(launches,[])
            model.state_path.unlink()
            with patch.object(control,'active_processes',return_value=[dict(pid=42,name='War3.exe')]):
                with self.assertRaisesRegex(RuntimeError,'已有游戏'):model.start('LR',2)
            self.assertEqual(launches,[])
            with control.launch_lock(model.artifacts/'human-practice-launch.lock'):
                with self.assertRaisesRegex(RuntimeError,'另一个开局'):model.start('LR',2)
            self.assertEqual(launches,[])

    def test_spawn_failure_is_visible_keeps_selection_and_never_retries_implicitly(self):
        with self.model() as (model,created,launches):
            attempted=[]
            def fail(*args,**kwargs):
                attempted.append(args)
                raise OSError('launcher unavailable')
            with patch.object(control.subprocess,'Popen',side_effect=fail):
                with self.assertRaisesRegex(OSError,'launcher unavailable'):model.start('CH',4)
                first=model.poll();second=model.poll()
            self.assertEqual(len(attempted),1)
            self.assertEqual(first['phase'],'error')
            self.assertIn('launcher unavailable',first['error'])
            self.assertEqual(second['error'],first['error'])
            self.assertTrue(first['can_start'])
            self.assertEqual(model.settings(),dict(map_alias='CH',human_race=4))

    def test_exited_or_reused_worker_is_not_reported_running(self):
        with self.model() as (model,created,launches):
            state=model.start('LR',2)
            created[state['runner_pid']]+=1
            polled=model.poll()
            self.assertEqual(polled['phase'],'error')
            self.assertIn('已退出',polled['error'])
            self.assertTrue(polled['can_start'])


class PracticeWorkerTests(unittest.TestCase):
    @contextlib.contextmanager
    def worker(self,token='current'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=control.PracticeModel(root)
            control.atomic_json(model.state_path,dict(token=token,phase='launching',launch_ready=True,
                                                      settings=dict(human_race=2,map_alias='LR')))
            with patch.object(control,'ROOT',root),patch.object(control,'PracticeModel',return_value=model), \
                 patch.object(control,'active_processes',return_value=[]), \
                 patch.object(control.psutil,'Process',return_value=N(pid=801,create_time=lambda:50)):
                yield model

    def test_stale_worker_token_never_launches_or_changes_current_request(self):
        with self.worker() as model,patch.object(run_match,'run_match') as run:
            before=model.state_path.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'请求已变化'):control.run_worker('old',2,'LR')
            run.assert_not_called()
            self.assertEqual(model.state_path.read_bytes(),before)

    def test_worker_refuses_game_appearing_after_click_without_clearing_its_stop(self):
        with self.worker() as model,patch.object(run_match,'run_match') as run:
            stop=model.artifacts/'STOP';stop.write_text('existing match stop')
            with patch.object(control,'active_processes',return_value=[dict(pid=99,name='War3.exe')]):
                with self.assertRaisesRegex(RuntimeError,'已有游戏'):control.run_worker('current',2,'LR')
            run.assert_not_called()
            self.assertEqual(stop.read_text(),'existing match stop')
            self.assertEqual(control.read_json(model.state_path)['phase'],'error')

    def test_worker_runs_once_and_publishes_progress_and_final_result(self):
        with self.worker() as model:
            stop=model.artifacts/'STOP';stop.write_text('previous match stop')
            recorded=[]
            final=dict(result='aborted',reason='human_game_closed',id='sample')
            def game(**kwargs):
                recorded.append(kwargs)
                self.assertFalse(stop.exists())
                kwargs['practice_status']('running',clock=12,background=True)
                live=control.read_json(model.state_path)
                self.assertEqual((live['phase'],live['clock'],live['background']),('running',12,True))
                return final
            with patch.object(run_match,'run_match',side_effect=game):
                rc=control.run_worker('current',4,'TM')
            self.assertEqual(rc,0)
            self.assertEqual(len(recorded),1)
            self.assertEqual({k:v for k,v in recorded[0].items() if k!='practice_status'},
                             dict(speed=100,enemy_race=4,difficulty=2,map_alias='TM',human_practice=True))
            saved=control.read_json(model.state_path)
            self.assertEqual((saved['phase'],saved['result'],saved['background']),('finished',final,False))

    def test_old_running_callback_cannot_overwrite_another_request(self):
        with self.worker() as model:
            def game(**kwargs):
                control.atomic_json(model.state_path,dict(token='new',phase='launching',launch_ready=True))
                kwargs['practice_status']('running',clock=99)
                return dict(result='aborted',reason='human_game_closed')
            with patch.object(run_match,'run_match',side_effect=game):
                control.run_worker('current',2,'LR')
            self.assertEqual(control.read_json(model.state_path),dict(token='new',phase='launching',launch_ready=True))

    def test_token_replaced_during_preflight_cancels_old_worker_before_game(self):
        with self.worker() as model,patch.object(run_match,'run_match') as run:
            def another_request():
                control.atomic_json(model.state_path,dict(token='new',phase='launching',launch_ready=True))
                return []
            with patch.object(control,'active_processes',side_effect=another_request):
                with self.assertRaisesRegex(RuntimeError,'请求已变化'):control.run_worker('current',2,'LR')
            run.assert_not_called()
            self.assertEqual(control.read_json(model.state_path)['token'],'new')


if __name__=='__main__':unittest.main()
