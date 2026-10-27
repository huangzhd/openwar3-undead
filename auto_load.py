"""Opt-in startup watcher for private KK practice games, using a pinned runtime."""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import psutil

from bootstrap import ROOT, UPSTREAM
from attach_match import atomic_json, identity, compatible_dll, probe, still_same

STATE = ROOT/'artifacts/auto-load.json'
STOP = ROOT/'artifacts/AUTO_LOAD_STOP'
RUNTIME_SHA = '92bb7e6b75e56f91e7eb905844b9a28085e88d4d991a547522c7da8c2907da97'
PLATFORM_EXE = Path(r'C:\Program Files (x86)\kkduizhan\Platform.exe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_runtime():
    dll = UPSTREAM/'prebuilt/render_hook.dll'
    if sha(dll) != RUNTIME_SHA:
        raise RuntimeError('固定运行时的SHA256不匹配；停止加载')
    return dll


def build_helper():
    source = ROOT/'native/RuntimeAttach.cs'
    directory = ROOT/'artifacts/runtime-loader'; directory.mkdir(parents=True, exist_ok=True)
    exe = directory/'RuntimeAttach.exe'; manifest = directory/'build.json'
    if exe.exists() and manifest.exists():
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        if meta.get('source_sha256') == sha(source) and meta.get('exe_sha256') == sha(exe):
            return exe
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    result = subprocess.run([str(compiler), '/nologo', '/platform:x86', '/target:exe',
                             '/out:'+str(exe), str(source)], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
    (directory/'build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('32位加载器编译失败，详见artifacts/runtime-loader/build.log')
    checked = subprocess.run([str(exe), '--self-check'], capture_output=True,
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    if checked.returncode:
        raise RuntimeError('32位加载器运行检查失败')
    atomic_json(manifest, dict(source_sha256=sha(source), exe_sha256=sha(exe),
                              self_check=checked.stdout.decode('utf-8','replace').strip(),
                              runtime_sha256=RUNTIME_SHA))
    return exe


def eligible(row, game_exe, cutoff, parent):
    """Only newly started, configured games directly launched by the known KK exe."""
    return (row['created'] >= cutoff
            and os.path.normcase(row['exe']) == os.path.normcase(str(game_exe))
            and os.path.normcase(parent['exe']) == os.path.normcase(str(PLATFORM_EXE))
            and parent['created'] <= row['created'])


def holder_args(exe, row, dll, stop):
    if not still_same(row): raise RuntimeError('游戏进程身份已变化')
    if not compatible_dll(row): raise RuntimeError('Game.dll与已验证的1.27a不匹配')
    return [str(exe), str(row['pid']), repr(row['created']), row['exe'], str(dll),
            sha(Path(row['exe']).parent/'Game.dll'), str(stop)]


def validate_retry_record(record,game_exe):
    wanted=record['game']
    if record.get('runtime_sha256')!=RUNTIME_SHA or not still_same(wanted):
        raise RuntimeError('重试记录不匹配或原游戏身份无法确认；未执行加载')
    parent=psutil.Process(wanted['pid']).parent()
    parent_row=dict(exe=parent.exe(),created=parent.create_time()) if parent else {}
    if not parent_row or not eligible(wanted,game_exe,0,parent_row):
        raise RuntimeError('重试目标不是配置目录中由KK启动的同一游戏')
    return wanted


def owns_runner(child, state):
    try:
        runner=psutil.Process(state['runner_pid'])
        return (runner.create_time()==state['runner_created']
                and (runner.pid==child.pid or any(p.pid==child.pid for p in runner.parents())))
    except (psutil.Error,KeyError):return False


def stop_owned_bot(row, child):
    from attach_match import STATE as bot_state, COMMAND
    if not bot_state.exists(): return
    state = json.loads(bot_state.read_text(encoding='utf-8'))
    if not state.get('closed') and state.get('process') == row and owns_runner(child,state):
        atomic_json(COMMAND, dict(session=state['session'], action='release'))


def follow_game(row, helper, dll, output, auto_resume, enemy_race, publish, ready_timeout=150):
    # Own this holder only. The helper never launches or terminates the game.
    stop = output/'STOP_HOLDER'; bot = None; holder = None
    with (output/'loader.log').open('wb') as loader_log, (output/'bot.log').open('wb') as bot_log:
        try:
            initial = probe(row['pid'])
            atomic_json(output/'initial-probe.json', initial)
            if initial.get('bridge_state') == 'mapping_absent':
                holder = subprocess.Popen(holder_args(helper,row,dll,stop), cwd=output,
                                          stdin=subprocess.DEVNULL,stdout=loader_log,stderr=subprocess.STDOUT,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
            elif not initial.get('bridge'):
                raise RuntimeError('接口状态不允许加载：'+initial['reason'])
            publish('initializing', game=row, artifacts=str(output))
            deadline=float('inf') if ready_timeout is None else time.monotonic()+ready_timeout
            previous=None
            while time.monotonic()<deadline:
                if STOP.exists() or not still_same(row): return 'stopped_or_game_exited'
                if holder is not None and holder.poll() is not None:
                    raise RuntimeError('加载器已退出，见'+str(output/'loader.log'))
                status=probe(row['pid'])
                signature=(status.get('ready'),status.get('reason'))
                if signature!=previous:
                    atomic_json(output/'latest-probe.json',status); previous=signature
                if status.get('ready'): break
                time.sleep(1)
            else: raise RuntimeError('150秒内游戏接口/对局条件未就绪；不会自动重试加载')
            # A live, advancing fair snapshot is validated again by run_attachment.
            bot=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-u','-B',str(ROOT/'bot.py'),
                                  'attach','--pid',str(row['pid']),'--enemy-race',str(enemy_race)],
                                 cwd=ROOT,stdin=subprocess.DEVNULL,stdout=bot_log,stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            from attach_match import STATE as bot_state, COMMAND
            deadline=time.monotonic()+30; connected=None
            while time.monotonic()<deadline:
                if STOP.exists() or not still_same(row): return 'stopped_or_game_exited'
                if bot.poll() is not None: raise RuntimeError('接管客户端启动失败，见bot.log')
                if bot_state.exists():
                    state=json.loads(bot_state.read_text(encoding='utf-8'))
                    if not state.get('closed') and state.get('process')==row and owns_runner(bot,state):
                        connected=state;break
                time.sleep(.2)
            if connected is None: raise RuntimeError('接管客户端30秒内未确认连接')
            if auto_resume:
                atomic_json(COMMAND,dict(session=connected['session'],action='resume'))
            publish('resume_requested' if auto_resume else 'attached_paused',game=row,artifacts=str(output))
            while still_same(row) and not STOP.exists():
                if holder is not None and holder.poll() is not None:
                    raise RuntimeError('运行时加载助手异常退出')
                if bot is not None and bot.poll() is not None:
                    publish('bot_released',game=row,artifacts=str(output))
                    # Do not restart a bot the user released. Keep its runtime holder
                    # alive until this game ends or the watcher is explicitly stopped.
                    bot=None
                time.sleep(.5)
            return 'stopped' if STOP.exists() else 'game_exited'
        finally:
            if bot is not None and bot.poll() is None:
                stop_owned_bot(row,bot)
                try: bot.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    # No game kill, even on a hung SDK client. Stop only our child.
                    # The venv executable can be a redirector with a Python child.
                    # Capture only its current descendants; never search for game PIDs.
                    try:
                        for p in psutil.Process(bot.pid).children(recursive=True):
                            if p.name().lower() in ('python.exe','pythonw.exe'):p.terminate()
                    except psutil.Error:pass
                    bot.terminate();bot.wait(timeout=5)
            if holder is not None:
                stop.write_text('stop holder only',encoding='utf-8')
                try: holder.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    holder.terminate();holder.wait(timeout=5)


def watch(auto_resume=False, once=True, wait_seconds=1200, enemy_race=0, target_record=None,
          persistent=False, on_lock_wait=None, on_lock_acquired=None):
    # A named local file lock prevents duplicate watcher instances.
    import msvcrt
    cutoff=time.time()  # Include games started while an older watcher still owns the lock.
    lock_path=ROOT/'artifacts/auto-load.lock';lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        while True:
            if persistent and STOP.exists():return dict(result='stopped')
            try:
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError:
                if not persistent:raise RuntimeError('已有自动加载助手在运行')
                if on_lock_wait:on_lock_wait()
                time.sleep(1)
        try:
            if on_lock_acquired:on_lock_acquired()
            dll=verified_runtime();helper=build_helper()
            config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
            game_exe=Path(config['game_dir'])/'War3.exe'
            wanted=None
            if target_record is not None:
                record=json.loads(Path(target_record).read_text(encoding='utf-8'))
                wanted=validate_retry_record(record,game_exe)
                once=True
            if not persistent and STOP.exists():STOP.unlink()
            if persistent:once=False
            end=float('inf') if persistent else time.monotonic()+wait_seconds
            attempted=set()
            state=dict(observer_pid=os.getpid(),observer_created=psutil.Process().create_time(),
                       started=cutoff,closed=False,auto_resume=auto_resume,once=once,
                       persistent=persistent,enemy_race=enemy_race)
            def publish(stage,**fields):
                state.update(stage=stage,updated=time.time(),**fields);atomic_json(STATE,state)
                print(json.dumps(state,ensure_ascii=False),flush=True)
            publish('retrying_recorded_game' if wanted else 'waiting_for_new_kk_game')
            try:
                while time.monotonic()<end and not STOP.exists():
                    for proc in psutil.process_iter(['pid','name']):
                        if (proc.info['name'] or '').lower()!='war3.exe':continue
                        try:
                            row=identity(proc.pid);key=(row['pid'],row['created'])
                            if wanted is not None and row!=wanted:continue
                            parent=proc.parent()
                            if parent is None:continue
                            parent_row=dict(exe=parent.exe(),created=parent.create_time())
                            if key in attempted or not eligible(row,game_exe,0 if wanted else cutoff,parent_row):continue
                        except psutil.Error:continue
                        attempted.add(key)
                        output=ROOT/'artifacts'/('auto-load-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(row['pid']))
                        output.mkdir(exist_ok=False)
                        import shutil
                        frozen={}
                        for name in ('auto_load.py','native/RuntimeAttach.cs','attach_match.py','bridge_diagnostics.py','bot.py'):
                            src=ROOT/name;dest=output/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copy2(src,dest);frozen[name]=sha(src)
                        atomic_json(output/'source-manifest.json',frozen)
                        atomic_json(output/'target.json',dict(game=row,parent=parent_row,runtime_sha256=RUNTIME_SHA))
                        try:
                            result=follow_game(row,helper,dll,output,auto_resume,enemy_race,publish,
                                               ready_timeout=None if persistent else 150)
                        except Exception as exc:
                            result='error';publish('failed',game=row,error=str(exc),artifacts=str(output))
                        atomic_json(output/'result.json',dict(result=result,state=state))
                        if once:return dict(result=result,artifacts=str(output))
                        end=float('inf') if persistent else time.monotonic()+wait_seconds
                        publish('waiting_for_new_kk_game')
                    time.sleep(.25)
                return dict(result='stopped' if STOP.exists() else 'wait_timeout')
            finally:publish('closed',closed=True)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
