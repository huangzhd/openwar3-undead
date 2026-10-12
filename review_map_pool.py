"""Offline map practice evidence; never imports a live game client."""
import argparse,hashlib,json
from collections import Counter
from pathlib import Path

def review(run):
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    rows=[json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    manifest=json.loads((run/'source-manifest.json').read_text(encoding='utf-8'))
    source_matches=all((run/'source'/name).is_file() and hashlib.sha256((run/'source'/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    starts=json.loads((run/'spawn-audit.json').read_text(encoding='utf-8')) if (run/'spawn-audit.json').exists() else None
    def selected(events):return [r for r in rows if r['event'] in events]
    milestones={}
    for r in rows:
        if r['event']!='summary':continue
        for h in r['heroes']:
            key=h['type']+'_level_'+str(h['level'])
            milestones.setdefault(key,r['clock'])
    valid=result['result'] in ('win','loss') and not result.get('cleanup_error') and not result.get('ui_cleanup_error') and any(r.get('result')==result['result'] for r in selected({'terminal_confirmed'}))
    data=dict(run=run.name,result=result['result'],reason=result['reason'],game_seconds=result.get('game_seconds'),
              valid_natural_finish=valid,source_snapshot_verified=source_matches,launch_settings=result.get('launch_settings'),
              spawn_sample=starts,first_observed_hero_levels=milestones,
              critter_evidence=selected({'scout_spawn_region','scout_critter_target','scout_corpse_observed','opening_rod_observed','opening_rod_attempt'}),
              route=selected({'creep_goal','creep_area_cleared','creep_target_deferred','creep_target_exhausted'}),
              attacks=selected({'attack_phase_started','enemy_race_observed','enemy_start_confirmed'}),
              teleport_evidence=selected({'teleport_attempt','teleport_confirmed','teleport_failed'}),
              event_counts=dict(Counter(r['event'] for r in rows)),
              limitations=['A creep_area_cleared event is local visible-area evidence, not hidden global unit accounting.',
                           'Spawn sample is taken during the match; it is not a zero-second snapshot.',
                           'First observed hero levels are bounded by summary cadence.'])
    (run/'map-review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:data[k] for k in ('run','result','game_seconds','valid_natural_finish','source_snapshot_verified')},ensure_ascii=False))
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('runs',nargs='+');a=p.parse_args()
    for run in a.runs:review(Path('artifacts')/run)
