"""Stage 0 evidence inventory. Never launches games or promotes a policy.

Usage: python -m learning.baseline artifacts/<run> ... --output <new-report.json>
An intact source snapshot and a terminal receipt are necessary, but do not
replace live verification of observer isolation and both opponents' economy.
"""
import argparse
import hashlib
import json
from pathlib import Path
from learning.outcome import NATURAL as TERMINALS, classify_outcome

PROFILES = ('human-fast-expand', 'human-rifle')
NATIVE_PROFILES = ('kfai-human',)


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
    confirmed = any(
        row.get('event') == 'terminal_confirmed' and row.get('result') == outcome
        and row.get('reason') == reason for row in rows)
    termination = classify_outcome(outcome, reason, natural_confirmed=confirmed)
    natural = termination['terminated']
    classification = termination['classification']
    settings = result.get('launch_settings', {})
    profile = result.get('opponent', {}).get('controller')
    source_id = hashlib.sha256(json.dumps(manifest, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    issues = []
    if result.get('policy','rule') != 'rule' or result.get('control','rule') != 'rule':
        issues.append('not_rule_policy')
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
    if any(result.get(k) for k in ('cleanup_error', 'ui_cleanup_error',
                                   'trajectory_cleanup_error', 'visibility_cleanup_error', 'runtime_guard_cleanup_error',
                                   'primitive_cleanup_error','environment_frame_cleanup_error',
                                   'meter_cleanup_error', 'evidence_error')):
        issues.append('cleanup_failed')
    if not natural:issues.append('no_natural_terminal')
    ai_isolation = settings.get('native_ai_paused') is True
    if profile in NATIVE_PROFILES:
        # Preserve the recorded old computer-actor contract, separately grouped
        # by frozen source/map. New KFAI maps use a USER actor with no native AI.
        actor_setup = (settings.get('native_ai_paused_players'),settings.get('verified_players'),
                       settings.get('active_player_slots'))
        isolated_actor = actor_setup == (
            [1],[dict(slot=1,controller=1,race=3),dict(slot=2,controller=1,race=1)],[0,1,2]) or (
            actor_setup == ([],[dict(slot=1,controller=0,race=3),dict(slot=2,controller=1,race=1)],[0,2])
            and settings.get('player_slot_states') == [1,0,1])
        ai_isolation = (settings.get('native_ai_paused') is False
                        and isolated_actor
                        and settings.get('opponent_fairness') == 'native_KFAI_unverified')
    if not (settings.get('mode') == 'bot_vs_bot' and settings.get('fair') is True
            and settings.get('observer_player') == 0 and settings.get('controlled_player') == 1
            and settings.get('opponent_player') == 2 and ai_isolation):
        issues.append('setup_verification_missing')
    if not settings.get('map_sha256'):issues.append('map_fingerprint_missing')
    return dict(run_id=result.get('id', folder.name), opponent=profile, policy=result.get('policy','rule'),
                classification=classification, reason=reason, outcome=outcome, termination=termination,
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
