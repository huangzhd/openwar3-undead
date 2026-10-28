"""Local single-match practice launcher; closing this window leaves the game alone."""
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont, ttk

from bootstrap import ROOT
from practice_control import MAP_LABELS, RACE_LABELS, PracticeModel


BG = '#eef2f7'
CARD = BG
TEXT = '#1e293b'
MUTED = '#64748b'
GREEN = '#15803d'
GREEN_TEXT = '#ffffff'
ERROR = '#b91c1c'
FONT = 'Microsoft YaHei UI'


class PracticePanel:
    def __init__(self, window, model=None):
        self.window = window
        self.model = model if model is not None else PracticeModel(root=ROOT)
        self.current = dict(phase='idle', busy=False, can_start=False,
                            status='正在读取练习状态…', error='', display='', clock=None)
        self.pending_start = False
        self.local_error = ''
        self.poll_error = ''
        self.closed = False
        self.settings_loaded = False
        self.choices_edited = False
        self._setting_choices = False
        self._poll_pending = False
        self._requests = queue.Queue()
        self._results = queue.Queue()
        self._callbacks = set()
        self.map_values = dict(MAP_LABELS)
        self.race_values = dict(RACE_LABELS)
        self.map_choice = tk.StringVar(window, self.map_values['LR'])
        self.race_choice = tk.StringVar(window, self.race_values[2])
        self.map_choice.trace_add('write', self._choices_changed)
        self.race_choice.trace_add('write', self._choices_changed)

        window.title('dayuan 人机练习')
        window.configure(bg=BG)
        window.resizable(True, True)
        window.attributes('-topmost', False)
        window.protocol('WM_DELETE_WINDOW', self.close)
        self.unit = max(1.0, tkfont.Font(window, family=FONT, size=11).metrics('linespace') / 22)
        self.pad = max(14, round(16 * self.unit))

        self.outer = tk.Frame(window, bg=BG, padx=self.pad, pady=self.pad)
        self.outer.pack(fill='both', expand=True)
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(7, weight=1)
        self.heading = self.label(self.outer, '和 dayuan 练一局', 12, TEXT, bold=True)
        self.heading.configure(anchor='center')
        self.heading.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        self.opponent = self.label(self.outer, '对手 dayuan（亡灵）  ·  1 倍速  ·  本地单局', 10, MUTED)
        self.opponent.configure(anchor='center')
        self.opponent.grid(row=1, column=0, sticky='ew', pady=(0, 8))

        self.form = tk.Frame(self.outer, bg=CARD, padx=self.pad, pady=self.pad)
        self.form.grid(row=2, column=0, sticky='ew')
        self.form.columnconfigure(1, weight=1)
        self.label(self.form, '地图', 10, TEXT, bg=CARD).grid(row=0, column=0, sticky='w', padx=(0, 12), pady=(0, 10))
        self.map_box = ttk.Combobox(self.form, textvariable=self.map_choice,
                                   values=list(self.map_values.values()), state='disabled',
                                   width=26)
        self.map_box.grid(row=0, column=1, sticky='ew', pady=(0, 10))
        self.label(self.form, '我方种族', 10, TEXT, bg=CARD).grid(row=1, column=0, sticky='w', padx=(0, 12))
        self.race_box = ttk.Combobox(self.form, textvariable=self.race_choice,
                                    values=list(self.race_values.values()), state='disabled',
                                    width=26)
        self.race_box.grid(row=1, column=1, sticky='ew')

        self.start_button = tk.Button(self.outer, text='开始练习', command=self.start_practice,
                                      font=(FONT, 11), width=13, bg=GREEN, fg=GREEN_TEXT,
                                      activebackground='#166534', activeforeground=GREEN_TEXT,
                                      disabledforeground=MUTED,
                                      highlightbackground=BG,
                                      highlightcolor=TEXT, cursor='hand2', pady=4)
        self.start_button.grid(row=3, column=0, pady=(8, 12))
        self.status = self.label(self.outer, '', 11, TEXT, bold=True)
        self.status.configure(anchor='center')
        self.status.grid(row=4, column=0, sticky='ew', pady=(0, 6))
        self.detail = self.label(self.outer, '', 9, MUTED)
        self.detail.configure(anchor='center')
        self.detail.grid(row=5, column=0, sticky='ew', pady=(0, 8))
        # Reserve feedback room so a short launch error does not shift the form.
        self.feedback = self.label(self.outer, '', 10, ERROR)
        self.feedback.configure(height=3)
        self.feedback.grid(row=6, column=0, sticky='new')
        self.footer = self.label(self.outer, '关闭面板不会关闭游戏；本局结束后可再开始练习。', 9, MUTED)
        self.footer.configure(anchor='center')
        self.footer.grid(row=8, column=0, sticky='ew', pady=(16, 0))
        self.wrapped = (self.heading, self.opponent, self.status, self.detail, self.feedback, self.footer)
        window.bind('<Configure>', self._resize, add='+')
        self.render(self.current)
        window.update_idletasks()
        width = max(round(550 * self.unit), self.form.winfo_reqwidth() + self.pad * 2)
        self._minimum_width = width
        self._set_wrap(width)
        window.update_idletasks()
        height = self.outer.winfo_reqheight()
        window.minsize(width, height)
        window.geometry(f'{width}x{height}')
        self._worker = threading.Thread(target=self._work, name='practice-panel-io', daemon=True)
        self._worker.start()
        self.refresh()
        self._after(50, self._drain_results)

    def label(self, parent, text, size, color, bg=BG, bold=False):
        return tk.Label(parent, text=text, font=(FONT, size, 'bold' if bold else 'normal'),
                        fg=color, bg=bg, anchor='w', justify='left')

    def _choices_changed(self, *args):
        if not self._setting_choices:
            self.choices_edited = True

    def _after(self, milliseconds, callback):
        if self.closed:
            return
        token = None
        def invoke():
            self._callbacks.discard(token)
            if not self.closed:
                callback()
        token = self.window.after(milliseconds, invoke)
        self._callbacks.add(token)

    def _set_wrap(self, width):
        available = max(180, width - self.pad * 2)
        for label in self.wrapped:
            label.configure(wraplength=available)
        # An arbitrarily long error stays readable in a resizable window.
        text = self.feedback.cget('text')
        metrics = tkfont.Font(font=self.feedback.cget('font'))
        rows = 0
        for paragraph in text.splitlines():
            pixels = 0
            rows += 1
            for char in paragraph:
                pixels += metrics.measure(char)
                if pixels > available:
                    rows += 1
                    pixels = metrics.measure(char)
        self.feedback.configure(height=max(3, rows))

    def _resize(self, event):
        if event.widget is self.window and not self.closed:
            self._set_wrap(event.width)
            self._after(0, self._fit_height)

    def _fit_height(self):
        if hasattr(self, '_minimum_width'):
            self.window.update_idletasks()
            self.window.minsize(self._minimum_width, self.outer.winfo_reqheight())

    def _work(self):
        while True:
            request = self._requests.get()
            if request is None or self.closed:
                return
            kind, args = request
            try:
                if kind == 'start':
                    self.model.start(*args)
                data = self.model.poll()
                self._results.put((kind, data, None))
            except Exception as exc:
                self._results.put((kind, None, str(exc)))

    def refresh(self):
        if not self._poll_pending and not self.pending_start and not self.closed:
            self._poll_pending = True
            self._requests.put(('poll', ()))
        self._after(800, self.refresh)

    def _drain_results(self):
        while True:
            try:
                kind, data, error = self._results.get_nowait()
            except queue.Empty:
                break
            if kind == 'poll':
                self._poll_pending = False
            else:
                self.pending_start = False
            if error:
                if kind == 'poll':
                    self.poll_error = '状态读取失败：' + error
                    self.current = dict(self.current, can_start=False)
                else:
                    self.local_error = '启动失败：' + error
                self.render(self.current)
            else:
                self.poll_error = ''
                self.render(data)
        self._after(50, self._drain_results)

    def render(self, data):
        self.current = dict(data)
        if not self.settings_loaded and 'settings' in data:
            if not self.choices_edited:
                settings = data['settings']
                self._setting_choices = True
                try:
                    self.map_choice.set(self.map_values.get(settings.get('map_alias'), self.map_values['LR']))
                    self.race_choice.set(self.race_values.get(settings.get('human_race'), self.race_values[2]))
                finally:
                    self._setting_choices = False
            self.settings_loaded = True
        phase = data.get('phase', 'idle')
        busy = self.pending_start or data.get('busy', False) or phase in ('launching', 'running')
        enabled = bool(data.get('can_start')) and not busy
        for choice in (self.map_box, self.race_box):
            choice.configure(state='disabled' if busy else 'readonly')
        caption = ('正在启动练习…' if self.pending_start or phase == 'launching' else
                   '练习进行中' if phase == 'running' else '开始练习')
        self.start_button.configure(text=caption, state='normal' if enabled else 'disabled',
                                    bg=GREEN if enabled else '#e2e8f0',
                                    cursor='hand2' if enabled else 'arrow')
        self.status.configure(text='正在启动练习，请稍候…' if self.pending_start else data.get('status', '等待开始'),
                              fg=GREEN if phase == 'running' else TEXT)
        detail = str(data.get('display') or '')
        clock = data.get('clock')
        if isinstance(clock, (int, float)) and clock >= 0:
            detail += ('  ·  ' if detail else '') + f'游戏时间 {int(clock)//60:02d}:{int(clock)%60:02d}'
        self.detail.configure(text=detail)
        self.feedback.configure(text=self.local_error or self.poll_error or data.get('error') or '')
        width = self.window.winfo_width()
        self._set_wrap(width if width > 1 else round(550 * self.unit))
        self._after(0, self._fit_height)

    def start_practice(self):
        if self.pending_start or not self.current.get('can_start') or self.current.get('busy'):
            return
        if self.current.get('phase') in ('launching', 'running'):
            return
        try:
            alias = next(key for key, value in self.map_values.items() if value == self.map_choice.get())
            race = next(key for key, value in self.race_values.items() if value == self.race_choice.get())
        except StopIteration:
            self.local_error = '请选择列表中的地图和我方种族。'
            self.render(self.current)
            return
        self.pending_start = True
        self.local_error = ''
        self.render(self.current)
        self._requests.put(('start', (alias, race)))

    def close(self):
        if self.closed:
            return
        self.closed = True
        for token in self._callbacks:
            self.window.after_cancel(token)
        self._callbacks.clear()
        self._requests.put(None)
        self.window.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    window = tk.Tk()
    PracticePanel(window)
    window.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
