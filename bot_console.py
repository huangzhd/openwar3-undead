"""Native desktop status panel. Reads logs; buttons use the existing session command channel."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk

from bootstrap import ROOT
from console_state import DashboardModel, ACTIONS, NAMES, request_control

BG='#101822';CARD='#192431';TEXT='#edf3fa';MUTED='#9badc2';GREEN='#5bd5a0';AMBER='#ffcb77'


class Console:
    def __init__(self,window,model=None,send=request_control):
        self.window=window;self.model=model or DashboardModel();self.send=send
        self.current={};self.pending=None;self.last_rows=None
        window.title('OpenWar3AI · 接管控制台');window.geometry('820x710');window.minsize(700,610)
        window.configure(bg=BG)
        style=ttk.Style(window);style.theme_use('clam')
        style.configure('Treeview',background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=30,
                        borderwidth=0,font=('Microsoft YaHei UI',10))
        style.configure('Treeview.Heading',background='#253549',foreground=TEXT,font=('Microsoft YaHei UI',10))
        style.map('Treeview',background=[('selected','#294c61')])
        outer=tk.Frame(window,bg=BG,padx=24,pady=20);outer.pack(fill='both',expand=True)
        self.label(outer,'OPENWAR3AI  /  接管控制台',12,MUTED).pack(anchor='w')
        top=tk.Frame(outer,bg=BG);top.pack(fill='x',pady=(16,12))
        self.status=self.label(top,'读取状态…',23,GREEN);self.status.pack(side='left')
        self.clock=self.label(top,'--:--',24,TEXT);self.clock.pack(side='right')
        self.connection=self.label(outer,'',10,MUTED);self.connection.pack(anchor='w')
        buttons=tk.Frame(outer,bg=BG);buttons.pack(fill='x',pady=(16,8))
        self.pause=tk.Button(buttons,text='停止接管',command=lambda:self.command('pause'),bg='#ecbc70',fg='#17202b',
                             activebackground='#ffd995',font=('Microsoft YaHei UI',12,'bold'),relief='flat',padx=28,pady=12)
        self.pause.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.resume=tk.Button(buttons,text='继续接管',command=lambda:self.command('resume'),bg=GREEN,fg='#11271e',
                              activebackground='#83eac0',font=('Microsoft YaHei UI',12,'bold'),relief='flat',padx=28,pady=12)
        self.resume.pack(side='left',fill='x',expand=True,padx=(8,0))
        self.feedback=self.label(outer,'停止接管后，游戏继续；已有采集、移动和训练指令会保留。',10,MUTED)
        self.feedback.pack(anchor='w',pady=(0,12))
        card=tk.Frame(outer,bg=CARD,padx=18,pady=16);card.pack(fill='x')
        self.label(card,'当前决策',10,MUTED,bg=CARD).pack(anchor='w')
        self.intent=self.label(card,'等待游戏连接',17,TEXT,bg=CARD);self.intent.configure(wraplength=680)
        self.intent.pack(anchor='w',pady=(8,8))
        self.strategy=self.label(card,'',10,MUTED,bg=CARD);self.strategy.pack(anchor='w')
        self.army=self.label(card,'',11,TEXT,bg=CARD);self.army.pack(anchor='w',pady=(8,0))
        self.heroes=self.label(card,'',10,MUTED,bg=CARD);self.heroes.configure(wraplength=680)
        self.heroes.pack(anchor='w',pady=(7,0))
        self.label(outer,'最近操作',11,MUTED).pack(anchor='w',pady=(18,8))
        table=tk.Frame(outer,bg=BG);table.pack(fill='both',expand=True)
        self.events=ttk.Treeview(table,columns=('clock','event'),show='headings',height=7)
        self.events.heading('clock',text='游戏时间');self.events.heading('event',text='决策 / 操作记录')
        self.events.column('clock',width=85,stretch=False,anchor='center');self.events.column('event',width=560)
        scrollbar=ttk.Scrollbar(table,orient='vertical',command=self.events.yview)
        self.events.configure(yscrollcommand=scrollbar.set);self.events.pack(side='left',fill='both',expand=True)
        scrollbar.pack(side='right',fill='y')
        self.footer=self.label(outer,'',10,MUTED);self.footer.pack(anchor='w',pady=(12,0))
        self.label(outer,'关闭窗口不停止 AI。面板每秒刷新；决策说明来自最近日志。',9,MUTED).pack(anchor='w',pady=(6,0))
        self.refresh()

    def label(self,parent,text,size,color,bg=BG):
        return tk.Label(parent,text=text,font=('Microsoft YaHei UI',size),fg=color,bg=bg,anchor='w',justify='left')

    def command(self,action):
        try:
            self.send(action,self.current.get('session'))
            self.pending=(action,self.current.get('session'),time.monotonic())
            self.feedback.config(text='请求已发送，正在等待 AI 确认…',fg=AMBER)
        except Exception as exc:self.feedback.config(text=str(exc),fg=AMBER)
        self.render(self.model.poll())

    def render(self,data):
        self.current=data
        self.status.config(text=data['status'],fg=AMBER if data['paused'] or data['stale'] or not data['alive'] else GREEN)
        self.clock.config(text=data['clock'] if data['alive'] else '--:--')
        age=data.get('log_age');fresh='暂无日志' if age is None else f'日志更新于 {int(age)} 秒前'
        self.connection.config(text=(f"当前游戏 · PID {data['pid']}  /  {fresh}" if data['alive'] else '等待 KK 游戏连接 · 下方保留上一局记录'))
        if self.pending:
            action,session,started=self.pending
            if data['session']!=session or not data['alive']:
                self.feedback.config(text='连接已变化，请按当前状态操作。',fg=AMBER);self.pending=None
            elif data['paused']==(action=='pause'):
                self.feedback.config(text='已确认：停止接管，可手动操作。' if action=='pause' else '已确认：AI 继续接管。',fg=GREEN);self.pending=None
            elif time.monotonic()-started>8:
                self.feedback.config(text='尚未收到确认，请检查游戏是否仍运行；可以重试。',fg=AMBER);self.pending=None
        self.pause.config(state='normal' if data['alive'] and not data['paused'] and not self.pending else 'disabled')
        self.resume.config(state='normal' if data['alive'] and data['paused'] and not self.pending else 'disabled')
        prefix='暂停前：' if data['alive'] and data['paused'] else '' if data['alive'] else '上局记录：'
        self.intent.config(text=prefix+data['intent'])
        decision=data['decision'];actual=ACTIONS.get(decision.get('actual'),'等待决策')
        requested=ACTIONS.get(decision.get('requested'),'—')
        self.strategy.config(text=f"战术：{actual}    /    策略建议：{requested}    /    意图采样：{data['summary_clock']}")
        self.army.config(text=f"科技 {decision.get('tier','—')} 本    ·    蜘蛛 {decision.get('fiends','—')} 只")
        self.heroes.config(text='  /  '.join(f'{NAMES.get(h[0],h[0])} Lv.{h[1]} · HP {h[2]}' for h in decision.get('heroes',[])) or '英雄：等待记录')
        rows=list(reversed(data['history']))
        if rows!=self.last_rows:
            at_top=self.events.yview()[0]==0
            self.events.delete(*self.events.get_children())
            for row in rows:self.events.insert('','end',values=row)
            if at_top:self.events.yview_moveto(0)
            self.last_rows=rows
        race={1:'人族',2:'兽族',3:'不死族',4:'暗夜精灵'}.get(data.get('enemy_race'),'未设置')
        self.footer.config(text=f"下局自动接管：{data['automation']}    ·    对手策略：{race}")

    def refresh(self):
        try:self.render(self.model.poll())
        except Exception as exc:self.feedback.config(text='状态读取失败：'+str(exc),fg=AMBER)
        self.window.after(1000,self.refresh)


def main():
    import msvcrt
    from attach_match import atomic_json
    import os
    import psutil
    path=ROOT/'artifacts/console.lock';path.parent.mkdir(exist_ok=True)
    with path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return 0
        try:
            window=tk.Tk();ui=Console(window)
            state_path=ROOT/'artifacts/console.json'
            state=dict(pid=os.getpid(),created=psutil.Process().create_time(),closed=False)
            def report():
                atomic_json(state_path,dict(state,updated=time.time(),display=ui.current))
                window.after(2000,report)
            report();window.mainloop()
            atomic_json(state_path,dict(state,closed=True))
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    return 0


if __name__=='__main__':raise SystemExit(main())
