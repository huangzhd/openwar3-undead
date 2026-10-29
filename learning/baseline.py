"""Stage 0 evidence inventory. Never launches games or promotes a policy.

Usage: python -m learning.baseline artifacts/<run> ... --output <new-report.json>
An intact source snapshot and a terminal receipt are necessary, but do not
replace live verification of observer isolation and both opponents' economy.
"""
import argparse
import hashlib
import json
from pathlib import Path

PROFILES = ('human-fast-expand', 'human-rifle')
NATIVE_PROFILES = ('kfai-human',)
TERMINALS = {'win': 'all_enemy_buildings_destroyed',
             'loss': 'all_own_buildings_destroyed'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def inspect_run(folder):
    folder = Path(folder)
    result = read_json(folder / 'result.json')
    manifest = read_json(folder / 'source-manifest.json')
    rows = [json.loads(line) for line in (folder / 'events.jsonl').read_text(
        encoding='utf-8').splitlines() if line.strip()]
    broken = []
    source = (folder / 'source').resolve()
    for name, expected in manifest.items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            broken.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            broken.append(name)
    outcome, reason = result.get('result'), result.get('reason')
    natural = outcome in TERMINALS and reason == TERMINALS[outcome] and any(
        row.get('event') == 'terminal_confirmed' and row.get('result') == outcome
        and row.get('reason') == reason for row in rows)
    classification = ('natural_terminal' if natural else 'runtime_failure' if outcome == 'error'
                      else 'process_exit' if reason == 'human_game_closed'
                      else 'user_abort' if reason in ('user_stop', 'manual_restart')
                      else 'incomplete')
    settings = result.get('launch_settings', {})
    profile = result.get('opponent', {}).get('controller')
    source_id = hashlib.sha256(json.dumps(manifest, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    issues = []
    history = result.get('speed_history', [])
    speeds = [r.get('percent') for r in history]
    if not speeds or any(type(v) is not int or v <= 0 for v in speeds):
        speed_condition = 'unknown'
        issues.append('speed_observation_missing')
    else:
        speed_condition = ('fixed:'+str(speeds[0]) if len(set(speeds)) == 1
                           else 'variable:'+str(folder.resolve()))
    audit_path = folder/'source-audit.json'
    audit = read_json(audit_path) if audit_path.is_file() else {}
    if not (audit.get('source_unchanged') is True and audit.get('session_closed') is True
            and audit.get('active_processes') == [] and audit.get('mismatches') == []
            and audit.get('files') == len(manifest)):
        issues.append('end_of_run_source_or_cleanup_audit_missing')
    if result.get('mode') != 'bot_vs_bot' or profile not in (*PROFILES, *NATIVE_PROFILES):
        issues.append('not_supported_sparring_run')
    if broken or not manifest:issues.append('source_snapshot_invalid')
    if result.get('cleanup_error') or result.get('ui_cleanup_error'):issues.append('cleanup_failed')
    if not natural:issues.append('no_natural_terminal')
    ai_isolation = settings.get('native_ai_paused') is True
    if profile in NATIVE_PROFILES:
        ai_isolation = (settings.get('native_ai_paused') is False
                        and settings.get('native_ai_paused_players') == [1]
                        and settings.get('opponent_fairness') == 'native_KFAI_unverified'
                        and settings.get('active_player_slots') == [0, 1, 2]
                        and settings.get('verified_players') == [dict(slot=1, controller=1, race=3),
                                                                 dict(slot=2, controller=1, race=1)])
    if not (settings.get('mode') == 'bot_vs_bot' and settings.get('fair') is True
            and settings.get('observer_player') == 0 and settings.get('controlled_player') == 1
            and settings.get('opponent_player') == 2 and ai_isolation):
        issues.append('setup_verification_missing')
    if not settings.get('map_sha256'):issues.append('map_fingerprint_missing')
    return dict(run_id=result.get('id', folder.name), opponent=profile,
                classification=classification, reason=reason, outcome=outcome,
                source_id=source_id, broken_sources=broken,
                map_sha256=settings.get('map_sha256'), issues=issues,
                speed_condition=speed_condition,
                terminal_candidate=not issues,
                opponent_fairness=settings.get('opponent_fairness', 'not_recorded'))


def inventory(folders):
    runs = [inspect_run(folder) for folder in folders]
    # Different frozen revisions/maps/speeds are distinct baselines; never pool wins.
    groups = {}
    for run in runs:
        if not run['terminal_candidate']:continue
        key = (run['source_id'], run['map_sha256'], run['speed_condition'])
        groups.setdefault(key, set()).add(run['opponent'])
    return dict(schema='learning-stage0-inventory-v2', runs=runs,
                baselines=[dict(source_id=key[0], map_sha256=key[1], speed_condition=key[2],
                    opponents=sorted(profiles), both_opponents_recorded=set(PROFILES) <= profiles)
                    for key, profiles in sorted(groups.items())],
                training_actor_approved=False,
                remaining_checks=['live_observer_and_fair_view_isolation',
                                  'selected_opponent_pool_economy_and_combat',
                                  'native_KFAI_information_and_resource_audit',
                                  'observation_and_action_contract_freeze'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = inventory(args.runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':main()
