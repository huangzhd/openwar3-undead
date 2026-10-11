"""Register the user's explicitly requested login watcher via standard Windows UAC."""
import csv
import ctypes
from ctypes import wintypes
import io
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
TASK = 'OpenWar3AI-KK-AutoTakeover-38993'
NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'


def task_xml(sid):
    ET.register_namespace('', NS)
    root = ET.Element('{'+NS+'}Task', version='1.4')
    def node(parent, name, value=None, **attrs):
        item = ET.SubElement(parent, '{'+NS+'}'+name, attrs)
        if value is not None:item.text = value
        return item
    registration = node(root, 'RegistrationInfo')
    node(registration, 'Description', 'OpenWar3AI: automatically take over configured KK 1v1 Undead practice games. Disable with auto-takeover-stop.cmd.')
    trigger = node(node(root, 'Triggers'), 'LogonTrigger')
    node(trigger, 'Enabled', 'true');node(trigger, 'UserId', sid)
    principal = node(node(root, 'Principals'), 'Principal', id='Author')
    node(principal, 'UserId', sid);node(principal, 'LogonType', 'InteractiveToken')
    node(principal, 'RunLevel', 'HighestAvailable')
    settings = node(root, 'Settings')
    for key, value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                       ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),
                       ('StartWhenAvailable','true'),('RunOnlyIfNetworkAvailable','false'),
                       ('Enabled','true'),('Hidden','false'),('ExecutionTimeLimit','PT0S'),('Priority','7')]:
        node(settings, key, value)
    restart = node(settings, 'RestartOnFailure')
    node(restart, 'Interval', 'PT1M');node(restart, 'Count', '3')
    action = node(node(root, 'Actions', Context='Author'), 'Exec')
    node(action, 'Command', str(ROOT/'.venv/Scripts/pythonw.exe'))
    node(action, 'Arguments', subprocess.list2cmdline(['-u','-B',str(ROOT/'persistent_auto_load.py')]))
    node(action, 'WorkingDirectory', str(ROOT))
    return ET.tostring(root, encoding='unicode')


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.ShellExecuteW.argtypes = [wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,
                                       wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_int]
        shell.ShellExecuteW.restype = ctypes.c_void_p
        result = shell.ShellExecuteW(None,'runas',str(ROOT/'.venv/Scripts/python.exe'),
                                    subprocess.list2cmdline(['-B',str(Path(__file__).resolve())]),str(ROOT),0)
        return 0 if result and result > 32 else 1
    from attach_match import atomic_json
    from auto_load import STOP, build_helper, verified_runtime
    from persistent_auto_load import CONFIG
    report = ROOT/'artifacts/auto-takeover-install.json'
    try:
        verified_runtime();build_helper()
        sid = list(csv.reader(io.StringIO(subprocess.check_output(
            ['whoami','/user','/fo','csv','/nh'], text=True))))[0][1]
        previous = subprocess.run(['schtasks','/Query','/TN',TASK,'/XML'],capture_output=True,text=True)
        if previous.returncode == 0:
            prior = ET.fromstring(previous.stdout)
            command = prior.find('.//{'+NS+'}Exec/{'+NS+'}Command')
            arguments = prior.find('.//{'+NS+'}Exec/{'+NS+'}Arguments')
            if (command is None or Path(command.text) != ROOT/'.venv/Scripts/pythonw.exe'
                    or arguments is None or arguments.text != subprocess.list2cmdline(['-u','-B',str(ROOT/'persistent_auto_load.py')])):
                raise RuntimeError('Existing task with same name is not this project; not replaced')
        xml_path = ROOT/'artifacts/auto-takeover-task.xml'
        xml_path.write_text(task_xml(sid), encoding='utf-16')
        created = subprocess.run(['schtasks','/Create','/TN',TASK,'/XML',str(xml_path),'/F'],
                                 capture_output=True,text=True)
        if created.returncode:
            raise RuntimeError(created.stdout+created.stderr)
        atomic_json(CONFIG, dict(enabled=True,enemy_race=1,scope='KK configured 1v1 Undead practice'))
        if STOP.exists():STOP.unlink()
        started = subprocess.run(['schtasks','/Run','/TN',TASK],capture_output=True,text=True)
        if started.returncode:
            raise RuntimeError(started.stdout+started.stderr)
        atomic_json(report, dict(installed=True,task=TASK,sid=sid,enemy_race=1,
                                message=created.stdout+started.stdout))
        return 0
    except Exception as exc:
        atomic_json(report, dict(installed=False,task=TASK,error=str(exc)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
