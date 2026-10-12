"""Attach to an existing OpenWar3AI bridge; never inject, launch or end a game."""
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
import psutil
from bootstrap import ROOT,UPSTREAM

STATE=ROOT/'artifacts/attachment.json'
COMMAND=ROOT/'artifacts/attachment-command.json'


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def identity(pid):
    p=psutil.Process(pid)
    if not re.fullmatch(r'(war3(?:-\d+)?|warcraft iii)\.exe',p.name(),re.I):
        raise RuntimeError('指定进程不是已识别的 Warcraft III 游戏进程')
    return dict(pid=pid,created=p.create_time(),name=p.name(),exe=p.exe())


def still_same(row):
    try:return identity(row['pid'])==row
    except (psutil.Error,RuntimeError):return False


def compatible_dll(row):
    config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
    known=Path(config['game_dir'])/'Game.dll'
    actual=Path(row['exe']).parent/'Game.dll'
    return known.is_file() and actual.is_file() and hashlib.sha256(known.read_bytes()).digest()==hashlib.sha256(actual.read_bytes()).digest()


def validate_snapshot(s):
    if s is None or not s.in_game or s.clock<=0:raise RuntimeError('请先进入对局，不能接管大厅或载入界面')
    if not 0<=s.me<12:raise RuntimeError('本机没有有效玩家槽位，不能接管观战者')
    own=[u for u in s.units if u.owner==s.me and u.alive]
    if not any(u.type in {'uaco','unpl','unp1','unp2','Udea','Ulic'} for u in own):
        raise RuntimeError('仅支持本机玩家使用不死族且仍有可接管单位')
    if s.speed_pct!=100:raise RuntimeError('接管仅支持正常100%倍率，请在开局前设置；工具不会修改游戏速度')
    return dict(player=s.me,epoch=s.epoch,clock=s.clock,own_types=sorted({u.type for u in own}))


def probe(pid):
    row=identity(pid)
    result=dict(process=row,ready=False,bridge=False)
    if not compatible_dll(row):
        return dict(result,reason='Game.dll与已验证的本机1.27a不一致；此版本不支持')
    import w3world
    world=None
    try:
        world=w3world.World(pid)
        result['bridge']=True
        result.update(validate_snapshot(world.read()))
        mp=world.map()
        if mp is None:raise RuntimeError('地图接口未就绪，请稍后重新检测')
        starts=[tuple(p) for p in mp.starts if tuple(p)!=(0,0)]
        if len(set(starts))!=2:raise RuntimeError('当前接管策略仅支持双出生点1v1近战地图')
        if not still_same(row):raise RuntimeError('检测期间游戏进程发生变化')
        result.update(ready=True,reason='接口已就绪；联机命令同步仍需实测')
    except w3world.WorldUnavailable as exc:
        from bridge_diagnostics import diagnose_unavailable
        result.update(diagnose_unavailable(pid,str(exc)))
        result['detail']=str(exc)
        if not still_same(row):
            result.update(bridge_state='process_changed',reason='检测期间原游戏进程已退出或发生变化。',
                          next_step='当前结果不能代表新进程；不要继续使用旧 PID。')
    except Exception as exc:result['reason']=str(exc)
    finally:
        if world is not None:world.close()
    return result


def candidates():
    out=[]
    for p in psutil.process_iter(['pid','name']):
        if re.fullmatch(r'(war3(?:-\d+)?|warcraft iii)\.exe',p.info['name'] or '',re.I):
            try:out.append(probe(p.pid))
            except Exception as exc:out.append(dict(pid=p.pid,ready=False,reason=str(exc)))
    return out


class RunnerLock:
    def __enter__(self):
        import msvcrt
        path=ROOT/'artifacts/attachment.lock';path.parent.mkdir(parents=True,exist_ok=True)
        self.file=path.open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            self.file.close();raise RuntimeError('已有接管进程运行，请先释放它')
        return self
    def __exit__(self,*exc):
        import msvcrt
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close()


def control(action):
    if action not in ('pause','resume','release'):raise ValueError(action)
    state=json.loads(STATE.read_text(encoding='utf-8'))
    if state.get('closed'):raise RuntimeError('当前没有运行中的接管会话')
    p=psutil.Process(state['runner_pid'])
    if p.create_time()!=state['runner_created']:raise RuntimeError('接管进程已结束或PID被复用')
    atomic_json(COMMAND,dict(session=state['session'],action=action))
    return dict(requested=action,session=state['session'])


def make_controller(g,log,enemy_race):
    from undead.controller import Controller
    b=Controller(g,log,enemy_race)
    # The launch configuration's default map is NOT evidence of the live map.
    b.creeping.catalog=[];b.critter_search.spawns=[]
    heroes=g.my_heroes()
    b.economy.ever_heroes.update(h.type for h in heroes)
    if hasattr(g,'units'):
        b.economy.ever_heroes.update(u.type for u in g.units('me',alive=False) if u.is_hero)
    b.tavern_seen.update(h.handle for h in heroes if h.type==b.third_hero)
    return b


def release_claims(g):
    # Releasing leases leaves current game orders intact for the human to replace.
    for u in g.my_units():g.claims.give_back(u.addr)


