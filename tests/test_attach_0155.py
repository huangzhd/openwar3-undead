import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import attach_match as a


class FakeGame:
    def __init__(self):
        self.u=N(type='uaco',owner=4,alive=True,addr=10)
        self.s=N(in_game=True,clock=100.,me=4,epoch=7,speed_pct=100,publish_count=1,units=[self.u])
        self.raw=N(in_game=True,me=4,epoch=7)
        self.world=N(read=lambda:self.raw)
        self.released=[];self.claims=N(give_back=self.released.append)
        self.evs=[];self.closed=False
    def snapshot(self,**kw):return self.s
    def my_units(self):return [self.u]
    def events(self):return self.evs
    def close(self):self.closed=True
    # No launch/end/speed/kill API exists in this double: accidental use fails.


class AttachmentTests(unittest.TestCase):
    def setup(self):
        g=FakeGame();bots=[];logs=[]
        def factory(*args):
            b=N(ticks=0,intent='test',observe_events=lambda events:None)
            def tick():b.ticks+=1
            b.tick=tick;bots.append(b);return b
        loop=a.Attachment(g,dict(player=4,epoch=7,clock=100),3,lambda *args,**kw:logs.append((args,kw)),factory)
        return g,loop,bots,logs

    def test_initial_pause_no_orders_resume_and_handoff_rebuilds_controller(self):
        g,b,bots,_=self.setup()
        b.step('pause',0);self.assertFalse(bots)
        b.step('resume',1);self.assertEqual(bots[0].ticks,1)
        g.s.clock+=1;g.s.publish_count+=1;b.step('pause',2)
        self.assertTrue(b.paused);self.assertEqual(g.released,[10]);self.assertEqual(bots[0].ticks,1)
        b.step('resume',3);self.assertEqual(len(bots),2);self.assertEqual(bots[1].ticks,1)

    def test_game_pause_skips_duplicate_orders(self):
        g,b,bots,_=self.setup();b.step('resume',0)
        for t in range(1,5):g.s.publish_count+=1;b.step('resume',t)
        self.assertEqual(bots[0].ticks,1)
        g.s.clock+=1;b.step('resume',5);self.assertEqual(bots[0].ticks,2)

    def test_hero_history_survives_pause_even_if_hero_dies_under_manual_control(self):
        g,b,bots,_=self.setup()
        factory=b.factory
        def with_economy(*args):
            bot=factory(*args);bot.economy=N(ever_heroes=set());return bot
        b.factory=with_economy;b.step('resume',0)
        bots[0].economy.ever_heroes.add('Ulic');b.step('pause',1)
        b.step('resume',2)
        self.assertIn('Ulic',bots[1].economy.ever_heroes)

    def test_game_epoch_local_player_exit_and_speed_changes_release_without_tick(self):
        for change in ('epoch','player','ended','speed','clock'):
            g,b,bots,_=self.setup();b.step('resume',0)
            if change=='epoch':g.raw.epoch+=1
            elif change=='player':g.raw.me=1
            elif change=='ended':g.raw.in_game=False
            elif change=='speed':g.s.speed_pct=400
            else:g.s.clock=1
            self.assertIsNotNone(b.step('resume',1),change)
            self.assertEqual(bots[0].ticks,1)

    def test_stale_publication_stops_even_when_game_clock_is_paused(self):
        g,b,_,_=self.setup();b.step('pause',0)
        with self.assertRaisesRegex(RuntimeError,'停止更新'):b.step('resume',11)

    def test_release_does_not_need_live_snapshot(self):
        g,b,bots,_=self.setup();g.raw=None
        self.assertEqual(b.step('release',0),'released_by_user');self.assertFalse(bots)

    def test_only_local_departure_or_game_end_exits(self):
        g,b,bots,_=self.setup();g.evs=[N(kind='player.left',player=1)]
        self.assertIsNone(b.step('resume',0))
        g.evs=[N(kind='player.left',player=4)]
        self.assertEqual(b.step('resume',1),'game_or_local_player_left')

    def test_wrong_race_observer_lobby_and_speed_are_rejected(self):
        for reason in ('race','observer','lobby','speed'):
            g=FakeGame()
            if reason=='race':g.u.type='hpea'
            elif reason=='observer':g.s.me=15
            elif reason=='lobby':g.s.in_game=False
            else:g.s.speed_pct=400
            with self.assertRaises(RuntimeError,msg=reason):a.validate_snapshot(g.s)

    def test_live_map_does_not_inherit_launchers_default_catalog(self):
        b=N(creeping=N(catalog=[1]),critter_search=N(spawns=[1]),economy=N(ever_heroes=set()),tavern_seen=set(),third_hero='Nbrn')
        g=N(my_heroes=lambda:[N(type='Nbrn',handle=(5,6))])
        with patch('undead.controller.Controller',return_value=b):a.make_controller(g,lambda *a:None,3)
        self.assertEqual(b.creeping.catalog,[]);self.assertEqual(b.critter_search.spawns,[])
        self.assertEqual(b.economy.ever_heroes,{'Nbrn'});self.assertEqual(b.tavern_seen,{(5,6)})


