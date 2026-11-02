import copy
import json
import tempfile
import unittest
import contextlib
import io
from dataclasses import replace, make_dataclass
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

import bootstrap
import w3fast
import w3world
from learning.trajectory import BoundaryError, ObservationBoundary, PointVisibility, TrajectoryRecorder


def unit(owner, ident, visible=(), **overrides):
    u = w3world.Unit(index=ident, addr=ident+100000, handle_lo=ident, handle_hi=7,
                    type='uaco' if owner == 1 else 'hpea', owner=owner, flags=w3world.ALIVE,
                    x=100.0, y=200.0, hp=200.0, hp_max=200.0, mana=0.0, mana_max=0.0,
                    order=1234, order_target=(999, 7), order_x=9999, order_y=9999,
                    task_target=(999, 7), task_x=9999, task_y=9999, level=0, xp=999,
                    skill_points=99, first_seen=123456, visible_mask=sum(1 << p for p in visible))
    for key, value in overrides.items():setattr(u, key, value)
    return u


def fixture():
    own, seen, hidden = unit(1, 11), unit(2, 22, (0, 1, 2)), unit(2, 33, (0, 2))
    raw = w3world.WorldState(1, 0, 10., 1, 0, True, 400, 50, 0, 0, 0,
                            [w3world.Player(i, 100+i, 40+i, 5, 12, 10, 20, 3, True) for i in range(3)],
                            [own, seen, hidden], [], by_handle={u.handle: u for u in (own, seen, hidden)})
    raw.production = [w3world.Production(u.handle, 'queue', ['uaco' if u.owner == 1 else 'hgry'],
                                         20, 10, 1, False, True) for u in raw.units]
    raw.opponent_strategy = 'DO_NOT_SERIALIZE'
    lane = N(commands=Mock(side_effect=lambda calls, *a, **kw:
                           [w3fast.Receipt(c.op, 0, 1, None, 0, 0, (0,)*8) for c in calls]))
    game = N(pid=101, player=1, fair=True, world=N(read=Mock(return_value=raw)),
             _w3fast=w3fast, lane=lane, visible=Mock(return_value=True))
    return game, raw


class ObservationTests(unittest.TestCase):
    def test_whitelist_excludes_addresses_orders_masks_enemy_resources_and_production(self):
        game, raw = fixture()
        frame = ObservationBoundary(101, 1).project(game, raw)
        self.assertEqual(frame['resources']['gold'], 101)
        self.assertEqual([u['handle'] for u in frame['units']], [[11, 7], [22, 7]])
        self.assertEqual([p['building'] for p in frame['production']], [[11, 7]])
        forbidden = ('addr', 'visible_mask', 'first_seen', 'order_target', 'task_target', 'opponent_strategy', 'players')
        encoded = json.dumps(frame)
        for key in forbidden:self.assertNotIn(key, encoded)
        self.assertNotIn('inventory', frame['units'][1])

    def test_hidden_world_perturbations_produce_identical_observations(self):
        game, raw = fixture()
        expected = ObservationBoundary(101, 1).project(game, raw)
        for seed in range(30):
            with self.subTest(seed=seed):
                changed = copy.deepcopy(raw)
                changed.players[0].gold = changed.players[2].gold = 10000+seed
                hidden = changed.units[2]
                hidden.x, hidden.hp, hidden.flags = seed*200, seed, 0 if seed % 2 else w3world.ALIVE
                hidden.abilities = [N(code='A000', level=seed, cooldown=seed)]
                changed.production[1].queue = changed.production[2].queue = ['hgry'] * seed
                changed.opponent_strategy = seed
                changed.items = [N(type='stwp', x=seed, y=seed, addr=seed)]
                changed.selection_addrs = [hidden.addr]
                self.assertEqual(expected, ObservationBoundary(101, 1).project(game, changed))

    def test_hidden_death_disappearance_and_sdk_memory_cannot_erase_last_seen(self):
        game, raw = fixture();boundary = ObservationBoundary(101, 1)
        first = boundary.project(game, raw)
        raw.clock += 1;raw.publish_count += 1
        seen = raw.units[1];seen.visible_mask = 1;seen.flags = 0;seen.hp = 0;seen.x = 99999
        game._last_seen = {}  # SDK clears this on raw hidden deaths; boundary never reads it.
        next_frame = boundary.project(game, raw)
        self.assertEqual(first['last_seen'], next_frame['last_seen'])
        raw.clock += 1;raw.publish_count += 1;raw.units.remove(seen)
        self.assertEqual(first['last_seen'], boundary.project(game, raw)['last_seen'])

    def test_visible_death_is_observation_and_output_cannot_mutate_memory(self):
        game, raw = fixture();boundary = ObservationBoundary(101, 1)
        first = boundary.project(game, raw)
        first['last_seen'][0]['unit']['hp'] = -999
        raw.clock += 1;raw.publish_count += 1
        raw.units[1].flags = 0;raw.units[1].hp = 0
        frame = boundary.project(game, raw)
        self.assertFalse(frame['last_seen'][0]['unit']['alive'])
        self.assertEqual(frame['last_seen'][0]['unit']['hp'], 0)

    def test_unknown_values_remain_unknown_not_zero(self):
        game, raw = fixture();raw.players[1].known = False;raw.units[0].mana = float('nan')
        frame = ObservationBoundary(101, 1).project(game, raw)
        self.assertIsNone(frame['resources'])
        self.assertIsNone(frame['units'][0]['mana'])
        self.assertIsNone(frame['units'][0]['inventory'])
        self.assertIsNone(frame['units'][0]['abilities'])

    def test_pause_stale_clock_publication_and_cross_binding_are_rejected(self):
        for mutation in (lambda g,r:setattr(g,'pid',102), lambda g,r:setattr(g,'player',0),
                         lambda g,r:setattr(g,'fair',False), lambda g,r:setattr(r,'epoch',2),
                         lambda g,r:setattr(r,'me',1), lambda g,r:setattr(r,'clock',9),
                         lambda g,r:setattr(r,'publish_count',0),lambda g,r:setattr(r,'in_game',False)):
            game, raw = fixture();boundary = ObservationBoundary(101, 1)
            boundary.project(game, raw)
            self.assertIsNone(boundary.project(game, raw))
            mutation(game, raw)
            with self.assertRaises(BoundaryError):boundary.project(game, raw)


