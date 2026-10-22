"""Local, single-session controls for an OpenWar3AI training round."""
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from bootstrap import ROOT
from undead.version import DISPLAY_NAME, VERSION as BOT_VERSION

STATUS = ROOT / 'artifacts/training-control.json'
COMMAND = ROOT / 'artifacts/training-command.json'
VALID = {'forfeit', 'restart', 'switch'}


def valid_selection(selection):
    return (isinstance(selection, dict) and
            selection.get('matchup') in {'human', 'orc', 'undead', 'nightelf'} and
            type(selection.get('level')) is int and 1 <= selection['level'] <= 10 and
            selection.get('mode') in {'easy', 'hard'})


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def begin(selection, speed=100, seconds=180, wall_seconds=240):
    previous=previous_round(read_json(STATUS))
    session_id = uuid4().hex
    COMMAND.unlink(missing_ok=True)
    atomic_json(STATUS, dict(session_id=session_id, phase='loading', round=1,
                             selection=selection, speed=speed, seconds=seconds,
                             wall_seconds=wall_seconds, result=None,
                             bot_name=DISPLAY_NAME, bot_version=BOT_VERSION, apm=None,last_round=previous))
    return session_id


def status(session_id, **updates):
    current = read_json(STATUS)
    if not current or current.get('session_id') != session_id:
        raise RuntimeError('Training control session changed')
    current.update(updates)
    atomic_json(STATUS, current)


def post(session_id, action, selection=None):
    current = read_json(STATUS)
    if action not in VALID or not current or current.get('session_id') != session_id:
        return False
    if current.get('phase') != 'running':
        return False
    if action == 'switch' and not valid_selection(selection):
        return False
    atomic_json(COMMAND, dict(session_id=session_id, action=action,
                              selection=selection if action == 'switch' else None,
                              nonce=uuid4().hex))
    return True


def take(session_id):
    command = read_json(COMMAND)
    if not command or command.get('session_id') != session_id or command.get('action') not in VALID:
        return None
    COMMAND.unlink(missing_ok=True)
    if command['action']=='switch' and not valid_selection(command.get('selection')):return None
    return command


def round_summary(result):
    selection=result.get('selection') or {}
    return dict(result=result.get('result','unknown'),reason=result.get('reason'),
                selection={k:selection.get(k) for k in ('matchup','level','mode')},
                bot_name=result.get('bot_name'),artifact_dir=result.get('artifact_dir'),
                average_apm=result.get('average_apm') if result.get('apm_basis')=='accepted_unit_commands_game_time_v2' else None,
                accepted_actions=result.get('accepted_actions'),apm_game_seconds=result.get('apm_game_seconds'))


def previous_round(state):
    state=state or {}
    if state.get('last_round'):return state['last_round']
    if state.get('phase')=='finished':
        result=read_json(Path(state['artifact_dir'])/'result.json') if state.get('artifact_dir') else None
        return round_summary(result or state)
    return None


def previous_text(state):
    last=previous_round(state)
    if not last:return '上一局：暂无记录'
    results={'win':'胜利','loss':'失败','forfeit':'认输','timeout':'超时','error':'异常',
             'aborted':'已中止','restart_requested':'手动重开','selection_requested':'手动切关'}
    selection=last.get('selection') or {}
    race={'human':'人族','orc':'兽族','undead':'不死族','nightelf':'暗夜精灵'}.get(selection.get('matchup'),'')
    mode={'easy':'简单','hard':'困难'}.get(selection.get('mode'),'')
    average=last.get('average_apm')
    value=f'{average:.1f}' if isinstance(average,(int,float)) else '未记录'
    return f"上一局：{results.get(last.get('result'),last.get('result','未知'))} · {race} 第{selection.get('level','?')}关 {mode}\n上一局平均 APM：{value}"


def metrics_text(state, now=None):
    state=state or {}
    label=state.get('bot_name') if state.get('phase') in {'running','loading','restarting'} else DISPLAY_NAME
    label=label or DISPLAY_NAME
    fresh=(state.get('phase')=='running' and state.get('apm') is not None and
           (time.time() if now is None else now)-(state.get('metrics_updated') or 0)<=5)
    return f"{label}   ·   APM {state['apm'] if fresh else '—'}"


