"""Persistent selections and single-flight launch/status for the practice panel."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import psutil
from bootstrap import ROOT
from attach_match import atomic_json
from machine_start import active_processes
from practice_video import current_display

MAP_LABELS={'AZ':'AZ · 亚马逊','AL':'AL · 秋叶','CH':'CH · 隐秘谷','LR':'LR · 最后的避难所',
            'NI':'NI · 北方群岛','TH':'TH · 潮汐高地','TR':'TR · 海龟岛','TM':'TM · 扭曲草原'}
RACE_LABELS={1:'人族',2:'兽族',3:'亡灵',4:'暗夜精灵'}


def read_json(path):
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def runner_alive(state):
    try:return psutil.Process(state['runner_pid']).create_time()==state['runner_created']
    except (psutil.NoSuchProcess,KeyError,TypeError):return False
    except psutil.AccessDenied:return True


@contextmanager
def launch_lock(path):
    import msvcrt
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0,2)
        if not stream.tell():stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('正在处理另一个开局请求，请稍候') from None
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


class PracticeModel:
    def __init__(self,root=ROOT):
        self.root=Path(root)
        self.artifacts=self.root/'artifacts'
        self.state_path=self.artifacts/'human-practice-panel.json'
        self.settings_path=self.artifacts/'human-practice-settings.json'

    def settings(self):
        value=read_json(self.settings_path)
        return dict(map_alias=value.get('map_alias') if value.get('map_alias') in MAP_LABELS else 'LR',
                    human_race=value.get('human_race') if value.get('human_race') in RACE_LABELS else 2)

    def poll(self):
        state=read_json(self.state_path)
        phase=state.get('phase','idle')
        alive=runner_alive(state)
        active=active_processes()
        pending=phase=='launching' and not state.get('launch_ready') and time.time()-state.get('updated',0)<10
        busy=alive or bool(active) or pending
        error=state.get('error','')
        if phase in ('launching','running') and not busy:
            phase='error';error=error or '练习进程已退出，请重新开始'
        status={'idle':'准备就绪','launching':'正在启动游戏，请稍候…','running':'练习进行中',
                'finished':'本局已结束，可以开始下一局','error':'练习未完成'}.get(phase,'准备就绪')
        if phase=='running' and state.get('background'):status='游戏在后台 · 切回游戏后继续'
        if active and not alive and not pending:status='已有游戏运行，请先退出当前游戏'
        result=state.get('result')
        if phase=='finished' and result:
            if result.get('result')=='win':status='本局结束 · dayuan 获胜'
            elif result.get('result')=='loss':status='本局结束 · 你获胜'
        try:
            mode=current_display()
            display=f"{mode['width']} × {mode['height']} · 32 位色"
        except Exception as exc:
            display='无法读取显示器分辨率';error=error or str(exc)
        return dict(settings=self.settings(),phase=phase,busy=busy,can_start=not busy,status=status,
                    error=error,display=display,clock=state.get('clock'),result=result)

    def start(self,map_alias,human_race):
        if map_alias not in MAP_LABELS or human_race not in RACE_LABELS:
            raise ValueError('请选择支持的地图和种族')
        with launch_lock(self.artifacts/'human-practice-launch.lock'):
            current=self.poll()
            if not current['can_start']:raise RuntimeError(current['status'])
            from human_practice import source_files
            from undead.maps import resolve_map
            source_files();resolve_map(map_alias);current_display()
            token=uuid4().hex
            settings=dict(map_alias=map_alias,human_race=human_race)
            atomic_json(self.settings_path,settings)
            state=dict(token=token,phase='launching',launch_ready=False,settings=settings,updated=time.time())
            atomic_json(self.state_path,state)
            log=self.artifacts/f'human-practice-{token}.log'
            try:
                with log.open('w',encoding='utf-8') as stream:
                    child=subprocess.Popen([str(self.root/'.venv/Scripts/python.exe'),'-X','utf8','-B',
                        str(self.root/'practice_control.py'),'--run',token,'--race',str(human_race),'--map',map_alias],
                        cwd=self.root,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                state.update(runner_pid=child.pid,runner_created=psutil.Process(child.pid).create_time(),
                             launch_ready=True,log=str(log),updated=time.time())
                atomic_json(self.state_path,state)
                return state
            except Exception as exc:
                state.update(phase='error',error=str(exc),updated=time.time())
                atomic_json(self.state_path,state)
                raise


def run_worker(token,human_race,map_alias):
    model=PracticeModel()
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=read_json(model.state_path)
        if state.get('token')!=token:raise RuntimeError('练习启动请求已变化')
        if state.get('launch_ready'):break
        time.sleep(.05)
    else:raise RuntimeError('练习启动登记超时')
    process=psutil.Process()
    state.update(runner_pid=process.pid,runner_created=process.create_time())
    def update(phase,**data):
        current=read_json(model.state_path)
        if current.get('token')!=token:return False
        state.update(phase=phase,updated=time.time(),**data)
        atomic_json(model.state_path,state)
        return True
    try:
        if active_processes():raise RuntimeError('已有游戏运行，未开启新局')
        stop=ROOT/'artifacts/STOP'
        if stop.exists():stop.unlink()
        if not update('launching'):raise RuntimeError('练习启动请求已变化，未开启新局')
        from run_match import run_match
        result=run_match(speed=100,enemy_race=human_race,difficulty=2,map_alias=map_alias,
                         human_practice=True,practice_status=update)
        update('error' if result['result']=='error' else 'finished',result=result,
               error=result['reason'] if result['result']=='error' else '',background=False)
        return 1 if result['result']=='error' else 0
    except Exception as exc:
        update('error',error=str(exc))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',required=True)
    parser.add_argument('--race',type=int,choices=tuple(RACE_LABELS),required=True)
    parser.add_argument('--map',dest='map_alias',choices=tuple(MAP_LABELS),required=True)
    args=parser.parse_args()
    raise SystemExit(run_worker(args.run,args.race,args.map_alias))
