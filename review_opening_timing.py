"""Offline opening milestones and deviations; commands are not completion."""
import json
from collections import Counter
from pathlib import Path

BASELINE=Path(__file__).resolve().parent/'data/opening_timing_baseline.json'


def analyze(rows, baseline, version):
    milestones={};ordered=Counter();founded=Counter();interference=None
    for row in rows:
        event=row['event'];clock=row.get('clock')
        if clock is None:continue
        if (event=='player_contact_interrupt' or row.get('base_enemy_hp',0)>0
                or event=='summary' and row.get('situation',{}).get('base_enemy_hp',0)>0):
            interference=clock if interference is None else min(clock,interference)
        if event=='purchase':
            code=row['code']
            if row['kind']=='build':
                # Failed placement attempts and actual foundations have separate
                # ordinals; a retry is not an extra completed population tower.
                ordered[code]+=1;milestones[f'build_attempt:{code}:{ordered[code]}:decision']=clock
            elif code in {'unp1','unp2','Udea','Ulic','ucry','uobs','ugho'} and row.get('accepted'):
                key=f'produce:{code}:first_order';milestones.setdefault(key,clock)
        elif event=='home_foundation_observed':
            code=row['code'];founded[code]+=1;milestones[f'build:{code}:{founded[code]}:foundation']=clock
        elif event=='opening_observed':milestones.setdefault('opening:'+row['stage'],clock)
        elif event in {'decision','summary'}:
            tier=row.get('tier',row.get('situation',{}).get('tier',1))
            for level in (2,3):
                if tier>=level:milestones.setdefault(f'tier:{level}:observed',clock)
            for hero in row.get('heroes',[]):
                code=hero['type'] if isinstance(hero,dict) else hero[0]
                milestones.setdefault('hero:'+code+':observed',clock)
        elif event=='item_confirmed' and row.get('code') in {'rnec','ocor'}:
            milestones.setdefault(f'item:{row["hero"]}:{row["code"]}:observed',clock)
    reference=baseline.get('milestones',{})
    compatible=bool(reference and baseline.get('version')==version)
    deviations=[];unreached=[]
    for key,expected in reference.items():
        if key not in milestones:
            if rows and max((r.get('clock',0) for r in rows))>expected+baseline.get('absolute_tolerance_seconds',20):unreached.append(key)
            continue
        actual=milestones[key];threshold=max(baseline.get('absolute_tolerance_seconds',20),expected*baseline.get('relative_tolerance',.15))
        if abs(actual-expected)>threshold:
            deviations.append(dict(milestone=key,reference=expected,actual=actual,delta=round(actual-expected,3),
                                   threshold=round(threshold,3),priority='investigate',
                                   interference_before_actual=interference is not None and interference<=actual,
                                   comparable_version=compatible))
    return dict(milestones=milestones,first_player_interference=interference,
                placement_failures=[r for r in rows if r['event']=='home_foundation_unconfirmed'],
                baseline_status=baseline.get('status','not_calibrated'),baseline_run=baseline.get('run'),
                comparable_version=compatible,deviations=deviations,unreached_reference_milestones=unreached,
                limitations=['build attempt ordinals and actual foundation ordinals are independent after failures',
                             'decision timestamps are not exact order dispatch or construction start',
                             'foundation and hero/tier observations are sampled, not exact completion times',
                             'missing interference events do not prove absence of all enemy interference',
                             'candidate baselines and version mismatches are investigative references, not pass/fail gates'])


def review(run):
    run=Path(run)
    rows=[json.loads(s) for s in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    baseline=json.loads(BASELINE.read_text(encoding='utf-8')) if BASELINE.exists() else {}
    report=analyze(rows,baseline,result['version']);report['run']=run.name;report['version']=result['version']
    (run/'opening-timing-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 开局时点复盘', '',f'对局：{run.name}；版本：{result["version"]}；参考状态：{report["baseline_status"]}。',
           '下单、地基和完成观察分开；明显偏差优先排查敌方干扰、资源／人口、工人采集、选址耗时和科技预算。', '',
           '| 时点 | 游戏秒 |','|---|---:|']
    lines += [f'| {key} | {value:.3f} |' for key,value in sorted(report['milestones'].items(),key=lambda kv:kv[1])]
    lines += ['', '## 偏差提醒', '', '参考未校准时只记录，不宣称符合正常开局。不同版本及存在敌方干扰时仍保留提醒，但不直接归因于经济代码。']
    lines += [f'- {r["milestone"]}：参考{r["reference"]:.1f}秒，本局{r["actual"]:.1f}秒，差{r["delta"]:+.1f}秒；此前干扰={r["interference_before_actual"]}。' for r in report['deviations']]
    lines += [f'- 参考应出现但本局尚未记录：{key}（需检查观察缺失或实际延误）。' for key in report['unreached_reference_milestones']]
    lines += [f'- {r["clock"]:.3f}秒 {r["code"]} 地基未确认，检查工人／落点／资源：{r.get("point")}。' for r in report['placement_failures']]
    (run/'opening-timing-review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:
        r=review(Path('artifacts')/name)
        print(json.dumps({k:r[k] for k in ('run','baseline_status','first_player_interference','deviations')},ensure_ascii=False))