class VisibilityTests(unittest.TestCase):
    def oracle(self):
        _, raw = fixture()
        client = N(pid=101,world=N(read=Mock(return_value=raw)),close=Mock(),
                   jass=N(Player=Mock(side_effect=lambda p:100+p),
                          IsVisibleToPlayer=Mock(side_effect=lambda x,y,p:p == 100)))
        return PointVisibility(client, 101, 1), client, raw

    def test_observer_visible_does_not_mean_p1_visible(self):
        oracle, client, _ = self.oracle()
        self.assertTrue(client.jass.IsVisibleToPlayer(100, 200, 100))
        self.assertFalse(oracle.query(100, 200)['visible'])
        client.jass.Player.assert_called_once_with(1)
        client.jass.IsVisibleToPlayer.assert_called_with(100., 200., 101)

    def test_errors_unknown_and_epoch_change_never_fall_back(self):
        oracle, client, raw = self.oracle()
        client.jass.IsVisibleToPlayer.side_effect = RuntimeError('private diagnostic')
        self.assertIsNone(oracle.query(1, 2)['visible'])
        client.jass.IsVisibleToPlayer.side_effect = lambda *a:setattr(raw, 'epoch', 2) or True
        self.assertIsNone(oracle.query(1, 2)['visible'])
        oracle.close();client.close.assert_called_once()


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'trajectory.jsonl'
        self.game, self.raw = fixture()

    def rows(self):
        return [json.loads(s) for s in self.path.read_text(encoding='utf-8').splitlines()]

    def test_separates_request_acceptance_and_subsequent_observation(self):
        original = self.game.lane.commands
        recorder = TrajectoryRecorder(self.game, self.path)
        call = w3fast.command('target',self.raw.units[0],code=851983,target=self.raw.units[1])
        self.game.lane.commands([call])
        self.raw.clock += 1;self.raw.publish_count += 1;self.raw.units[1].hp -= 10
        recorder.observe();recorder.finish('timeout','game_time_limit')
        rows = self.rows()
        self.assertEqual([r['event'] for r in rows], ['header','observation','action_request','action_receipt','observation','terminal'])
        self.assertTrue(rows[2]['eligible']);self.assertTrue(rows[3]['accepted'])
        self.assertEqual(rows[3]['effect'],'unverified')
        self.assertEqual(rows[4]['observation']['units'][1]['hp'],190)
        self.assertTrue(rows[-1]['truncated']);self.assertIsNone(rows[-1]['reward'])
        self.assertIs(self.game.lane.commands, original)
        original.assert_called_once_with([call])
        self.assertNotIn(str(self.raw.units[0].addr),json.dumps(rows))

    def test_hidden_or_stale_target_and_unowned_sources_have_no_serialized_payload(self):
        recorder = TrajectoryRecorder(self.game,self.path)
        mine, seen, hidden = self.raw.units
        calls = [w3fast.command('target',mine,code=851983,target=hidden),
                 w3fast.command('point',hidden,code=851986,x=9999,y=9999),
                 w3fast.command('target',mine,code=851983,target=seen)]
        seen.visible_mask = 1  # vanished since observation, still present in raw table
        self.game.lane.commands(calls)
        recorder.finish('aborted','user_stop')
        requests = [r for r in self.rows() if r['event']=='action_request']
        self.assertEqual(len(requests),3)
        self.assertTrue(all(r['action'] is None and r['eligible'] is False for r in requests))
        # Passive observer: recording exclusions never secretly replace existing rule commands.
        recorder.original.assert_called_once_with(calls)

    def test_queries_camera_and_strategy_jass_are_not_commands_or_receipts_in_dataset(self):
        recorder = TrajectoryRecorder(self.game,self.path)
        calls = [w3fast.command(op) for op in ('q_tech','q_visible','cam_field','jass')]
        self.game.lane.commands(calls);recorder.finish('aborted','user_stop')
        self.assertEqual([r['event'] for r in self.rows()],['header','observation','terminal'])

    def test_transport_failure_is_unknown_and_private_error_is_redacted(self):
        self.game.lane.commands.side_effect = RuntimeError('opponent private resources=99999')
        recorder = TrajectoryRecorder(self.game,self.path)
        with self.assertRaises(RuntimeError):
            self.game.lane.commands([w3fast.command('immediate',self.raw.units[0],code=851972)])
        recorder.finish('error','opponent private resources=99999')
        self.assertIsNone(self.rows()[-2]['accepted'])
        self.assertNotIn('99999',self.path.read_text(encoding='utf-8'))

    def test_cutoff_after_request_records_unknown_receipt_then_propagates(self):
        from run_guard import RunInterrupted
        self.game.lane.commands.side_effect = RunInterrupted('stage_time_limit',10)
        recorder = TrajectoryRecorder(self.game,self.path)
        with self.assertRaises(RunInterrupted):
            self.game.lane.commands([w3fast.command('immediate',self.raw.units[0])])
        recorder.finish('timeout','stage_time_limit')
        self.assertIsNone(self.rows()[-2]['accepted'])
        self.assertEqual(self.rows()[-2]['status'],'interrupted')
        self.assertIsNone(self.rows()[-1]['reward'])

    def test_rejected_and_missing_receipts_never_become_success(self):
        self.game.lane.commands.side_effect = lambda calls:[w3fast.Receipt(calls[0].op,1,0,None,0,0,(0,)*8)]
        recorder = TrajectoryRecorder(self.game,self.path)
        call = w3fast.command('immediate',self.raw.units[0])
        self.game.lane.commands([call,call]);recorder.finish('timeout','game_time_limit')
        receipts = [r for r in self.rows() if r['event']=='action_receipt']
        self.assertFalse(receipts[0]['accepted'])
        self.assertIsNone(receipts[1]['accepted'])

    def test_native_timeout_is_unknown_not_a_confirmed_rejection(self):
        self.game.lane.commands.side_effect=lambda calls:[w3fast.Receipt.timeout(calls[0].op)]
        recorder=TrajectoryRecorder(self.game,self.path)
        self.game.lane.commands([w3fast.command('immediate',self.raw.units[0],code=851972)])
        recorder.finish('timeout','game_time_limit')
        receipt=next(r for r in self.rows() if r['event']=='action_receipt')
        self.assertIsNone(receipt['accepted']);self.assertEqual(receipt['status'],99)

    def test_terminal_requires_natural_referee_confirmation(self):
        for index,(outcome,reason,confirmed,reward) in enumerate([
                ('win','all_enemy_buildings_destroyed',True,1),
                ('loss','all_own_buildings_destroyed',True,-1),
                ('win','all_enemy_buildings_destroyed',False,None),
                ('loss','manual_surrender',True,None),
                ('error','failed',True,None)]):
            path = self.path.with_name(str(index)+'.jsonl')
            recorder = TrajectoryRecorder(self.game,path)
            recorder.finish(outcome,reason,natural_confirmed=confirmed)
            terminal = json.loads(path.read_text().splitlines()[-1])
            self.assertEqual(terminal['reward'],reward)
            self.assertEqual(terminal['terminated'],reward is not None)

    def test_terminal_classifies_health_failure_separately_from_cutoff_and_exit(self):
        for index, (outcome, reason, category) in enumerate((
                ('timeout', 'stage_time_limit', 'runtime_failure'),
                ('timeout', 'game_time_limit', 'time_limit'),
                ('aborted', 'human_game_closed', 'process_exit'),
                ('aborted', 'practice_match_changed', 'epoch_changed'),
                ('loss', 'manual_surrender', 'user_abort'),
                ('error', 'exception with private diagnostic', 'runtime_failure'))):
            path = self.path.with_name('category-'+str(index)+'.jsonl')
            recorder = TrajectoryRecorder(self.game, path)
            recorder.finish(outcome, reason, natural_confirmed=True)
            terminal = json.loads(path.read_text().splitlines()[-1])
            self.assertEqual(terminal['classification'], category)
            self.assertTrue(terminal['truncated'])
            self.assertIsNone(terminal['reward'])
            self.assertNotIn('private diagnostic', json.dumps(terminal))

    def test_cross_epoch_stops_before_submitting_action_and_never_overwrites_file(self):
        original = self.game.lane.commands
        recorder = TrajectoryRecorder(self.game,self.path)
        self.raw.epoch = 2
        with self.assertRaises(BoundaryError):
            self.game.lane.commands([w3fast.command('immediate',self.raw.units[0])])
        original.assert_not_called();recorder.finish('aborted','practice_match_changed')
        with self.assertRaises(FileExistsError):TrajectoryRecorder(self.game,self.path)

    def test_new_p1_visibility_rows_do_not_use_rule_bot_visible(self):
        client = N(pid=101,world=self.game.world,close=Mock(),
                   jass=N(Player=lambda p:p+100,IsVisibleToPlayer=lambda x,y,p:p==100))
        oracle = PointVisibility(client,101,1)
        recorder = TrajectoryRecorder(self.game,self.path,visibility=oracle,public_points=[(1,2)])
        recorder.observe_points();recorder.observe_points()
        recorder.finish('timeout','game_time_limit')
        points = [r for r in self.rows() if r['event']=='point_visibility']
        self.assertEqual(len(points),1);self.assertFalse(points[0]['points'][0]['visible'])
        self.game.visible.assert_not_called()


