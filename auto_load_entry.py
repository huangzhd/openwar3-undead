"""User-invoked launcher with the normal Windows administrator consent prompt."""
import argparse
import contextlib
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parent


def elevation_args(arguments):
    return subprocess.list2cmdline(['-u','-B',str(ROOT/'auto_load_entry.py'),*arguments])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auto-resume',action='store_true')
    parser.add_argument('--watch-restarts',action='store_true')
    parser.add_argument('--enemy-race',type=int,choices=(1,2,3,4),default=3)
    args=parser.parse_args()
    if not ctypes.windll.shell32.IsUserAnAdmin():
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteW.argtypes=[wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,
                                    wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_int]
        shell.ShellExecuteW.restype=ctypes.c_void_p
        # SW_HIDE hides only the helper console; Windows still owns the UAC prompt.
        result=shell.ShellExecuteW(None,'runas',str(ROOT/'.venv/Scripts/python.exe'),
                                  elevation_args(sys.argv[1:]),str(ROOT),0)
        if not result or result<=32:
            print('Administrator launch was not approved or failed; no game was loaded.')
            return 1
        print('Administrator launcher dispatched. Read bot.py auto-load-status for actual readiness.')
        return 0
    os.chdir(ROOT);os.environ['PYTHONIOENCODING']='utf-8'
    directory=ROOT/'artifacts';directory.mkdir(exist_ok=True)
    path=directory/('auto-load-elevated-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    with path.open('w',encoding='utf-8',buffering=1) as log:
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            print(json.dumps(dict(administrator=True,auto_resume=args.auto_resume,once=not args.watch_restarts)),flush=True)
            try:
                from auto_load import watch
                result=watch(args.auto_resume,not args.watch_restarts,enemy_race=args.enemy_race)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                return 1 if result.get('result')=='error' else 0
            except Exception:
                traceback.print_exc();return 1


if __name__=='__main__':raise SystemExit(main())