class Attachment:
    def __init__(self,g,metadata,enemy_race,log,controller_factory=make_controller):
        self.g=g;self.meta=metadata;self.enemy_race=enemy_race;self.log=log
        self.factory=controller_factory;self.bot=None;self.paused=True;self.last_clock=None
        self.ever_heroes=set()
        self.last_publish=None;self.published=time.monotonic();self.last_summary=-100

    def step(self,action,wall=None):
        wall=time.monotonic() if wall is None else wall
        if action=='release':return 'released_by_user'
        raw=self.g.world.read() # Only local player / epoch metadata is inspected here.
        if raw is None:raise RuntimeError('接管快照不可用')
        if not raw.in_game:return 'game_left'
        if raw.epoch!=self.meta['epoch'] or raw.me!=self.meta['player']:return 'match_or_player_changed'
        s=self.g.snapshot(max_age=0)
        if s is None:raise RuntimeError('公平快照不可用')
        if s.clock<(self.last_clock if self.last_clock is not None else self.meta['clock']):return 'clock_reset'
        if s.speed_pct!=100:return 'speed_changed'
        if s.publish_count!=self.last_publish:self.last_publish=s.publish_count;self.published=wall
        elif wall-self.published>10:raise RuntimeError('世界快照停止更新，已停止接管')
        events=self.g.events()
        if any(e.kind=='game.ended' or (e.kind=='player.left' and getattr(e,'player',None)==s.me) for e in events):return 'game_or_local_player_left'
        if action=='pause' and not self.paused:
            if hasattr(self.bot,'economy'):self.ever_heroes.update(self.bot.economy.ever_heroes)
            self.paused=True;self.bot=None;release_claims(self.g)
            self.log('attachment_paused',clock=s.clock)
        if action=='resume' and self.paused:
            validate_snapshot(s)
            self.bot=self.factory(self.g,self.log,self.enemy_race)
            if hasattr(self.bot,'economy'):self.bot.economy.ever_heroes.update(self.ever_heroes)
            self.paused=False;self.last_clock=None
            self.log('attachment_resumed',clock=s.clock)
        if not self.paused and s.clock!=self.last_clock:
            self.bot.observe_events(events);self.bot.tick()
            if s.clock-self.last_summary>=15:
                self.last_summary=s.clock
                self.log('attachment_summary',clock=s.clock,player=s.me,intent=self.bot.intent)
        self.last_clock=s.clock
        return None


def run_attachment(pid,enemy_race=3):
    from undead.game_view import Game
    with RunnerLock():
        metadata=probe(pid)
        if not metadata['ready']:raise RuntimeError(metadata['reason'])
        # A local runner may own the same process; do not compete with it.
        local=ROOT/'artifacts/session.json'
        if local.exists() and any(r['pid']==pid for r in json.loads(local.read_text(encoding='utf-8')).get('processes',[])):
            raise RuntimeError('此游戏由本项目单机运行器控制，不能重复接管')
        token=uuid.uuid4().hex
        out=ROOT/'artifacts'/('attach-'+time.strftime('%Y%m%d-%H%M%S')+'-'+token[:6]);out.mkdir(parents=True)
        import shutil
        manifest={}
        for path in [ROOT/'attach_match.py',ROOT/'bridge_diagnostics.py',ROOT/'bot.py',*sorted((ROOT/'undead').glob('*.py'))]:
            name=path.relative_to(ROOT).as_posix();dest=out/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,dest);manifest[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_json(out/'source-manifest.json',manifest)
        state=dict(session=token,runner_pid=os.getpid(),runner_created=psutil.Process().create_time(),
                   process=metadata['process'],player=metadata['player'],epoch=metadata['epoch'],closed=False,paused=True,artifacts=str(out))
        result=dict(version='0.1.60-dev',rules_version='0.1.54',mode='attach',metadata=metadata,result='detached')
        g=None;started=time.monotonic()
        with (out/'events.jsonl').open('w',encoding='utf-8') as stream:
            def log(event,**data):
                line=json.dumps(dict(event=event,**data),ensure_ascii=False)
                stream.write(line+'\n');stream.flush()
                if event.startswith('attachment_'):print(line,flush=True)
            try:
                g=Game(pid=pid,player=metadata['player'],fair=True)
                loop=Attachment(g,metadata,enemy_race,log)
                atomic_json(COMMAND,dict(session=token,action='pause'));atomic_json(STATE,state)
                log('attachment_ready',**state)
                print('已连接，初始暂停。另开终端执行 bot.py attach-resume 开始，attach-pause 暂停，attach-release 释放。',flush=True)
                while True:
                    if not still_same(metadata['process']):result['reason']='process_exited_or_changed';break
                    try:command=json.loads(COMMAND.read_text(encoding='utf-8'))
                    except (OSError,ValueError):command={}
                    action=command.get('action','pause') if command.get('session')==token else 'pause'
                    if action not in ('pause','resume','release'):action='pause'
                    reason=loop.step(action)
                    if state['paused']!=loop.paused:
                        state['paused']=loop.paused;atomic_json(STATE,state)
                    if reason:result['reason']=reason;break
                    time.sleep(.2)
            except KeyboardInterrupt:result['reason']='keyboard_interrupt'
            except Exception as exc:result.update(result='error',reason=repr(exc))
            finally:
                if g is not None:
                    try:release_claims(g)
                    except Exception as exc:result['lease_release_error']=repr(exc)
                    try:g.close()
                    except Exception as exc:result['client_close_error']=repr(exc)
                state.update(closed=True,paused=True);atomic_json(STATE,state)
                result['wall_seconds']=round(time.monotonic()-started,2)
                atomic_json(out/'result.json',result)
        return result
