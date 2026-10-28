import threading
import time
import tkinter as tk
import unittest

from practice_control import MAP_LABELS, RACE_LABELS
from practice_panel import PracticePanel


class FakeModel:
    def __init__(self, **settings):
        self.data = dict(settings=dict({'map_alias': 'LR', 'human_race': 2}, **settings),
                         phase='idle', busy=False, can_start=True, status='准备好开始练习',
                         error='', display='显示器原生分辨率', clock=None, result=None)
        self.calls = []
        self.io_threads = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.start_error = None
        self.poll_error = None

    def poll(self):
        self.io_threads.append(threading.get_ident())
        if self.poll_error:
            raise RuntimeError(self.poll_error)
        return dict(self.data, settings=dict(self.data['settings']))

    def start(self, alias, race):
        self.io_threads.append(threading.get_ident())
        self.calls.append((alias, race))
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError('Test launch was not released')
        if self.start_error:
            raise RuntimeError(self.start_error)
        self.data.update(settings=dict(map_alias=alias, human_race=race), phase='launching',
                         busy=True, can_start=False, status='正在加载游戏')
        return dict(started=True)


class PracticePanelTests(unittest.TestCase):
    def make_panel(self, model=None):
        model = model or FakeModel()
        window = tk.Tk()
        window.withdraw()
        ui = PracticePanel(window, model)
        def cleanup():
            model.release.set()
            if not ui.closed:
                ui.close()
            ui._worker.join(timeout=2)
        self.addCleanup(cleanup)
        self.pump(window, lambda: ui.settings_loaded)
        return ui, model, window

    def pump(self, window, ready):
        deadline = time.monotonic() + 2
        while not ready() and time.monotonic() < deadline:
            window.update()
            time.sleep(.005)
        window.update_idletasks()
        self.assertTrue(ready(), 'The UI did not consume its background result')

    def test_start_uses_selected_map_race_and_does_not_block_or_submit_twice(self):
        ui, model, window = self.make_panel()
        ui.map_choice.set(MAP_LABELS['NI'])
        ui.race_choice.set(RACE_LABELS[3])
        model.release.clear()
        try:
            ui.start_button.invoke()
            ui.start_button.invoke()
            ui.start_practice()
            self.assertEqual(ui.start_button.cget('state'), 'disabled')
            self.assertEqual(str(ui.map_box.cget('state')), 'disabled')
            self.assertEqual(str(ui.race_box.cget('state')), 'disabled')
            self.assertIn('正在启动', ui.status.cget('text'))
            responsive = []
            window.after(0, lambda: responsive.append(True))
            self.pump(window, lambda: bool(responsive) and model.entered.is_set())
            self.assertEqual(model.calls, [('NI', 3)])
            self.assertNotIn(threading.get_ident(), model.io_threads)
        finally:
            model.release.set()
        self.pump(window, lambda: not ui.pending_start)
        self.assertEqual(ui.current['phase'], 'launching')
        self.assertEqual(ui.start_button.cget('state'), 'disabled')

    def test_running_blocks_duplicate_start_and_finished_reenables_selection(self):
        ui, model, window = self.make_panel()
        for phase in ('launching', 'running'):
            model.data.update(phase=phase, busy=True, can_start=False,
                              status='正在加载' if phase == 'launching' else 'dayuan 正在练习', clock=125)
            ui.refresh()
            self.pump(window, lambda: ui.current['phase'] == phase)
            ui.start_practice()
            self.assertFalse(model.calls)
            self.assertEqual(str(ui.map_box.cget('state')), 'disabled')
            self.assertEqual(ui.start_button.cget('state'), 'disabled')
        self.assertIn('02:05', ui.detail.cget('text'))
        model.data.update(phase='finished', busy=False, can_start=True, status='本局已结束')
        ui.refresh()
        self.pump(window, lambda: ui.current['phase'] == 'finished')
        self.assertEqual(ui.start_button.cget('state'), 'normal')
        self.assertEqual(str(ui.map_box.cget('state')), 'readonly')
        self.assertEqual(str(ui.race_box.cget('state')), 'readonly')

    def test_error_is_inline_and_polling_does_not_erase_chosen_settings(self):
        ui, model, window = self.make_panel()
        ui.map_choice.set(MAP_LABELS['TR'])
        ui.race_choice.set(RACE_LABELS[4])
        model.start_error = '地图文件当前不可用，请检查地图目录。'
        ui.start_practice()
        self.pump(window, lambda: not ui.pending_start)
        self.assertIn(model.start_error, ui.feedback.cget('text'))
        # The failed backend still reports its old persisted LR/Orc settings.
        ui.refresh()
        self.pump(window, lambda: not ui._poll_pending)
        self.assertEqual(ui.map_choice.get(), MAP_LABELS['TR'])
        self.assertEqual(ui.race_choice.get(), RACE_LABELS[4])
        self.assertIn(model.start_error, ui.feedback.cget('text'))
        self.assertEqual(ui.start_button.cget('state'), 'normal')

    def test_saved_selection_is_loaded_and_closing_panel_does_not_start_or_stop_game(self):
        model = FakeModel()
        model.data['settings'] = dict(map_alias='TM', human_race=1)
        ui, model, window = self.make_panel(model)
        self.assertEqual(ui.map_choice.get(), MAP_LABELS['TM'])
        self.assertEqual(ui.race_choice.get(), RACE_LABELS[1])
        self.assertEqual(len(ui.map_box.cget('values')), 8)
        self.assertEqual(len(ui.race_box.cget('values')), 4)
        self.assertIn('dayuan（亡灵）', ui.opponent.cget('text'))
        self.assertIn('1 倍速', ui.opponent.cget('text'))
        model.data.update(phase='running', busy=True, can_start=False)
        ui.render(model.data)
        ui.close()
        ui._worker.join(timeout=2)
        self.assertFalse(ui._worker.is_alive())
        self.assertFalse(model.calls)
        self.assertEqual(model.data['phase'], 'running')

    def test_read_failure_disables_start_until_status_recovers(self):
        ui, model, window = self.make_panel()
        model.poll_error = '状态文件暂时不可读'
        ui.refresh()
        self.pump(window, lambda: bool(ui.poll_error))
        self.assertIn(model.poll_error, ui.feedback.cget('text'))
        self.assertEqual(ui.start_button.cget('state'), 'disabled')
        ui.start_practice()
        self.assertFalse(model.calls)
        model.poll_error = None
        ui.refresh()
        self.pump(window, lambda: not ui.poll_error)
        self.assertEqual(ui.feedback.cget('text'), '')
        self.assertEqual(ui.start_button.cget('state'), 'normal')

    def test_chinese_error_and_status_fit_resizable_non_topmost_layout(self):
        ui, model, window = self.make_panel()
        old_height = window.minsize()[1]
        error = '未能打开所选地图，请检查地图目录、文件是否完整，以及当前是否仍有游戏运行。' * 6
        ui.render(dict(model.data, phase='error', status='启动未完成，请检查下方错误后重试。', error=error))
        window.update()
        window.update_idletasks()
        minimum_width, minimum_height = window.minsize()
        self.assertEqual(ui.feedback.cget('text'), error)
        self.assertGreater(minimum_height, old_height)
        self.assertGreaterEqual(minimum_height, ui.outer.winfo_reqheight())
        self.assertGreaterEqual(minimum_width, ui.form.winfo_reqwidth() + ui.pad * 2)
        self.assertGreater(ui.feedback.winfo_reqheight(), 3 * 12)
        self.assertEqual(window.title(), 'dayuan 人机练习')
        self.assertEqual(window.resizable(), (1, 1))
        self.assertFalse(window.attributes('-topmost'))
        self.assertIn('关闭面板不会关闭游戏', ui.footer.cget('text'))


if __name__ == '__main__':
    unittest.main()
