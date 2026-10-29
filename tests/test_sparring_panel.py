import threading
import time
import tkinter as tk
import unittest
from sparring_panel import SparringPanel


class Model:
    def __init__(self):
        self.state = dict(token=(123, 100, 1, 'test'), status='对局进行中', clock=125, speed=100,
                          camera=6000, profile='kfai-human', run='test', history=[])
        self.calls = []
        self.closed = False

    def poll(self):
        return dict(self.state)

    def request(self, *args):
        self.calls.append((threading.get_ident(), args))
        self.state['pending'] = ('speed', 400, 1)
        return dict(self.state)

    def close(self):
        self.closed = True


class PanelTests(unittest.TestCase):
    def test_controls_keep_actual_value_and_send_off_main_thread(self):
        window = tk.Tk(); window.withdraw()
        model = Model(); panel = SparringPanel(window, model)
        try:
            panel.render(model.poll())
            panel.speed.set('4×'); panel.submit('speed', 400)
            deadline = time.monotonic() + 2
            while not model.calls and time.monotonic() < deadline:
                window.update(); time.sleep(.01)
            self.assertTrue(model.calls)
            self.assertNotEqual(model.calls[0][0], threading.get_ident())
            panel.busy = False; panel.render(model.poll())
            self.assertIn('实际速度 1×', panel.metrics.cget('text'))
            self.assertEqual(panel.speed.get(), '4×')
            self.assertEqual(str(panel.speed_button.cget('state')), 'disabled')
            window.update_idletasks()
            self.assertLessEqual(panel.metrics.winfo_reqwidth(), 630)
            self.assertLessEqual(panel.phase.winfo_reqwidth(), 630)
        finally:
            panel.close(); panel.worker.join(2)
        self.assertTrue(model.closed)


if __name__ == '__main__':
    unittest.main()
