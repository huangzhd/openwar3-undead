import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import console_state as c


class ConsoleModelTests(unittest.TestCase):
    def test_partial_utf8_line_and_truncated_log_are_handled(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.jsonl';tail=c.EventTail()
            line=json.dumps(dict(event='attachment_summary',intent='进攻'),ensure_ascii=False).encode('utf-8')+b'\n'
            split=line.index('攻'.encode('utf-8'))+1
            path.write_bytes(line[:split]);self.assertEqual(tail.read(path),[])
            with path.open('ab') as stream:stream.write(line[split:])
            self.assertEqual(tail.read(path)[0]['intent'],'进攻');self.assertEqual(tail.read(path),[])
            path.write_bytes(b'{"event":"reset"}\n')
            self.assertEqual(tail.read(path),[{'event':'reset'}])

    def test_command_is_bound_to_displayed_session_and_rejects_new_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts').mkdir()
            path=root/'artifacts/attachment.json';path.write_text(json.dumps(dict(session='new',closed=False)))
            with patch.object(c,'session_alive',return_value=True):
                with self.assertRaisesRegex(RuntimeError,'变化'):c.request_control('pause','old',root)
                self.assertFalse((root/'artifacts/attachment-command.json').exists())
                c.request_control('resume','new',root)
            self.assertEqual(c.read_json(root/'artifacts/attachment-command.json'),dict(action='resume',session='new'))

    def test_dead_runner_never_receives_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts').mkdir()
            (root/'artifacts/attachment.json').write_text(json.dumps(dict(session='a',closed=False)))
            with patch.object(c,'session_alive',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'没有'):c.request_control('pause','a',root)
            self.assertFalse((root/'artifacts/attachment-command.json').exists())

    def test_new_session_clears_old_decision_and_paused_status_is_confirmed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'artifacts/one';out.mkdir(parents=True)
            state=root/'artifacts/attachment.json'
            state.write_text(json.dumps(dict(session='one',paused=False,artifacts=str(out))))
            (out/'events.jsonl').write_text(json.dumps(dict(event='attachment_summary',intent='进攻',clock=40))+'\n')
            model=c.DashboardModel(root)
            with patch.object(c,'session_alive',return_value=True):
                self.assertEqual(model.poll()['intent'],'进攻')
                state.write_text(json.dumps(dict(session='one',paused=True,artifacts=str(out))))
                self.assertTrue(model.poll()['paused'])
                state.write_text(json.dumps(dict(session='two',paused=False)))
                data=model.poll()
            self.assertEqual(data['intent'],'等待决策');self.assertEqual(data['history'],[])
            self.assertTrue(data['stale'])

    def test_reused_runner_pid_does_not_appear_connected(self):
        from types import SimpleNamespace as N
        with patch.object(c.psutil,'Process',return_value=N(create_time=lambda:99)),patch.object(c,'still_same',return_value=True):
            self.assertFalse(c.session_alive(dict(closed=False,runner_pid=1,runner_created=20,process={})))

    def test_purchase_receipt_is_not_labelled_completed(self):
        self.assertEqual(c.describe(dict(event='purchase',kind='build',code='uaod')),'建造黑暗祭坛 · 已下达指令')
        self.assertNotIn('完成',c.describe(dict(event='new_units',types=['uaod'])))


class ConsoleWidgetTests(unittest.TestCase):
    def test_buttons_wait_for_acknowledgement_and_never_touch_live_game(self):
        import tkinter as tk
        from bot_console import Console
        from types import SimpleNamespace as N
        window=tk.Tk();window.withdraw()
        data=dict(session='test',alive=True,paused=False,stale=False,status='AI 正在接管',clock='01:20',
                  intent='进攻',summary_clock='01:15',decision={},history=[],automation='已启用',
                  error='',log_age=0,pid=123,enemy_race=1)
        sent=[]
        try:
            ui=Console(window,model=N(poll=lambda:dict(data)),send=lambda action,session:sent.append((action,session)))
            ui.pause.invoke();self.assertEqual(sent,[('pause','test')]);self.assertIsNotNone(ui.pending)
            self.assertIn('等待',ui.feedback.cget('text'));self.assertEqual(ui.resume.cget('state'),'disabled')
            data.update(paused=True,status='已停止接管 · 可手动操作');ui.render(dict(data))
            self.assertIsNone(ui.pending);self.assertEqual(ui.resume.cget('state'),'normal')
            ui.resume.invoke();self.assertEqual(sent[-1],('resume','test'));self.assertIsNotNone(ui.pending)
            data.update(paused=False,status='AI 正在接管');ui.render(dict(data))
            self.assertIsNone(ui.pending);self.assertIn('已确认',ui.feedback.cget('text'))
            window.update_idletasks()
            self.assertGreater(ui.pause.winfo_reqwidth(),100)
        finally:window.destroy()


if __name__=='__main__':unittest.main()