def launch(session_id):
    if sys.platform != 'win32':
        return None
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    executable = str(pythonw if pythonw.exists() else sys.executable)
    return subprocess.Popen([executable, '-B', str(ROOT / 'training.py'),
                             'panel', '--control-id', session_id], cwd=ROOT,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def panel(session_id=None):
    if sys.platform != 'win32':
        raise RuntimeError('Interactive training panel requires Windows')
    import tkinter as tk
    from tkinter import ttk
    from machine_start import active_processes
    current = read_json(STATUS)
    if session_id and (not current or current.get('session_id') != session_id):
        return 1
    session_id = session_id or (current or {}).get('session_id')
    selection = (current or {}).get('selection') or dict(matchup='orc', level=2, mode='easy')
    root = tk.Tk()
    root.title('dayuan 训练面板')
    root.geometry('550x320')
    root.resizable(False, False)
    root.attributes('-topmost', True)
    root.configure(bg='#eef2f7')
    race = {'orc': '兽族', 'human': '人族', 'undead': '不死族', 'nightelf': '暗夜精灵'}
    mode = {'easy': '简单', 'hard': '困难'}
    title_text = tk.StringVar(value=f"{race.get(selection['matchup'], '?')} · 当前第 {selection['level']} 关 · {mode.get(selection['mode'], '?')}")
    title = tk.Label(root, textvariable=title_text,
                     font=('Microsoft YaHei UI', 12, 'bold'), bg='#eef2f7')
    title.pack(pady=(14, 4))
    metrics=tk.StringVar(value=metrics_text(current))
    tk.Label(root,textvariable=metrics,font=('Microsoft YaHei UI',11,'bold'),bg='#eef2f7').pack(pady=3)
    tk.Label(root,text='APM：最近60游戏秒内已接受的单位操作',font=('Microsoft YaHei UI',9),bg='#eef2f7',fg='#64748b').pack()
    previous=tk.StringVar(value=previous_text(current))
    tk.Label(root,textvariable=previous,font=('Microsoft YaHei UI',10),bg='#eef2f7',fg='#334155').pack(pady=4)
    message = tk.StringVar(value='训练图正在载入…')
    tk.Label(root, textvariable=message, font=('Microsoft YaHei UI', 10), bg='#eef2f7').pack(pady=3)
    choices = tk.Frame(root, bg='#eef2f7')
    choices.pack(pady=(8, 1))
    tk.Label(choices,text='对战种族',bg='#eef2f7').pack(side='left',padx=(0,5))
    race_choice=tk.StringVar(value=race[selection['matchup']])
    ttk.Combobox(choices,textvariable=race_choice,values=list(race.values()),
                 state='readonly',width=9).pack(side='left',padx=(0,18))
    tk.Label(choices, text='关卡', bg='#eef2f7').pack(side='left', padx=(0, 5))
    level_choice = tk.StringVar(value=str(selection['level']))
    ttk.Combobox(choices, textvariable=level_choice, values=[str(i) for i in range(1, 11)],
                 state='readonly', width=5).pack(side='left', padx=(0, 22))
    tk.Label(choices, text='难度', bg='#eef2f7').pack(side='left', padx=(0, 5))
    mode_choice = tk.StringVar(value=mode[selection['mode']])
    ttk.Combobox(choices, textvariable=mode_choice, values=['简单', '困难'],
                 state='readonly', width=7).pack(side='left')
    buttons = tk.Frame(root, bg='#eef2f7')
    buttons.pack(pady=(13, 0))
    pending = {'action': None, 'round': None, 'process': None, 'log': None}

    def chosen():
        return dict(matchup=next(k for k,v in race.items() if v==race_choice.get()), level=int(level_choice.get()),
                    mode='easy' if mode_choice.get() == '简单' else 'hard')

    def launch_selected(next_selection, state):
        if active_processes():
            message.set('已有对局在运行，暂不能启动新关卡')
            return None
        settings = state or {}
        log_path = ROOT / 'artifacts' / ('training-panel-start-' + uuid4().hex[:8] + '.log')
        command = [sys.executable, '-B', str(ROOT / 'training.py'), 'play',
                   '--matchup', next_selection['matchup'], '--level', str(next_selection['level']),
                   '--mode', next_selection['mode'], '--speed', str(settings.get('speed', 100)),
                   '--seconds', str(settings.get('seconds', 180)),
                   '--wall-seconds', str(settings.get('wall_seconds', 240))]
        with log_path.open('w', encoding='utf-8') as output:
            process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                       stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        pending.update(action='switch', round=None, process=process, log=log_path)
        message.set('正在启动所选关卡…')
        return process

    def request(action):
        state = read_json(STATUS)
        if action == 'switch' and (not state or state.get('phase') == 'finished'):
            launch_selected(chosen(), state)
            return
        if post(session_id, action, chosen() if action == 'switch' else None):
            pending.update(action=action, round=state.get('round'))
            message.set({'forfeit': '正在认输并清理…',
                         'restart': '正在清理并重开本关…',
                         'switch': '正在清理并切换关卡…'}[action])

    forfeit = tk.Button(buttons, text='认输', width=11, command=lambda: request('forfeit'),
                        font=('Microsoft YaHei UI', 11), bg='#d94141', fg='white', disabledforeground='white')
    restart = tk.Button(buttons, text='重开本关', width=11, command=lambda: request('restart'),
                        font=('Microsoft YaHei UI', 11), bg='#2563eb', fg='white', disabledforeground='white')
    switch = tk.Button(buttons, text='开始所选关卡', width=13, command=lambda: request('switch'),
                       font=('Microsoft YaHei UI', 11), bg='#15803d', fg='white')
    forfeit.pack(side='left', padx=9)
    restart.pack(side='left', padx=9)
    switch.pack(side='left', padx=9)

    def refresh():
        state = read_json(STATUS)
        metrics.set(metrics_text(state))
        previous.set(previous_text(state))
        if session_id and (not state or state.get('session_id') != session_id):
            root.destroy()
            return
        if session_id is None and pending['action'] == 'switch' and state:
            root.destroy()
            return
        if pending['process'] is not None and pending['process'].poll() is not None:
            pending.update(action=None, process=None)
            message.set('启动未完成，请查看 ' + pending['log'].name)
        else:
            phase = (state or {}).get('phase')
            attempt = (state or {}).get('round')
            if phase == 'finished' and pending['action'] in {'forfeit', 'restart', 'switch'}:
                pending.update(action=None, process=None)
            active_selection = (state or {}).get('selection') or selection
            title_text.set(f"{race.get(active_selection['matchup'], '?')} · 当前第 {active_selection['level']} 关 · {mode.get(active_selection['mode'], '?')}")
            if pending['action'] in {'restart', 'switch'} and attempt != pending['round'] and phase == 'running':
                pending.update(action=None, round=attempt)
            if pending['action'] is None:
                if phase == 'finished':
                    review = (read_json(Path(state['artifact_dir']) / 'human-review.json')
                              if state.get('artifact_dir') else None)
                    if review and review.get('human_observed_map_result') == 'winner_slot_0':
                        message.set('原图已判胜（截图核验）；运行器读取异常')
                    else:
                        message.set('训练结束：' + str(state.get('result')))
                elif phase == 'loading':
                    message.set('第 ' + str(attempt) + ' 次尝试 · 正在载入…')
                elif phase == 'restarting':
                    message.set('正在清理并重开本关…')
                elif phase == 'running':
                    message.set('第 ' + str(attempt) + ' 次尝试 · 对局进行中')
                else:
                    message.set('选择种族、关卡和难度后开始训练')
        running = bool(state and state.get('phase') == 'running' and pending['action'] is None)
        for button in (forfeit, restart):
            button.configure(state='normal' if running else 'disabled')
        switch.configure(state='normal' if pending['action'] is None and
                         (not state or state.get('phase') in {'running', 'finished'}) else 'disabled')
        root.after(300, refresh)

    refresh()
    root.mainloop()
    return 0
