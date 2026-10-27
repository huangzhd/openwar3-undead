import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import attach_match as attach
import console_state as model
from kk_control import Surrender
from tests.test_attach_0155 import FakeGame


def chat(sender,text='gg'):
    return N(kind='message',chat=dict(sender=sender,text=text))


class SurrenderTests(unittest.TestCase):
    def fixture(self):
        actions=[]
        g=FakeGame()
        task=Surrender('request','Me',send=lambda pid:actions.append(('chat',pid)),
                       leave=lambda game:actions.append(('exit',game.pid)))
        return g,task,actions

    def test_only_fresh_own_gg_allows_one_exit_and_waiting_is_bounded(self):
        g,task,actions=self.fixture()
        task.step(g,[chat('Me')],0) # Old event from before sending is not evidence.
        task.step(g,[chat('Enemy')],1)
        task.step(g,[chat('Me','other text')],2)
        self.assertEqual(actions,[('chat',123)])
        task.step(g,[chat('|cffff0303Me|r')],3)
        self.assertEqual(actions,[('chat',123),('exit',123)])
        self.assertTrue(task.gg_confirmed)
        task.step(g,[chat('Me')],4);self.assertEqual(len(actions),2)
        task.step(g,[],11)
        self.assertEqual(task.stage,'failed');self.assertIn('未确认游戏退出',task.message)

    def test_send_failure_missing_name_and_no_chat_confirmation_never_exit(self):
        g,task,actions=self.fixture();task.local_name=''
        task.step(g,[],0);self.assertFalse(actions)
        g,task,actions=self.fixture()
        task.send=lambda pid:(_ for _ in ()).throw(RuntimeError('denied'))
        task.step(g,[],0);self.assertEqual(task.stage,'failed');self.assertFalse(task.exit_requested)
        g,task,actions=self.fixture();task.step(g,[],0);task.step(g,[],5)
        self.assertEqual(actions,[('chat',123)]);self.assertEqual(task.stage,'failed')

    def test_surrender_pauses_bot_and_duplicate_token_does_not_send_again(self):
        g,task,actions=self.fixture();bots=[]
        def factory(*args):
            b=N(ticks=0,enemy_race=2,intent='test',observe_events=lambda e:None)
            def tick():b.ticks+=1
            b.tick=tick;bots.append(b);return b
        loop=attach.Attachment(g,dict(player=4,epoch=7,clock=100,local_name='Me'),2,lambda *a,**k:None,factory)
        loop.step('resume',0);self.assertEqual(bots[0].ticks,1)
        loop.control_request_id='request'
        with patch('kk_control.Surrender',return_value=task):loop.step('surrender',1)
        self.assertTrue(loop.paused);self.assertEqual(g.released,[10]);self.assertIsNone(loop.bot)
        g.s.clock+=1;g.s.publish_count+=1;loop.step('surrender',7)
        loop.step('surrender',8)
        self.assertEqual(actions,[('chat',123)]);self.assertEqual(bots[0].ticks,1)
        loop.step('resume',9);self.assertFalse(loop.paused)

    def test_match_change_prevents_surrender_input(self):
        g,task,actions=self.fixture()
        loop=attach.Attachment(g,dict(player=4,epoch=7,clock=100,local_name='Me'),2,lambda *a,**k:None)
        g.raw.epoch=8;loop.control_request_id='request'
        with patch('kk_control.Surrender',return_value=task):
            self.assertEqual(loop.step('surrender',1),'match_or_player_changed')
        self.assertFalse(actions)


class PanelModelTests(unittest.TestCase):
    def test_live_metadata_overrides_config_and_paused_stale_apm_is_not_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts').mkdir()
            path=root/'artifacts/attachment.json'
            state=dict(session='now',closed=False,paused=False,updated=time.time(),clock=75,apm=320,
                       opponent=dict(race=2),map=dict(status='verified',alias='LR'),control_capabilities=['surrender'])
            path.write_text(json.dumps(state))
            (root/'artifacts/auto-takeover-config.json').write_text(json.dumps(dict(enemy_race=1)))
            view=model.DashboardModel(root)
            with patch.object(model,'session_alive',return_value=True):
                data=view.poll();self.assertEqual(data['enemy_race'],2);self.assertEqual(data['apm'],320)
                self.assertEqual(data['map']['alias'],'LR');self.assertTrue(data['can_surrender'])
                state['paused']=True;path.write_text(json.dumps(state));self.assertIsNone(view.poll()['apm'])
                state.update(paused=False,updated=time.time()-10);path.write_text(json.dumps(state))
                self.assertTrue(view.poll()['stale']);self.assertIsNone(view.poll()['apm'])

    def test_surrender_requires_capability_current_session_and_unique_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts').mkdir();path=root/'artifacts/attachment.json'
            state=dict(session='new',closed=False);path.write_text(json.dumps(state))
            with patch.object(model,'session_alive',return_value=True):
                with self.assertRaises(RuntimeError):model.request_control('surrender','old',root)
                with self.assertRaises(RuntimeError):model.request_control('surrender','new',root)
                state['control_capabilities']=['surrender'];path.write_text(json.dumps(state))
                first=model.request_control('surrender','new',root);second=model.request_control('surrender','new',root)
                self.assertNotEqual(first['request_id'],second['request_id'])
                self.assertEqual(model.read_json(root/'artifacts/attachment-command.json'),second)
                state['surrender']=dict(stage='waiting_gg');path.write_text(json.dumps(state))
                with self.assertRaises(RuntimeError):model.request_control('resume','new',root)


class PanelWidgetTests(unittest.TestCase):
    def test_surrender_feedback_requires_matching_request_and_confirmed_result(self):
        import tkinter as tk
        from bot_console import Console
        window=tk.Tk();window.withdraw()
        data=dict(session='test',alive=True,paused=False,stale=False,status='AI 正在接管',clock='01:20',
                  intent='练级',summary_clock='01:15',decision={},history=[],automation='单局监听运行中',
                  log_age=0,pid=123,enemy_race=2,apm=300,can_surrender=True,
                  map=dict(status='verified',alias='LR',name='Last Refuge',sha256='abc'),
                  surrender=dict(request_id='old',stage='failed',message='旧错误'))
        sent=[]
        def send(action,session):sent.append((action,session));return dict(request_id='new')
        try:
            ui=Console(window,model=N(poll=lambda:dict(data)),send=send)
            ui.surrender.invoke();self.assertEqual(sent,[('surrender','test')]);self.assertIsNotNone(ui.pending)
            self.assertNotIn('旧错误',ui.feedback.cget('text'))
            data['surrender']=dict(request_id='new',stage='waiting_gg',message='等待 gg')
            ui.render(dict(data));self.assertEqual(ui.toggle.cget('state'),'disabled')
            data['surrender']=dict(request_id='new',stage='finished',message='gg 已发送，游戏已退出')
            data['alive']=False;ui.render(dict(data));self.assertIsNone(ui.pending)
            self.assertIn('已退出',ui.feedback.cget('text'));self.assertIn('LR',ui.map_name.cget('text'))
        finally:window.destroy()