class LifecycleTests(unittest.TestCase):
    def test_missing_bridge_has_specific_diagnostic_and_does_not_create_client(self):
        import w3world
        row=dict(pid=123,created=1,name='war3.exe',exe='C:/Game/war3.exe')
        with patch.object(a,'identity',return_value=row),patch.object(a,'compatible_dll',return_value=True),patch.object(a,'still_same',return_value=True),patch('bridge_diagnostics.mapping_access',return_value={'winerror':2}),patch.object(w3world,'World',side_effect=w3world.WorldUnavailable('absent')):
            r=a.probe(123)
        self.assertFalse(r['ready']);self.assertFalse(r['bridge'])
        self.assertEqual(r['bridge_state'],'mapping_absent')
        self.assertEqual(r['diagnostic']['sdk_detail'],'absent')

    def test_probe_rejects_changed_pid_and_closes_world(self):
        import w3world
        g=FakeGame();closed=[];world=N(read=lambda:g.s,map=lambda:N(starts=[(-1,1),(1,1)]),close=lambda:closed.append(True))
        with patch.object(a,'identity',return_value={}),patch.object(a,'compatible_dll',return_value=True),patch.object(a,'still_same',return_value=False),patch.object(w3world,'World',return_value=world):
            r=a.probe(123)
        self.assertFalse(r['ready']);self.assertEqual(closed,[True])

    def test_unavailable_interface_after_process_exit_is_not_missing_runtime(self):
        import w3world
        with patch.object(a,'identity',return_value={}),patch.object(a,'compatible_dll',return_value=True),patch.object(a,'still_same',return_value=False),patch('bridge_diagnostics.mapping_access',return_value={'winerror':2}),patch.object(w3world,'World',side_effect=w3world.WorldUnavailable('absent')):
            r=a.probe(123)
        self.assertFalse(r['ready'])
        self.assertEqual(r['bridge_state'],'process_changed')

    def test_runner_closes_client_and_leaves_game_alive_on_release_and_error(self):
        from contextlib import nullcontext
        from openwar3 import Game
        for error in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'undead').mkdir()
                for name in ('attach_match.py','bridge_diagnostics.py','bot.py'):(root/name).write_text('# fixture')
                g=FakeGame();meta=dict(ready=True,process={'pid':123},player=4,epoch=7,clock=100)
                loop=N(paused=True,step=lambda action: 'released_by_user')
                if error:
                    def fail(action):raise RuntimeError('disconnected')
                    loop.step=fail
                with patch.object(a,'ROOT',root),patch.object(a,'STATE',root/'state.json'),patch.object(a,'COMMAND',root/'command.json'),patch.object(a,'RunnerLock',return_value=nullcontext()),patch.object(a,'probe',return_value=meta),patch.object(a,'still_same',return_value=True),patch('openwar3.Game',return_value=g) as connect,patch.object(a,'Attachment',return_value=loop):
                    r=a.run_attachment(123)
                connect.assert_called_once_with(pid=123,player=4,fair=True)
                self.assertTrue(g.closed);self.assertEqual(g.released,[10])
                self.assertEqual(r['result'],'error' if error else 'detached')
                self.assertTrue(json.loads((root/'state.json').read_text(encoding='utf-8'))['closed'])

    def test_stale_session_control_is_not_sent_to_reused_runner_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state.json';command=Path(temp)/'command.json'
            a.atomic_json(state,dict(closed=False,session='old',runner_pid=999,runner_created=1))
            with patch.object(a,'STATE',state),patch.object(a,'COMMAND',command),patch.object(a.psutil,'Process',return_value=N(create_time=lambda:2)):
                with self.assertRaisesRegex(RuntimeError,'复用'):a.control('resume')
            self.assertFalse(command.exists())

    def test_lock_prevents_two_controllers_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(a,'ROOT',Path(temp)):
            with a.RunnerLock():
                with self.assertRaises(RuntimeError):
                    with a.RunnerLock():pass
            with a.RunnerLock():pass
