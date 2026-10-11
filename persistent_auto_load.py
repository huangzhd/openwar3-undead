"""Login-started KK practice watcher; normal Task Scheduler privileges, no UAC bypass."""
import contextlib
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT/'artifacts/auto-takeover-config.json'
STATE = ROOT/'artifacts/auto-takeover-service.json'


def configuration():
    value = json.loads(CONFIG.read_text(encoding='utf-8'))
    if type(value.get('enabled')) is not bool or value.get('enemy_race') not in (1, 2, 3, 4):
        raise ValueError('Invalid automatic takeover configuration')
    return value


def disable():
    from attach_match import atomic_json
    from auto_load import STOP
    value = configuration()
    value['enabled'] = False
    atomic_json(CONFIG, value)
    STOP.write_text('User disabled automatic takeover', encoding='utf-8')


def main():
    if sys.argv[1:] == ['--disable']:
        disable()
        print('Automatic takeover disabled; game remains open.')
        return 0
    os.chdir(ROOT)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    from attach_match import atomic_json
    import psutil
    state = dict(pid=os.getpid(), created=psutil.Process().create_time(), closed=False)
    def publish(stage, **fields):
        state.update(stage=stage, updated=time.time(), **fields)
        atomic_json(STATE, state)
    logpath = ROOT/'artifacts'/('auto-takeover-service-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    logpath.parent.mkdir(parents=True, exist_ok=True)
    with logpath.open('w', encoding='utf-8', buffering=1) as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                config = configuration()
                if not config['enabled']:
                    publish('disabled', closed=True)
                    return 0
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    raise RuntimeError('Task must run with its registered highest privileges')
                from auto_load import watch
                publish('starting', enemy_race=config['enemy_race'], log=str(logpath))
                def waiting():
                    if state.get('stage') != 'waiting_for_previous_watcher':
                        publish('waiting_for_previous_watcher')
                result = watch(auto_resume=True, once=False, enemy_race=config['enemy_race'],
                               persistent=True, on_lock_wait=waiting,
                               on_lock_acquired=lambda:publish('watching'))
                publish('closed', closed=True, result=result)
                return 0
            except Exception:
                traceback.print_exc()
                publish('failed', closed=True)
                return 1


if __name__ == '__main__':
    raise SystemExit(main())
