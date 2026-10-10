"""Review recorded P1 evidence without issuing any game commands."""
import json,sys
from pathlib import Path
from collections import Counter
from undead.coil import can_damage
version=sys.argv[1];results=[];previous=None;previous_opponent=None;streak=0
for path in sorted(Path('artifacts').glob('*/result.json')):
 result=json.loads(path.read_text(encoding='utf-8'))
 if result.get('version')!=version:continue
 out=path.parent;rows=[json.loads(l) for l in (out/'events.jsonl').read_text(encoding='utf-8').splitlines()]
 manifest=json.loads((out/'source-manifest.json').read_text())
 same=previous is None or manifest==previous
 opponent=result.get('opponent',{'race':1,'difficulty':2})
 same_opponent=previous_opponent is None or opponent==previous_opponent
 coils=[r for r in rows if r['event'] in {'coil_damage_attempt','coil_heal_attempt'}]
 forbidden=[r for r in coils if not (can_damage(r['target']) if r['event']=='coil_damage_attempt' else r['target'] in {'Ulic','Nbrn','ucry','ugho'})]
 phase=next((r['clock'] for r in rows if r['event']=='attack_phase_started'),None)
 decisions=[r for r in rows if r['event']=='decision']
 post=[r for r in decisions if phase is not None and r['clock']>=phase]
 valid=result['result'] in {'win','loss'} and not result.get('cleanup_error') and any(r['event']=='terminal_confirmed' and r['result']==result['result'] for r in rows)
 streak=(streak+1 if same and same_opponent else 1) if valid else 0
 review={'result':result,'source_matches_previous':same,'valid_terminal_and_cleanup':valid,'counts':dict(Counter(r['event'] for r in rows)),'coil_attempts':len(coils),'forbidden_coil_attempts':forbidden,'post_orb_decisions':dict(Counter(r['actual'] for r in post)),'milestones':[r for r in rows if r['event'] in {'attack_phase_started','enemy_air_sighted','web_research_attempt','web_level_observed','web_effect_observed','attack_goal','enemy_main_empty','attack_search_goal','base_hall_missing','terminal_confirmed'}],'max_decision_gap':max((b['clock']-a['clock'] for a,b in zip(decisions,decisions[1:])),default=None)}
 (out/'p1-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
 results.append({'id':result['id'],'result':result['result'],'opponent':opponent,'valid':valid,'source_matches_previous':same,'opponent_matches_previous':same_opponent,'coil_attempts':len(coils),'forbidden_coils':len(forbidden),'review':str(out/'p1-review.json')})
 previous=manifest
 previous_opponent=opponent
series={'version':version,'runs':results,'valid_consecutive':streak,'passed':streak>=3,'status':'three-game terminal criterion passed' if streak>=3 else 'verification incomplete; review before next launch'}
Path('artifacts',f'p1-normal-series-{version.removesuffix("-dev")}.json').write_text(json.dumps(series,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(series,ensure_ascii=False,indent=2))
