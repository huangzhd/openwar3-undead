"""Portable training entry point. Its parent is the user's WC3 installation."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import traceback

ROOT = Path(__file__).resolve().parent
UPSTREAM_NAME = 'OpenWar3AI-ffd7dd25a3c2478f457b74bde89d23e605b24243'
GAME_VERSION = '1.27.0.52240'
RUNTIME = {
    'render_hook.dll': '92bb7e6b75e56f91e7eb905844b9a28085e88d4d991a547522c7da8c2907da97',
    'war3_launch.exe': 'c86eb9239355a097a53a1da5b21243f64d956d338f68aeb639b54485369a716b',
    'war3_ui_command.exe': 'fd63df069d017ba68977823a609799235e5b9e96c7124eb5540906f8ade667d0',
}
GENERATED = ('units.json', 'names.json', 'skills.json', 'items.json', 'heroes.json', 'buffs.json')
TABLES = ('UnitBalance.slk', 'UnitWeapons.slk', 'UnitData.slk', 'UnitUI.slk',
          'UnitAbilities.slk', 'AbilityData.slk', 'UpgradeData.slk', 'ItemData.slk',
          'DestructableData.slk', 'ItemFunc.txt', 'ItemStrings.txt', 'ItemAbilityFunc.txt',
          'ItemAbilityStrings.txt', 'HumanAbilityStrings.txt', 'MiscData.txt',
          'MiscGame.txt', 'MiscUI.txt', 'UI_MiscData.txt')


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_version(path):
    api = ctypes.windll.version
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                 ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:return None
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)):return None
    if not pointer.value or length.value < 16:return None
    info = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
    ms, ls = info[2], info[3]
    return f'{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}'


def locate_game(root=ROOT, version_reader=file_version):
    game = root.resolve().parent
    if not all((game / name).is_file() for name in ('War3.exe', 'Game.dll')):
        raise ValueError('文件夹位置不对。\n请把整个 dayuan-training 文件夹放到魔兽目录里，'
                         '与 War3.exe、Game.dll 同一层。\n不要只复制启动脚本，也不要放进 Maps 文件夹。')
    version = version_reader(game / 'Game.dll')
    if version != GAME_VERSION:
        raise ValueError(f'当前游戏版本：{version or "无法读取"}。\n需要魔兽争霸 III 1.27a '
                         f'（{GAME_VERSION}），1.27b 不兼容。')
    if not all((game / name).is_file() for name in ('war3.mpq', 'War3x.mpq')):
        raise ValueError('游戏文件不完整：需要 war3.mpq 和 War3x.mpq。请使用完整的 1.27a 游戏目录。')
    return game


def active_games():
    import psutil
    return [p.info['name'] for p in psutil.process_iter(['name'])
            if (p.info['name'] or '').lower().startswith(('war3', 'warcraft'))
            and (p.info['name'] or '').lower().endswith('.exe')]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def configure(root, game, executable):
    # Do not copy either development machine's profile or game path.
    config = dict(game_dir=str(game), maps_dir='', python=str(executable),
                  default_map='FrozenThrone\\(2)EchoIsles.w3x', undead_machine_profile='portable-training')
    atomic_json(root / 'vendor' / UPSTREAM_NAME / 'openwar3.json', config)


def install_runtime(upstream):
    for name, expected in RUNTIME.items():
        source = upstream / 'prebuilt' / name
        if not source.is_file() or digest(source) != expected:
            raise ValueError(f'运行组件缺失或损坏：{name}。请重新解压完整训练包。')
    for name, expected in RUNTIME.items():
        destination = upstream / 'bin' / name
        if not destination.is_file() or digest(destination) != expected:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(upstream / 'prebuilt' / name, destination)


def game_signature(game):
    # Relocation and replaced MPQs invalidate preparation, without hashing GBs each launch.
    return dict(game_dir=str(game.resolve()), files={name: [p.stat().st_size, p.stat().st_mtime_ns]
                for name in ('Game.dll', 'War3Patch.mpq', 'War3xLocal.mpq', 'War3x.mpq', 'war3.mpq')
                if (p := game / name).is_file()})


def data_ready(upstream, signature):
    try:
        folder = upstream / 'data' / 'game'
        if json.loads((folder / 'dayuan-prepared.json').read_text(encoding='utf-8')) != signature:return False
        if not all((folder / name).is_file() and (folder / name).stat().st_size for name in TABLES):return False
        return all(isinstance(value := json.loads((folder / name).read_text(encoding='utf-8')), dict)
                   and bool(value) for name in GENERATED)
    except (OSError, ValueError):return False


def run_tool(arguments, cwd, env, log):
    result = subprocess.run([sys.executable, '-E', '-s', '-X', 'utf8', '-B', *map(str, arguments)],
                            cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=180)
    if result.returncode:
        raise RuntimeError('游戏数据准备失败，请查看 dayuan-training/artifacts/portable-setup.log。')


def prepare(root=ROOT, progress=print):
    progress('检查文件夹位置与游戏版本…')
    game = locate_game(root)
    if active_games():raise RuntimeError('请先关闭正在运行的魔兽游戏，再双击训练启动脚本。')
    # Probe both writable locations before modifying config or extracting tables.
    for folder in (root / 'artifacts', game / 'Maps' / 'OpenWar3Training'):
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f'.dayuan-write-check-{os.getpid()}'
        try:probe.write_bytes(b'')
        finally:probe.unlink(missing_ok=True)
    upstream = root / 'vendor' / UPSTREAM_NAME
    progress('校验训练组件…')
    install_runtime(upstream)
    configure(root, game, Path(sys.executable))
    signature = game_signature(game)
    with (root / 'artifacts' / 'portable-setup.log').open('w', encoding='utf-8') as log:
        if not data_ready(upstream, signature):
            progress('首次准备：从你的游戏中提取数据，请稍候…')
            env = dict(os.environ, WAR3_GAME_DIR=str(game), PYTHONIOENCODING='utf-8')
            tool_dir = upstream / 'data' / 'tools'
            # Upstream's wrapper does not propagate generator failures; run each explicitly.
            run_tool([tool_dir / 'extract_game_data.py', '--no-generate'], upstream, env, log)
            for name in ('parse_slk.py', 'extract_names.py', 'make_skills.py', 'make_items.py', 'make_buffs.py'):
                run_tool([tool_dir / name], upstream, env, log)
            atomic_json(upstream / 'data' / 'game' / 'dayuan-prepared.json', signature)
            if not data_ready(upstream, signature):raise RuntimeError('游戏数据不完整，请查看 portable-setup.log。')
        progress('检查训练地图和面板…')
        # New subprocess loads paths only after this machine's config/data is ready.
        run_tool([root / 'training_launcher.py', '--verify-assets'], root, os.environ.copy(), log)
    progress('训练环境准备完成。')
    return dict(game_dir=str(game), version=GAME_VERSION, game_started=False)


class LauncherLock:
    def __init__(self, root):self.path=root / 'artifacts' / 'portable-launcher.lock';self.stream=None
    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream=self.path.open('a+b')
        self.stream.seek(0, 2)
        if self.stream.tell()==0:self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.stream.close()
            raise RuntimeError('训练面板已打开或正在准备，请使用已经打开的窗口。') from None
        return self
    def __exit__(self, *args):
        import msvcrt
        self.stream.seek(0);msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1);self.stream.close()


def show_launcher():
    import tkinter as tk
    from tkinter import messagebox, ttk
    window = tk.Tk();window.title('dayuan 训练启动');window.geometry('530x170');window.resizable(False, False)
    status = tk.StringVar(value='正在准备训练面板…')
    ttk.Label(window, textvariable=status, padding=22, wraplength=480).pack()
    bar = ttk.Progressbar(window, mode='indeterminate', length=460);bar.pack(pady=6);bar.start()
    window.protocol('WM_DELETE_WINDOW', lambda: None)
    updates = queue.Queue();outcome = []
    def worker():
        try:prepare(progress=lambda text:updates.put(('progress', text)));updates.put(('ready', None))
        except Exception as exc:
            traceback.print_exc();updates.put(('error', str(exc)))
    def poll():
        try:
            while True:
                event, value = updates.get_nowait()
                if event=='progress':status.set(value)
                else:
                    if event=='error':messagebox.showerror('无法启动训练', value, parent=window)
                    outcome.append(event=='ready');window.destroy();return
        except queue.Empty:pass
        window.after(100, poll)
    threading.Thread(target=worker, daemon=True).start();window.after(100, poll);window.mainloop()
    if outcome != [True]:return 1
    import training_control
    return training_control.panel()


def main(argv=None):
    # The existing panel launches worker Python processes; keep those portable too.
    os.environ.pop('PYTHONHOME',None);os.environ.pop('PYTHONPATH',None)
    os.environ['PYTHONUTF8']='1';os.environ['PYTHONIOENCODING']='utf-8'
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Prepare/check without opening a panel or game')
    parser.add_argument('--verify-assets', action='store_true', help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.verify_assets:
        import bootstrap
        from training_map import build
        import training
        import tkinter
        build(download=False)
        print('Training imports and map adaptation OK; no game started.');return 0
    if args.check:
        with LauncherLock(ROOT):print(json.dumps(prepare(),ensure_ascii=False))
        return 0
    ROOT.joinpath('artifacts').mkdir(parents=True,exist_ok=True)
    with ROOT.joinpath('artifacts/portable-launcher.log').open('a',encoding='utf-8',buffering=1) as log:
        original=(sys.stdout,sys.stderr);sys.stdout=sys.stderr=log
        try:
            with LauncherLock(ROOT):return show_launcher()
        except Exception as exc:
            traceback.print_exc()
            import tkinter as tk
            from tkinter import messagebox
            window=tk.Tk();window.withdraw();messagebox.showerror('dayuan 训练启动',str(exc),parent=window)
            window.destroy();return 1
        finally:sys.stdout,sys.stderr=original


if __name__=='__main__':raise SystemExit(main())
