"""Explicit local/upstream entry point; no game starts without the play command."""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psutil
from bootstrap import ROOT, UPSTREAM
from undead.maps import profiles, pool, resolve_map


def active_processes():
    """Read process identity, including attached games outside the owned session."""
    active = []
    for process in psutil.process_iter(['pid', 'name']):
        name = (process.info['name'] or '').lower()
        if name.startswith(('war3', 'warcraft')) and name.endswith('.exe'):
            active.append(dict(pid=process.pid, name=process.info['name']))
    for filename in ('session.json', 'attachment.json'):
        path = ROOT / 'artifacts' / filename
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('closed'):
            continue
        rows = list(record.get('processes', []))
        if record.get('runner_pid'):
            rows.append(dict(pid=record['runner_pid'], created=record.get('runner_created')))
        for row in rows:
            try:
                process = psutil.Process(row['pid'])
                if row.get('created') is not None and abs(process.create_time() - row['created']) > .01:
                    continue
                if process.is_running() and not any(p['pid'] == process.pid for p in active):
                    active.append(dict(pid=process.pid, name=process.name()))
            except psutil.NoSuchProcess:
                continue
    return active


def prepare(machine, game_dir=None, launching=False):
    config_path = UPSTREAM / 'openwar3.json'
    original = json.loads(config_path.read_text(encoding='utf-8'))
    profile = profiles()[machine]
    # Keep an explicitly saved installation override for this same machine.
    root = game_dir or (original['game_dir'] if original.get('undead_machine_profile') == machine
                       else profile['game_dir'])
    config = dict(original, game_dir=str(Path(root)), python=sys.executable,
                  undead_machine_profile=machine)
    config.setdefault('default_map', 'FrozenThrone\\(2)EchoIsles.w3x')
    missing = [name for name in ('render_hook.dll', 'war3_launch.exe', 'war3_ui_command.exe')
               if not (UPSTREAM / 'bin' / name).is_file()]
    if missing:
        raise ValueError('Missing OpenWar3AI runtime: ' + ', '.join(missing))
    maps = {}
    for alias in pool():
        path, catalog = resolve_map(alias, config)
        maps[alias] = dict(path=str(path), sha256=catalog['map_sha256'])
    active = active_processes()
    changed = config != original
    if active and (changed or launching):
        raise RuntimeError('An existing game/session blocks configuration changes or another launch: ' + str(active))
    if changed:
        backup = ROOT / 'artifacts' / ('machine-config-before-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(json.dumps(original, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(machine=machine, config_changed=changed, game_dir=config['game_dir'],
                python=config['python'], maps=maps, active_processes=active)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine', required=True, choices=tuple(profiles()))
    parser.add_argument('--game-dir', type=Path, help='Optional installation override, saved only in ignored vendor config')
    parser.add_argument('command', nargs='?', default='check', choices=('check', 'play'))
    args, extra = parser.parse_known_args()
    if args.command == 'check' and extra:
        parser.error('check does not accept gameplay arguments')
    if args.command == 'play' and ('--map' not in extra or '--enemy-race' not in extra):
        parser.error('play requires explicit --map and --enemy-race; use --difficulty 4 for insane')
    try:
        report = prepare(args.machine, args.game_dir, launching=args.command == 'play')
    except (OSError, ValueError, KeyError, RuntimeError, psutil.Error) as exc:
        print(json.dumps(dict(result='error', reason=str(exc), game_started=False), ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return subprocess.call([sys.executable, '-B', str(ROOT / 'bot.py'), args.command, *extra], cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
