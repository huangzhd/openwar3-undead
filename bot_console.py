"""Native desktop status panel. Reads logs; buttons use the existing session command channel."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk

from bootstrap import ROOT
from console_state import DashboardModel, request_control

BG='#eef2f7';TEXT='#1e293b';MUTED='#64748b';GREEN='#15803d';AMBER='#92400e';RED='#d94141'


class Console:
    def __init__(self,window,model=None,send=request_control):
        self.window=window;self.model=model or DashboardModel();self.send=send
        self.current={};self.pending=None;self.pending_id=None
        window.title('dayuan KK 对战控制面板');window.geometry('550x420')
        window.resizable(False,False);window.attributes('-topmost',True)
        window.configure(bg=BG)
        outer=tk.Frame(window,bg=BG,padx=22,pady=14);outer.pack(fill='both',expand=True)
        self.status=self.label(outer,'读取状态…',12,TEXT)
        self.status.configure(font=('Microsoft YaHei UI',12,'bold'));self.status.pack(pady=(0,5))
        metrics=tk.Frame(outer,bg=BG);metrics.pack(pady=3)
        self.clock=self.label(metrics,'时间 --:--',11,TEXT);self.clock.pack(side='left',padx=8)
        self.apm=self.label(metrics,'APM —',11,TEXT);self.apm.pack(side='left',padx=8)
        self.average=self.label(metrics,'局均 —',11,TEXT);self.average.pack(side='left',padx=8)
        self.label(outer,'APM：最近 60 游戏秒 bot 已接受的操作，不含人工操作',9,MUTED).pack()
        self.connection=self.label(outer,'',9,MUTED);self.connection.pack(pady=(6,9))
        self.map_name=self.label(outer,'地图 · 等待识别',11,TEXT)
        self.map_name.configure(wraplength=490);self.map_name.pack(pady=3)
        self.map_detail=self.label(outer,'',9,MUTED)
        self.map_detail.configure(wraplength=490);self.map_detail.pack(pady=1)
        self.opponent=self.label(outer,'对方种族 · 等待识别',11,TEXT);self.opponent.pack(pady=(6,10))
        buttons=tk.Frame(outer,bg=BG);buttons.pack(pady=(4,8))
        self.toggle=tk.Button(buttons,text='人工接管',width=16,command=self.toggle_control,
                              font=('Microsoft YaHei UI',11),bg=GREEN,fg='white',
                              activebackground='#166534',activeforeground='white',disabledforeground='white')
        self.toggle.pack(side='left',padx=6,ipady=4)
        self.surrender=tk.Button(buttons,text='认输',width=16,command=lambda:self.command('surrender'),
                                 font=('Microsoft YaHei UI',11),bg=RED,fg='white',
                                 activebackground='#b91c1c',activeforeground='white',disabledforeground='white')
        self.surrender.pack(side='left',padx=6,ipady=4)
        self.feedback=self.label(outer,'人工接管后 bot 停止下令；认输会发送 gg 后退出游戏。',10,TEXT)
        self.feedback.configure(wraplength=490);self.feedback.pack(pady=4)
        self.note=self.label(outer,'关闭面板不会停止 bot；已有的游戏指令会保留。',9,MUTED)
        self.note.pack(side='bottom',pady=(4,0))
        self.footer=self.label(outer,'',9,MUTED)
        self.footer.configure(wraplength=490);self.footer.pack(side='bottom')
        self.refresh()

    def toggle_control(self):
        self.command('resume' if self.current.get('paused',True) else 'pause')

    def label(self,parent,text,size,color,bg=BG):
        return tk.Label(parent,text=text,font=('Microsoft YaHei UI',size),fg=color,bg=bg,anchor='w',justify='left')

    def command(self,action):
        try:
            response=self.send(action,self.current.get('session')) or {}
            self.pending_id=response.get('request_id')
            self.pending=(action,self.current.get('session'),time.monotonic())
            self.feedback.config(text='请求已发送，正在等待 AI 确认…',fg=AMBER)
        except Exception as exc:self.feedback.config(text=str(exc),fg=AMBER)
        self.render(self.model.poll())

    def render(self,data):
        self.current=data
        self.status.config(text=data['status'],fg=AMBER if data['paused'] or data['stale'] or not data['alive'] else GREEN)
        self.clock.config(text='时间 '+(data['clock'] if data['alive'] else '--:--'))
        age=data.get('log_age');fresh='暂无日志' if age is None else f'日志更新于 {int(age)} 秒前'
        self.connection.config(text=(f"当前游戏 · PID {data['pid']}  /  {fresh}" if data['alive'] else '等待 KK 游戏连接'))
        if self.pending:
            action,session,started=self.pending
            outcome=data.get('surrender',{})
            if action=='surrender' and outcome.get('request_id')!=self.pending_id:outcome={}
            if action=='surrender' and outcome.get('stage') in ('finished','failed'):
                self.feedback.config(text=outcome.get('message',''),fg=GREEN if outcome['stage']=='finished' else AMBER);self.pending=None
            elif data['session']!=session or not data['alive']:
                self.feedback.config(text='连接已变化，请按当前状态操作。',fg=AMBER);self.pending=None
            elif action!='surrender' and data['paused']==(action=='pause'):
                self.feedback.config(text='已确认：停止接管，可手动操作。' if action=='pause' else '已确认：AI 继续接管。',fg=GREEN);self.pending=None
            elif action=='surrender' and outcome.get('stage') in ('new','waiting_gg','exiting'):
                self.feedback.config(text=outcome.get('message','正在认输…'),fg=AMBER)
                if time.monotonic()-started>18:
                    self.feedback.config(text='认输确认超时，请检查当前游戏；未确认退出。',fg=AMBER);self.pending=None
            elif time.monotonic()-started>8:
                self.feedback.config(text='尚未收到确认，请检查游戏是否仍运行；可以重试。',fg=AMBER);self.pending=None
        busy=data.get('surrender',{}).get('stage') in ('new','waiting_gg','exiting')
        can_toggle=data['alive'] and not data['stale'] and not self.pending and not busy
        can_surrender=data.get('can_surrender') and not self.pending and not busy
        self.toggle.config(text='恢复自动控制' if data['alive'] and data['paused'] else '人工接管',
                           bg=GREEN if can_toggle else '#94a3b8',
                           state='normal' if can_toggle else 'disabled')
        self.surrender.config(bg=RED if can_surrender else '#94a3b8',state='normal' if can_surrender else 'disabled')
        self.apm.config(text='APM '+(str(data['apm']) if data.get('apm') is not None else '—'))
        self.average.config(text='局均 '+str(data.get('average_apm') if data.get('average_apm') is not None else '—'))
        mp=data.get('map',{});verified=mp.get('status')=='verified'
        prior='' if data['alive'] else '上局 · '
        self.map_name.config(text=prior+'地图 · '+(f"{mp.get('alias','')} / {mp.get('name','')}" if verified else '未识别'))
        reasons={'map_file_unavailable':'未获取到游戏打开的地图文件','unknown_map_fingerprint':'地图文件尚未收录',
                 'ambiguous_map_files':'游戏打开了多份地图，无法唯一确认','live_starts_mismatch':'地图出生点校验不一致',
                 'map_read_failed':'地图文件读取失败'}
        self.map_detail.config(text=('哈希与出生点已校验 · '+mp.get('sha256','')[:12]) if verified else
                               reasons.get(mp.get('reason'),'等待新接管进程识别地图'))
        race={1:'人族',2:'兽族',3:'不死族',4:'暗夜精灵'}.get(data.get('enemy_race'),'未知 · 等待发现敌军' if data['alive'] else '未记录')
        basis={'player_setup':'对局设置','visible_enemy':'可见敌军','explicit_fallback':'手工备用设置'}.get(data.get('opponent',{}).get('race_basis'),'')
        self.opponent.config(text=f'对方种族 · {race}'+(f'  /  {basis}' if basis else ''))
        from undead.version import DISPLAY_NAME
        self.footer.config(text=f"监听：{data['automation']}  ·  bot：{data.get('version') or '未记录'}\n面板 {DISPLAY_NAME}")

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
