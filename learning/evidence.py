"""Freeze rule interface provenance and audit local run cleanup without approval."""
import hashlib
import json
from pathlib import Path, PureWindowsPath

from bootstrap import UPSTREAM
from learning.outcome import SCHEMA as OUTCOME_SCHEMA


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, report):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return report


def safe_path(base, name):
    if not isinstance(name, str) or not name or PureWindowsPath(name).is_absolute():
        raise ValueError('Invalid source path')
    parts = name.replace('\\', '/').split('/')
    if any(part in ('', '.', '..') or ':' in part for part in parts):
        raise ValueError('Invalid source path')
    path = (base / Path(*parts)).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Source path escapes root')
    return path


def freeze_contract(root, out, manifest, settings, *, rules_version, opponent, pid=None, epoch=None, control='rule'):
    """Record actual bytes, not an assertion that dependencies or a run passed."""
    root, out = Path(root), Path(out)
    upstream = root / 'vendor' / UPSTREAM.name
    dependencies, errors = {}, []
    groups = {
        'sdk': sorted((upstream / 'sdk').rglob('*.py')),
        'sdk_data': sorted((upstream / 'sdk').rglob('*.json')),
        'game_data': sorted((upstream / 'data' / 'game').rglob('*.json')),
        'runtime': sorted((upstream / 'runtime').rglob('*.py')),
        'bin': sorted(p for p in (upstream / 'bin').rglob('*')
                      if p.is_file() and p.suffix.lower() in ('.dll', '.exe')),
    }
    for group, paths in groups.items():
        if not paths:
            errors.append('missing_dependency_group:' + group)
        for path in paths:
            name = path.relative_to(root).as_posix()
            try:
                dependencies[name] = digest(path)
            except OSError as exc:
                errors.append(name + ':' + type(exc).__name__)
    for name in ('render_hook.dll', 'war3_launch.exe', 'war3_ui_command.exe'):
        if not (upstream / 'bin' / name).is_file():
            errors.append('missing_runtime:' + name)
    if not (upstream / 'sdk/python/openwar3/jass_signatures.json').is_file():
        errors.append('missing_sdk_data:jass_signatures.json')
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    report = dict(schema='dayuan-interface-contract-v1',
        observation_version='strict-p1-observation-v1', action_version='rule-native-v1',
        trajectory_schema='dayuan-trajectory-v1', outcome_schema=OUTCOME_SCHEMA,
        policy='rule', rules_version=rules_version, opponent=opponent,
        opponent_fairness=settings.get('opponent_fairness'),
        source_manifest_sha256=manifest_hash, map_sha256=settings.get('map_sha256'),
        slots={key: settings.get(key) for key in
               ('observer_player', 'controlled_player', 'opponent_player')},
        speed=settings.get('speed'), binding=dict(pid=pid, epoch=epoch),
        dependencies=dependencies, dependency_errors=errors,
        referee_scope='all_live_player_buildings_destroyed_not_full_ladder_rules',
        model_action_adapter=False, training_actor_approved=False)
    if control == 'primitives':
        from learning.actions import SCHEMA
        report.update(policy='external_primitives', action_version=SCHEMA,
                      model_action_adapter='partial_primitives_offline_only',
                      action_log='primitive-actions.jsonl', native_trajectory_action_version='rule-native-v1')
    elif control != 'rule':raise ValueError('Unsupported control mode')
    return write_new(out / 'interface-contract.json', report)


def audit_sources(root, out, manifest, *, instance_context=None):
    """Audit both copies and cleanup; unknown state is always a failed check."""
    from machine_start import active_processes
    root, out = Path(root), Path(out)
    mismatches, frozen_mismatches, errors = [], [], []
    for name, expected in manifest.items():
        for base, failures in ((root, mismatches), (out / 'source', frozen_mismatches)):
            try:
                if digest(safe_path(base, name)) != expected:
                    failures.append(name)
            except (OSError, ValueError) as exc:
                failures.append(name)
                errors.append(dict(source=name, copy='current' if base == root else 'frozen',
                                   error=type(exc).__name__))
    dependency_mismatches = []
    contract_path = out / 'interface-contract.json'
    if contract_path.exists():
        try:
            contract = json.loads(contract_path.read_text(encoding='utf-8'))
            dependencies = contract['dependencies']
            if not isinstance(dependencies, dict) or not dependencies or contract.get('dependency_errors'):
                dependency_mismatches.append('dependency_manifest_incomplete')
            if isinstance(dependencies, dict):
                for name, expected in dependencies.items():
                    try:
                        if digest(safe_path(root, name)) != expected:
                            dependency_mismatches.append(name)
                    except (OSError, ValueError) as exc:
                        dependency_mismatches.append(name)
                        errors.append(dict(check='dependency', source=name, error=type(exc).__name__))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            dependency_mismatches.append('dependency_manifest_unreadable')
            errors.append(dict(check='dependency_manifest', error=type(exc).__name__))
    session_closed = False
    try:
        record = instance_context.record if instance_context else root/'artifacts'/'session.json'
        session = json.loads(record.read_text(encoding='utf-8'))
        session_closed = session.get('closed') is True and session.get('processes') == []
    except (OSError, ValueError, AttributeError) as exc:
        errors.append(dict(check='session', error=type(exc).__name__))
    processes = None
    try:
        processes = instance_context.processes() if instance_context else active_processes()
    except Exception as exc:
        errors.append(dict(check='active_processes', error=type(exc).__name__))
    report = dict(files=len(manifest), mismatches=mismatches, frozen_mismatches=frozen_mismatches,
        dependency_mismatches=dependency_mismatches,
        source_unchanged=bool(manifest) and not mismatches and not frozen_mismatches and not dependency_mismatches,
        session_closed=session_closed, active_processes=processes, errors=errors,
        training_actor_approved=False)
    if instance_context:
        report.update(process_scope='owned_instance',instance_id=instance_context.instance_id,
                      cohort=instance_context.cohort,session_record=str(instance_context.record))
    return write_new(out / 'source-audit.json', report)
