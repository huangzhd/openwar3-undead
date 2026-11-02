"""Explicit, bounded single-instance reset verification. No model training."""
import argparse
import json
import math
import time
from pathlib import Path
from uuid import uuid4

from bootstrap import ROOT
from learning.environment import RuleEnvironment


def run_probe(episodes, *, game_seconds=60, wall_seconds=180, total_wall_seconds=420, output=None):
    if type(episodes) is not int or not 1 <= episodes <= 10:
        raise ValueError('Choose 1 to 10 explicit diagnostic episodes')
    for value in (game_seconds, wall_seconds, total_wall_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('All diagnostic limits must be finite and positive')
    output = Path(output) if output else ROOT/'artifacts'/(
        'environment-reset-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]+'.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    until = started+total_wall_seconds
    report = dict(schema='dayuan-reset-probe-v1', requested_episodes=episodes,
                  game_seconds=game_seconds, episode_wall_seconds=wall_seconds,
                  until=until, status='running', episodes=[], training_actor_approved=False)
    with output.open('x', encoding='utf-8') as stream:json.dump(report, stream, indent=2)
    def save():output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    previous_token = None
    env = RuleEnvironment()
    try:
        for index in range(episodes):
            if (ROOT/'artifacts'/'STOP').exists():
                report.update(status='stopped', reason='user_stop');break
            if time.time() >= until:
                report.update(status='stopped', reason='total_wall_limit');break
            episode = dict(index=index+1, status='starting', started_at=time.time(), steps=0, rule_steps=0,
                           accepted=0, rejected=0, unknown=0)
            report['episodes'].append(episode);save()
            frame = env.reset(game_seconds=game_seconds, wall_seconds=wall_seconds, until=until)
            token = frame['token']
            if token is not None:
                episode.update(run_id=token['run_id'], binding=token,
                               first_clock=frame['observation']['clock'], status='running')
                save()
                if previous_token is not None:
                    try:env.step(dict(kind='rule_tick', token=previous_token))
                    except ValueError:episode['old_token_rejected'] = True
                    else:raise RuntimeError('Old episode token was accepted')
                    if env.observe()['token'] != token:
                        raise RuntimeError('Rejected old token changed current decision')
                previous_token = token
            while not frame['done']:
                # Every step rechecks the absolute deadline before gameplay.
                if episode['steps'] >= 100000:raise RuntimeError('Diagnostic step budget exhausted')
                frame = env.step(dict(kind='rule_tick', token=frame['token']))
                episode['steps'] += 1
                if not frame['done']:episode['rule_steps'] += 1
                for receipt in frame['receipts']:
                    key = 'accepted' if receipt['accepted'] is True else 'rejected' if receipt['accepted'] is False else 'unknown'
                    episode[key] += 1
            result = env.result()
            episode.update(status='finished', result=result, finished_at=time.time(),
                           last_clock=frame['observation']['clock'] if frame['observation'] else None)
            termination = result['termination']
            expected = (termination['classification']=='natural_terminal' or
                        termination['classification']=='time_limit' and termination['reason']=='game_time_limit')
            episode['progress_observed'] = (episode['rule_steps'] > 0 and
                episode.get('first_clock') is not None and episode['last_clock'] > episode['first_clock'])
            if not episode['progress_observed']:
                report.update(status='stopped', reason='episode_made_no_progress');save();break
            if not result['cleanup_confirmed'] or not expected:
                report.update(status='stopped', reason='episode_failed_or_interrupted')
                save();break
            save()
        else:report.update(status='passed', reason='all_requested_resets_completed')
    except BaseException as exc:
        report.update(status='failed', reason=repr(exc))
        if not isinstance(exc, Exception):raise
    finally:
        try:
            closed = env.close()
            if closed is not None and not closed['cleanup_confirmed']:
                report.update(status='failed', reason='cleanup_unconfirmed')
            if report['episodes'] and report['episodes'][-1]['status'] != 'finished':
                report['episodes'][-1].update(status='interrupted', result=closed)
        except BaseException as exc:
            report.update(status='failed', cleanup_error=repr(exc))
        report['wall_seconds'] = round(time.time()-started, 3)
        save()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episodes',type=int,required=True)
    parser.add_argument('--game-seconds',type=float,default=60)
    parser.add_argument('--wall-seconds',type=float,default=180)
    parser.add_argument('--total-wall-seconds',type=float,default=420)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=run_probe(args.episodes,game_seconds=args.game_seconds,wall_seconds=args.wall_seconds,
                     total_wall_seconds=args.total_wall_seconds,output=args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
