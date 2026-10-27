"""Read-only dashboard model and session-bound pause/resume requests."""
from collections import deque
import json
from pathlib import Path
import time

import psutil
from bootstrap import ROOT
from attach_match import atomic_json, still_same

ACTIONS = {'CREEP':'练级','ATTACK':'进攻','HARASS':'骚扰分矿','DEFEND':'回防基地','RETREAT':'撤退'}
NAMES = {'uaco':'侍僧','ugho':'食尸鬼','ucry':'地穴恶魔','uobs':'雕像','Udea':'死亡骑士',
         'Ulic':'巫妖','Nbrn':'黑暗游侠','uaod':'黑暗祭坛','uzig':'通灵塔','uzg1':'幽魂之塔',
         'uzg2':'蛛网怪塔','usep':'地穴','ugrv':'坟场','uslh':'屠宰场','utom':'古墓废墟',
         'unpl':'大墓地','unp1':'亡者大厅','unp2':'黑色城堡','ocor':'腐蚀之球','rnec':'骷髅棒'}


def read_json(path):
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def clock_text(value):
    value=max(0,int(value or 0))
    return f'{value//60:02d}:{value%60:02d}'


def session_alive(state):
    if not state or state.get('closed'):return False
    try:
        return (psutil.Process(state['runner_pid']).create_time()==state['runner_created']
                and still_same(state['process']))
    except (psutil.Error,KeyError,TypeError):return False


def request_control(action, expected_session, root=ROOT):
    if action not in ('pause','resume','surrender'):raise ValueError('未知的接管控制命令')
    state=read_json(root/'artifacts/attachment.json')
    if not expected_session or state.get('session')!=expected_session:
        raise RuntimeError('对局已变化，请等待面板刷新后重试')
    if not session_alive(state):raise RuntimeError('当前没有可控制的接管连接')
    if action=='surrender' and 'surrender' not in state.get('control_capabilities',[]):
        raise RuntimeError('当前接管进程不支持面板认输，请在下一局使用新版接管')
    if state.get('surrender',{}).get('stage') in ('new','waiting_gg','exiting'):
        raise RuntimeError('认输正在处理中，请等待结果')
    # A subsequent game ignores this old token, even if it starts during this write.
    command=dict(session=expected_session,action=action)
    if action=='surrender':
        from uuid import uuid4
        command['request_id']=uuid4().hex
    atomic_json(root/'artifacts/attachment-command.json',command)
    return command


class EventTail:
    def __init__(self):
        self.path=None;self.offset=0;self.pending=b''

    def read(self,path):
        try:
            size=path.stat().st_size
            initial=path!=self.path or size<self.offset
            if initial:
                self.path=path;self.offset=max(0,size-262144);self.pending=b''
            with path.open('rb') as stream:
                stream.seek(self.offset);chunk=stream.read(262144);self.offset=stream.tell()
            if initial and self.offset-len(chunk)>0:
                chunk=chunk.split(b'\n',1)[1] if b'\n' in chunk else b''
            lines=(self.pending+chunk).split(b'\n');self.pending=lines.pop()
            out=[]
            for line in lines:
                try:
                    event=json.loads(line.decode('utf-8'))
                    if isinstance(event,dict):out.append(event)
                except (ValueError,UnicodeError):pass
            return out
        except OSError:return []


def describe(event):
    kind=event.get('event');code=event.get('code','');name=NAMES.get(code,code)
    if kind=='purchase':
        verb={'build':'建造','train':'训练','upgrade':'升级','research':'研究'}.get(event.get('kind'),'购买')
        return verb+name+(' · 指令未接受' if event.get('accepted') is False else ' · 已下达指令')
    if kind=='new_units':return '观察到新增类型：'+'、'.join(NAMES.get(x,x) for x in event.get('types',[]))
    if kind=='decision':return '战术选择：'+ACTIONS.get(event.get('actual'),str(event.get('actual')))
    if kind=='attachment_summary':return event.get('intent','')
    return {'attachment_paused':'已停止接管，交还手动操作','attachment_resumed':'AI 已继续接管',
            'attack_phase_started':'进攻条件满足，进入进攻阶段','teleport_confirmed':'已确认回城',
            'teleport_attempt':'尝试紧急回城','dk_rejoined':'死亡骑士归队',
            'enemy_air_sighted':'发现敌方空军','burrow_target_deferred':'暂时忽略埋地目标',
            'pullback_verified':'已观察到受伤单位成功拉开距离'}.get(kind)


