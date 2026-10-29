"""Offline KFAI baseline review; never infer death from one absent sample."""
import argparse
import json
from pathlib import Path


def analyze(rows, result):
    episodes, active = [], {}
    for r in rows:
        if r.get('event') != 'hero_revival_state':
            continue
        missing = set(r.get('missing', []))
        for code in missing:
            if code not in active:
                active[code] = dict(hero=code, first_missing=r['clock'], queue_observed=None,
                                    returned=None, accepted_revive=None)
            if code in r.get('queued', []) and active[code]['queue_observed'] is None:
                active[code]['queue_observed'] = r['clock']
        for code in set(active) - missing:
            e = active.pop(code)
            e['returned'] = r['clock']
            episodes.append(e)
    episodes.extend(active.values())
    for e in episodes:
        attempts = [r for r in rows if r.get('event') == 'revive_attempt'
                    and e['hero'] in r.get('heroes', []) and r.get('accepted') is True
                    and e['first_missing'] <= r['clock'] <= (e['returned'] or float('inf'))]
        e['accepted_revive'] = attempts[0]['clock'] if attempts else None
        e['confirmed_revival_cycle'] = (e['queue_observed'] is not None and e['returned'] is not None
                                         and e['accepted_revive'] is not None)
        e['absence_seconds'] = round(e['returned'] - e['first_missing'], 3) if e['returned'] else None
    summaries = [r for r in rows if r.get('event') == 'summary']
    food = [r['resources']['food_used'] for r in summaries]
    releases = [r for r in rows if r.get('event') == 'upkeep_burst_released']
    empty = next((r for r in rows if r.get('event') == 'enemy_main_area_observed_empty'), None)
    terminal = next((r for r in reversed(rows) if r.get('event') == 'terminal_confirmed'), None)
    start = empty['clock'] if empty else None
    end = terminal['clock'] if terminal else None
    search = [r for r in rows if start is not None and r.get('clock', -1) >= start
              and r.get('event') in ('attack_search_goal', 'attack_search_checked', 'attack_search_deferred')]
    return dict(schema='kfai-baseline-review-v1', run=result.get('id'),
                result=result.get('result'), hero_revival=episodes,
                economy=dict(max_sampled_food=max(food, default=None), final_sampled_food=food[-1] if food else None,
                             upkeep_releases=releases, permanent_49_food_cap=False if releases else None,
                             interpretation=('Observed upkeep releases: food above 49 alone is not a violation.' if releases
                                             else 'No upkeep release observed; this does not establish a permanent food cap.')),
                cleanup_search=dict(main_empty_clock=start, terminal_clock=end,
                                    seconds=round(end-start, 3) if start is not None and end is not None else None,
                                    goals=[r for r in search if r['event']=='attack_search_goal'],
                                    checked=sum(r['event']=='attack_search_checked' for r in search),
                                    deferred=[r for r in search if r['event']=='attack_search_deferred']),
                limitations=['Revival queue plus return confirms a revival cycle, not the exact death time or cause.',
                             'Search duration includes travel, combat and enemy rebuilding; it is not measured idle time.',
                             'No historical internal KFAI strategy ID was recorded; army composition is not a strategy label.'],
                training_actor_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    report = analyze(rows, json.loads((args.run/'result.json').read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
