"""White desktop spectator panel. All game/log I/O stays off the Tk thread."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from sparring_dashboard import DashboardModel, PROFILES
from undead.speed_control import LABELS

BG, INK, MUTED, ACCENT = '#f4f6f8', '#172b40', '#526477', '#176b52'
RESULTS = {'win': 'dayuan 胜', 'loss': 'dayuan 负', 'aborted': '中止', 'timeout': '有界探针结束', 'error': '运行异常'}


def clock_text(value):
    return f'{int(value)//60:02d}:{int(value)%60:02d}' if isinstance(value, (int, float)) else '—'


def economy_text(row):
    r = row.get('resources', {})
    if not r:
        return '等待经济采样'
    return f"金币 {r.get('gold', '—')}    木材 {r.get('lumber', '—')}    人口 {r.get('food_used', '—')}/{r.get('food_cap', '—')}"


class SparringPanel:
    def __init__(self, window, model=None):
        self.window, self.model = window, model or DashboardModel()
        self.closed, self.busy = False, False
        self.state = {}
        self.requests, self.results = queue.Queue(), queue.Queue()
        window.title('dayuan · 训练观战')
        window.configure(bg=BG)
        window.geometry('720x710')
        window.minsize(680, 680)
        window.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(window)
        style.configure('TCombobox', padding=5)
        style.configure('Treeview', rowheight=27, font=('Microsoft YaHei UI', 9))
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 9, 'bold'))
        body = tk.Frame(window, bg=BG, padx=24, pady=20)
        body.pack(fill='both', expand=True)
        self.label(body, '训练观战', 22, bold=True).pack(anchor='w')
        self.label(body, '阶段 0 · 规则基线验证', 11, color=ACCENT).pack(anchor='w', pady=(2, 2))
        self.label(body, '尚未开始模型学习；胜负记录不代表学习进度。', 10, color=MUTED).pack(anchor='w')
        card = tk.Frame(body, bg='white', padx=18, pady=14)
        card.pack(fill='x', pady=(16, 12))
        self.status = self.label(card, '正在读取状态…', 13, bold=True, bg='white')
        self.status.pack(anchor='w')
        self.match = self.label(card, '等待观战对局', 10, color=MUTED, bg='white')
        self.match.pack(anchor='w', pady=(4, 10))
        self.metrics = self.label(card, '游戏时间 —     实际速度 —     实际视距 —', 12, bg='white')
        self.metrics.pack(anchor='w')
        self.own = self.label(card, 'dayuan：等待采样', 10, bg='white')
        self.own.pack(anchor='w', pady=(12, 4))
        self.enemy = self.label(card, '陪练：等待采样', 10, bg='white')
        self.enemy.pack(anchor='w')
        self.phase = self.label(card, '', 9, color=MUTED, bg='white')
        self.phase.pack(anchor='w', pady=(6, 0))
        controls = tk.Frame(body, bg=BG)
        controls.pack(fill='x')
        controls.columnconfigure(1, weight=1)
        self.label(controls, '视距', 11).grid(row=0, column=0, padx=(0, 12))
        self.camera = tk.IntVar(window, 2500)
        self.slider = tk.Scale(controls, from_=500, to=6000, resolution=50, orient='horizontal',
                               variable=self.camera, bg=BG, fg=INK, highlightthickness=0,
                               length=330, takefocus=True)
        self.slider.grid(row=0, column=1, sticky='ew')
        self.camera_button = self.button(controls, '应用视距', lambda: self.submit('camera', self.camera.get()))
        self.camera_button.grid(row=0, column=2, padx=(12, 0))
        self.label(controls, '速度', 11).grid(row=1, column=0, pady=(10, 0))
        self.speed = tk.StringVar(window, LABELS[400])
        self.speed_box = ttk.Combobox(controls, textvariable=self.speed, values=list(LABELS.values()), state='readonly', width=16)
        self.speed_box.grid(row=1, column=1, sticky='w', pady=(10, 0))
        self.speed_button = self.button(controls, '应用速度', lambda: self.submit('speed', next(k for k, v in LABELS.items() if v == self.speed.get())))
        self.speed_button.grid(row=1, column=2, padx=(12, 0), pady=(10, 0))
        self.feedback = self.label(body, '', 10, color=ACCENT)
        self.feedback.configure(height=2, wraplength=630)
        self.feedback.pack(fill='x', pady=(8, 0))
        self.label(body, '最近观战记录', 12, bold=True).pack(anchor='w', pady=(8, 8))
        self.table = ttk.Treeview(body, columns=('run', 'opponent', 'result'), show='headings', height=5)
        for name, label, width in [('run', '对局', 165), ('opponent', '陪练', 190), ('result', '结果', 150)]:
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=100, anchor='w')
        self.table.pack(fill='both', expand=True)
        self.label(body, '操作面板时游戏会失焦暂停；调整后切回游戏，等待确认生效。\n关闭面板不会停止对局。', 9, color=MUTED).pack(anchor='w', pady=(12, 0))
        self.worker = threading.Thread(target=self.work, daemon=True, name='spectator-panel-io')
        self.worker.start()
        self.history = None
        self.timer = window.after(50, self.drain)
        self.render({})

    def label(self, parent, text, size, color=INK, bold=False, bg=BG):
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'),
                        bg=bg, fg=color, anchor='w', justify='left')

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=ACCENT, fg='white',
                         activebackground='#10513e', activeforeground='white', cursor='hand2',
                         font=('Microsoft YaHei UI', 10), padx=14, pady=5, relief='flat')

    def work(self):
        try:
            while not self.closed:
                try:
                    request = self.requests.get(timeout=1)
                    if request is None:
                        break
                    state = self.model.request(*request)
                except queue.Empty:
                    try:
                        state = self.model.poll()
                    except Exception as exc:
                        self.results.put(('error', str(exc)))
                        continue
                except Exception as exc:
                    self.results.put(('error', str(exc)))
                    continue
                self.results.put(('state', state))
        finally:
            self.model.close()

    def submit(self, kind, value):
        if self.busy or not self.state.get('token'):
            return
        self.busy = True
        self.feedback.configure(text='正在发送设置…', fg=ACCENT)
        self.requests.put((self.state['token'], kind, value))
        self.enable(False)

    def enable(self, on):
        state = 'normal' if on else 'disabled'
        self.camera_button.configure(state=state)
        self.speed_button.configure(state=state)

    def render(self, state):
        self.state = state
        self.status.configure(text=state.get('status', '正在读取状态…'))
        self.match.configure(text=f"{PROFILES.get(state.get('profile'), '等待观战对局')}   ·   {state.get('run', '—')}")
        speed = state.get('speed')
        self.metrics.configure(text=f"游戏时间 {clock_text(state.get('clock'))}     实际速度 {LABELS.get(speed, '—')}     实际视距 {state.get('camera') or '—'}")
        own, enemy = state.get('dayuan', {}), state.get('opponent', {})
        self.own.configure(text='dayuan：' + economy_text(own))
        self.enemy.configure(text='陪练：' + economy_text(enemy))
        self.phase.configure(text=f"dayuan 策略 {state.get('decision', '—')}   ·   陪练阶段 {enemy.get('phase', '—')}   ·   经济采样 {clock_text(own.get('clock'))} / {clock_text(enemy.get('clock'))}")
        self.feedback.configure(text=state.get('message', ''), fg=ACCENT)
        self.enable(bool(state.get('token')) and not state.get('pending') and not self.busy)
        history = state.get('history', [])
        if history != self.history:
            self.table.delete(*self.table.get_children())
            for row in history:
                self.table.insert('', 'end', values=(row['run'], PROFILES.get(row['profile'], row['profile']), RESULTS.get(row['result'], row['result'])))
            self.history = history

    def drain(self):
        if self.closed:
            return
        while True:
            try:
                kind, value = self.results.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if kind == 'state':
                self.render(value)
            else:
                self.feedback.configure(text=value, fg='#a12626')
                self.enable(False)
        self.timer = self.window.after(100, self.drain)

    def close(self):
        self.closed = True
        self.requests.put(None)
        self.window.after_cancel(self.timer)
        self.window.destroy()


if __name__ == '__main__':
    app = tk.Tk()
    SparringPanel(app)
    app.mainloop()