class DashboardModel:
    def __init__(self,root=ROOT):
        self.root=root;self.session=None;self.tail=EventTail();self.history=deque(maxlen=70)
        self.decision={};self.intent='等待决策';self.clock=0;self.summary_clock=0

    def poll(self):
        state=read_json(self.root/'artifacts/attachment.json')
        if state.get('session')!=self.session:
            self.session=state.get('session');self.tail=EventTail();self.history.clear()
            self.decision={};self.intent='等待决策';self.clock=0;self.summary_clock=0
        logpath=None
        if state.get('artifacts'):
            candidate=Path(state['artifacts']).resolve()
            if candidate.is_relative_to((self.root/'artifacts').resolve()):logpath=candidate/'events.jsonl'
        if logpath:
            for event in self.tail.read(logpath):
                self.clock=max(self.clock,event.get('clock',0))
                if event.get('event')=='decision':self.decision=event
                if event.get('event')=='attachment_summary':
                    self.intent=event.get('intent','等待决策');self.summary_clock=event.get('clock',0)
                message=describe(event)
                if message and (not self.history or self.history[-1][1]!=message):
                    self.history.append((clock_text(event.get('clock')),message))
        alive=session_alive(state)
        paused=bool(state.get('paused',True))
        if alive:status='已停止接管 · 可手动操作' if paused else 'AI 正在接管'
        else:status='当前未连接游戏'
        age=None
        if logpath:
            try:age=max(0,time.time()-logpath.stat().st_mtime)
            except OSError:pass
        heartbeat=state.get('updated')
        heartbeat_age=max(0,time.time()-heartbeat) if isinstance(heartbeat,(int,float)) else age
        stale=alive and (heartbeat_age is None or heartbeat_age>5) if heartbeat is not None else alive and not paused and (age is None or age>25)
        if stale:status='连接存在 · 等待状态更新'
        config=read_json(self.root/'artifacts/auto-takeover-config.json')
        watcher=read_json(self.root/'artifacts/auto-load.json')
        service=read_json(self.root/'artifacts/auto-takeover-service.json')
        enabled=config.get('enabled',False)
        listener=False
        try:listener=not service.get('closed',True) and psutil.Process(service['pid']).create_time()==service['created']
        except (psutil.Error,KeyError,TypeError):pass
        automation=('已启用 · 后台待命' if listener else '已启用 · 后台未运行') if enabled else '已停用'
        try:
            if not watcher.get('closed',True) and psutil.Process(watcher['observer_pid']).create_time()==watcher['observer_created']:
                automation='单局监听运行中' if watcher.get('once') else '连续监听运行中'
        except (psutil.Error,KeyError,TypeError):pass
        detail=watcher.get('error','') if watcher.get('stage')=='failed' else ''
        surrender=state.get('surrender',{})
        if alive and surrender.get('stage') in ('new','waiting_gg','exiting'):status=surrender.get('message','正在认输')
        return dict(session=self.session,alive=alive,paused=paused,stale=stale,status=status,
                    clock=clock_text(state.get('clock',self.clock)),intent=self.intent,summary_clock=clock_text(self.summary_clock),
                    decision=self.decision,history=list(self.history),automation=automation,error=detail,
                    log_age=heartbeat_age,pid=state.get('process',{}).get('pid'),enemy_race=state.get('opponent',{}).get('race',0),
                    opponent=state.get('opponent',{}),map=state.get('map',{}),version=state.get('bot_name'),
                    manual_skill_learning=state.get('manual_skill_learning',False),
                    skill_requests=state.get('skill_requests',[]),
                    apm=state.get('apm') if alive and not paused and not stale else None,
                    average_apm=state.get('average_apm'),surrender=surrender,
                    can_surrender=alive and not stale and 'surrender' in state.get('control_capabilities',[]))