class EntryTests(unittest.TestCase):
    def test_runner_freezes_recorder_records_actions_and_cleans_up_without_game(self):
        self.run_guarded_fixture()

    def test_stage_cutoff_runs_normal_cleanup_and_truncates_dataset(self):
        self.run_guarded_fixture(stage_cutoff=True)

    def test_environment_ready_precedes_orders_and_each_step_returns_safe_receipts(self):
        self.run_guarded_fixture(step_mode=True)

    def test_environment_close_before_first_tick_cleans_up_without_orders(self):
        self.run_guarded_fixture(step_mode=True,close_ready=True)

    def test_environment_resume_rechecks_epoch_before_orders(self):
        self.run_guarded_fixture(step_mode=True,change_epoch=True)

    def test_environment_idle_deadline_rechecked_before_orders(self):
        self.run_guarded_fixture(step_mode=True,expire=True)

    def test_environment_process_exit_precedes_guard_reads_and_keeps_cached_terminal(self):
        self.run_guarded_fixture(step_mode=True,process_exit=True)

    def test_primitive_runner_dispatches_external_action_without_rule_controller(self):
        self.run_guarded_fixture(step_mode=True,primitives=True)

    def test_primitive_close_before_first_action_never_sends_rule_or_native_command(self):
        self.run_guarded_fixture(step_mode=True,primitives=True,close_ready=True)

    def test_primitive_epoch_change_never_reaches_executor(self):
        self.run_guarded_fixture(step_mode=True,primitives=True,change_epoch=True)

    def test_primitive_process_exit_never_reads_stale_mapping_or_executes(self):
        self.run_guarded_fixture(step_mode=True,primitives=True,process_exit=True)

    def test_primitive_deadline_precedes_commands(self):
        self.run_guarded_fixture(step_mode=True,primitives=True,expire=True)

    def test_primitive_final_log_failure_cannot_skip_game_cleanup(self):
        self.run_guarded_fixture(step_mode=True,primitives=True,close_ready=True,log_failure=True)

    def run_guarded_fixture(self,stage_cutoff=False,step_mode=False,close_ready=False,change_epoch=False,expire=False,process_exit=False,primitives=False,log_failure=False):
        import run_match
        import run_guard
        import sparring
        import undead.game_view
        game, raw = fixture()
        live=[True]
        original_read=game.world.read
        def checked_read():
            if not live[0]:raise AssertionError('Read stale mapping after process exit')
            return original_read()
        game.world.read=checked_read
        game.snapshot = lambda **kw:replace(raw, me=1)
        game.clock = lambda:raw.clock
        game.events = lambda:[]
        game.resources = lambda:dict(gold=101,lumber=41)
        game.my_units = lambda:[raw.units[0]]
        game.my_heroes = lambda:[]
        game.tech_many = lambda codes:{}
        game.all_production = lambda owner:[]
        game.map = lambda:N(bounds=(-1000,1000,-1000,1000))
        if primitives:
            raw.units[0].has_detail=True
            raw.units[0].items=[None]*6
            raw.units[0].abilities=[N(code='Amov',level=1,cooldown=0)]
            def move(unit,x,y):
                receipt=game.lane.commands([w3fast.command('point',unit,851986,x=x,y=y)])[0]
                raw.clock+=1;raw.publish_count+=1
                return receipt
            game.move=move
        client = N(pid=101, world=game.world, lane=N(), close=Mock(),
                   jass=N(Player=lambda p:100+p, IsVisibleToPlayer=lambda *args:False))
        session = N(game=game, settings={}, start=lambda **kw:game, alive=lambda:live[0], active=lambda:True,
                    start_opponent=Mock(), tick_opponent=lambda epoch:True, stop=Mock(),
                    map_catalog=dict(camps=[],critters=[],neutral_buildings=[],name='fixture',map_sha256='a',
                                     starts=[dict(x=100,y=200,slot=2)]))
        controller = Mock(situation=make_dataclass('EmptySituation',[])())
        timing = [0.]
        def tick():
            game.lane.commands([w3fast.command('immediate',raw.units[0],code=851972)])
            if stage_cutoff:
                timing[0] = 3.
                game.world.read()
            raw.clock += 1;raw.publish_count += 1
        controller.tick.side_effect = tick
        original = game.lane.commands
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('session.py','run_match.py','run_guard.py','game_preferences.py','learning/trajectory.py'):
                path = root/name;path.parent.mkdir(exist_ok=True);path.write_text('fixture')
            with patch.object(run_match,'ROOT',root), \
                 patch.object(run_match,'Controller',return_value=controller) as factory, \
                 patch.object(run_match,'Referee',return_value=N(observe=lambda *args:None)), \
                 patch.object(sparring,'SparringSession',return_value=session), \
                 patch.object(sparring,'source_files',return_value=[]), \
                 patch.object(undead.game_view,'Game',return_value=client), \
                 patch.object(run_guard.time,'perf_counter',lambda:timing[0]), \
                 patch.object(run_match.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):
                if step_mode:
                    runner=run_match._match_steps(sparring='kfai-human',trajectory=True,max_game_seconds=13,
                                                 until=run_match.time.time()+60 if expire else None,step_mode=True,
                                                 control='primitives' if primitives else 'rule')
                    from learning.actions import SCHEMA
                    command=dict(schema=SCHEMA,op='move',unit=[11,7],x=20,y=30) if primitives else 'rule_tick'
                    ready=next(runner)
                    original.assert_not_called()
                    self.assertEqual(ready['observation']['resources']['gold'],101)
                    self.assertEqual(ready['receipts'],[])
                    self.assertNotIn('players',ready['observation'])
                    if close_ready:
                        failing=patch('learning.actions.PrimitiveExecutor.observe',side_effect=OSError('disk failure')) if log_failure else contextlib.nullcontext()
                        with failing, self.assertRaises(StopIteration) as stopped:
                            runner.throw(run_guard.RunInterrupted('environment_close',raw.clock))
                    elif change_epoch:
                        raw.epoch=2
                        with self.assertRaises(StopIteration) as stopped:runner.send(command)
                    elif expire:
                        future=run_match.time.time()+120
                        with patch.object(run_match.time,'time',return_value=future):
                            with self.assertRaises(StopIteration) as stopped:runner.send(command)
                    elif process_exit:
                        live[0]=False
                        with self.assertRaises(StopIteration) as stopped:runner.send(command)
                    else:
                        step=runner.send(command)
                        self.assertEqual(step['event'],'step')
                        self.assertGreater(step['observation']['clock'],ready['observation']['clock'])
                        self.assertTrue(step['receipts'][0]['accepted'])
                        self.assertNotIn('args',step['receipts'][0])
                        if primitives:
                            self.assertTrue(step['action_receipts'][0]['accepted'])
                            self.assertEqual(step['action_receipts'][0]['native_request_ids'],[1])
                        runner.send(command)
                        with self.assertRaises(StopIteration) as stopped:runner.send(command)
                    result=stopped.exception.value
                    if close_ready or change_epoch or expire or process_exit:original.assert_not_called()
                    if log_failure:
                        self.assertIn('environment_frame_cleanup_error',result)
                        self.assertIn('primitive_cleanup_error',result)
                    else:self.assertIn('environment_final_frame',result)
                    if process_exit:
                        self.assertEqual(result['termination']['classification'],'process_exit')
                        self.assertEqual(result['game_seconds'],ready['observation']['clock'])
                        self.assertEqual(result['environment_final_frame']['observation'],ready['observation'])
                else:
                    result = run_match.run_match(sparring='kfai-human',trajectory=True,max_game_seconds=11)
            expected=('human_game_closed' if process_exit else 'environment_close' if close_ready else 'game_epoch_changed' if change_epoch else
                      'automation_deadline' if expire else 'stage_time_limit' if stage_cutoff else 'game_time_limit')
            self.assertEqual(result['reason'],expected)
            folder = root/'artifacts'/result['id']
            rows = [json.loads(s) for s in (folder/'trajectory.jsonl').read_text().splitlines()]
            if primitives:
                factory.assert_not_called();controller.tick.assert_not_called();controller.observe_events.assert_not_called()
                self.assertEqual(result['policy'],'external_primitives')
                self.assertEqual(rows[0]['policy'],'external_primitives')
                contract=json.loads((folder/'interface-contract.json').read_text())
                self.assertEqual(contract['action_version'],SCHEMA)
                self.assertEqual(contract['policy'],'external_primitives')
                external=[json.loads(s) for s in (folder/'primitive-actions.jsonl').read_text().splitlines()]
                if not(close_ready or change_epoch or expire or process_exit):
                    self.assertEqual(external[1]['action'],command)
                    self.assertTrue(any(r['event']=='next_observation' and r['observation_id'] is not None for r in external))
                else:self.assertEqual(len(external),1)
            self.assertEqual(any(r['event']=='action_request' for r in rows),not(close_ready or change_epoch or expire or process_exit))
            self.assertTrue(rows[-1]['truncated'])
            self.assertIn('learning/trajectory.py',json.loads((folder/'source-manifest.json').read_text()))
            self.assertIn('run_guard.py',json.loads((folder/'source-manifest.json').read_text()))
            timing_rows=[json.loads(s) for s in (folder/'runtime-timing.jsonl').read_text().splitlines()]
            self.assertEqual(timing_rows[-1]['event'],'guard_closed')
        self.assertIs(game.lane.commands,original)
        client.close.assert_called_once();session.stop.assert_called_once()

    def test_flag_is_opt_in_and_forwarded_without_starting_a_game_in_test(self):
        import bot
        import run_match
        with tempfile.TemporaryDirectory() as temp, patch.object(bot,'ROOT',Path(temp)):
            for flag in ([],['--trajectory']):
                with patch('sys.argv',['bot.py','sparring','--opponent','kfai-human',*flag]), \
                     patch.object(run_match,'run_match',return_value={'result':'timeout'}) as run:
                    self.assertEqual(bot.main(),0)
                    self.assertEqual(run.call_args.kwargs['trajectory'],bool(flag))

    def test_recorder_cannot_be_enabled_in_normal_or_human_game(self):
        from run_match import run_match
        with self.assertRaises(ValueError):run_match(trajectory=True)


if __name__ == '__main__':unittest.main()
