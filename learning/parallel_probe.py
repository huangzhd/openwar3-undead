"""Two explicitly bounded workers verify overlap, stale routing and isolated close."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil
from bootstrap import ROOT
from attach_match import atomic_json,read_atomic_json
from learning.environment import RuleEnvironment
from machine_start import active_processes
from session import Session
from practice_video import configure_video


def read(path):
    try:return read_atomic_json(path)
    except FileNotFoundError:return None


def worker(instance_id, cohort, folder, until):
    folder=Path(folder)
    path=folder/f'{instance_id}.json'
    peer=folder/f'{82 if instance_id==81 else 81}.json'
    state=dict(instance_id=instance_id,cohort=cohort,status='starting',steps=0,accepted=0)
    env=RuleEnvironment(instance_id=instance_id,cohort=cohort)
    def save():atomic_json(path,state)
    save()
    try:
        frame=env.reset(game_seconds=300,wall_seconds=180,until=until)
        if frame['done']:raise RuntimeError('Episode ended before ready')
        state.update(status='ready',ready_at=time.time(),binding=frame['token'],
                     first_clock=frame['observation']['clock'])
        save()
        after_peer_steps=0
        for _ in range(100000):
            if time.time()>=until:raise TimeoutError('Worker deadline')
            if (ROOT/'artifacts'/'STOP').exists() or (folder/'STOP').exists():
                raise RuntimeError('Probe stopped')
            other=read(peer)
            if other and other['status']=='failed':raise RuntimeError('Peer failed')
            if other and other.get('ready_at'):
                if 'overlap_clock' not in state:
                    state.update(overlap_at=time.time(),overlap_clock=frame['observation']['clock'])
                if instance_id==82 and not state.get('cross_token_rejected'):
                    token=frame['token']
                    try:env.step(dict(kind='rule_tick',token=other['binding']))
                    except ValueError:pass
                    else:raise RuntimeError('Cross-instance token accepted')
                    if env.observe()['token']!=token:raise RuntimeError('Rejected request consumed peer token')
                    state['cross_token_rejected']=True
                    save()
                if instance_id==81 and other.get('cross_token_rejected'):
                    after_peer_steps+=1
                    if (after_peer_steps>=4 and other.get('last_clock',0)>other['overlap_clock']
                            and frame['observation']['clock']>state['overlap_clock']):
                        state['peer_clock_before_close']=other['last_clock']
                        break
                if instance_id==82 and other.get('status')=='closed':
                    if not other['result']['cleanup_confirmed']:raise RuntimeError('Peer cleanup unconfirmed')
                    if 'after_peer_clock' not in state:
                        state.update(after_peer_clock=frame['observation']['clock'],after_peer_at=time.time(),
                                     after_peer_accepted=state['accepted'],after_peer_steps=state['steps'])
                    if (frame['observation']['clock']-state['after_peer_clock']>=5
                            and state['accepted']>state['after_peer_accepted']):break
            frame=env.step(dict(kind='rule_tick',token=frame['token']))
            if frame['done']:raise RuntimeError('Episode terminated before isolation verification')
            state['steps']+=1
            state['accepted']+=sum(r['accepted'] is True for r in frame['receipts'])
            state['last_clock']=frame['observation']['clock']
            save()
        else:raise RuntimeError('Worker step budget exhausted')
        state.update(status='closing',close_started_at=time.time());save()
        result=env.close()
        if not result or not result['cleanup_confirmed']:raise RuntimeError('Cleanup unconfirmed')
        state.update(status='closed',result=result,closed_at=time.time())
    except BaseException as exc:
        state.update(status='failed',error=repr(exc))
    finally:
        try:
            result=env.close()
            if result is not None:state['result']=result
        except BaseException as exc:state.update(status='failed',cleanup_error=repr(exc))
        save()
    return 0 if state['status']=='closed' else 1


def assess(rows):
    """Require progress on both sides of close, not merely concurrent PIDs."""
    errors=[]
    if len(rows)!=2 or any(not r or r.get('status')!='closed' for r in rows):
        return ['workers_not_cleanly_closed']
    a,b=rows
    if any(not r.get('result',{}).get('cleanup_confirmed') for r in rows):errors.append('cleanup_unconfirmed')
    if a['binding']['pid']==b['binding']['pid']:errors.append('same_game_pid')
    if a['binding']['run_id']==b['binding']['run_id']:errors.append('same_run_id')
    if not b.get('cross_token_rejected'):errors.append('cross_token_not_rejected')
    if max(r['ready_at'] for r in rows)>=min(r['close_started_at'] for r in rows):errors.append('no_overlap')
    for r in rows:
        if r.get('steps',0)<3 or r.get('last_clock',0)<=r.get('overlap_clock',float('inf')):
            errors.append('no_overlapping_progress:'+str(r['instance_id']))
    if b.get('after_peer_at',0)<a['closed_at']:errors.append('continuation_before_peer_cleanup')
    if b.get('last_clock',0)-b.get('after_peer_clock',float('inf'))<5:errors.append('no_progress_after_peer_close')
    if a.get('peer_clock_before_close',0)<=b.get('overlap_clock',float('inf')):errors.append('peer_did_not_progress_before_close')
    if (b.get('accepted',0)<=b.get('after_peer_accepted',float('inf'))
            or b.get('steps',0)<=b.get('after_peer_steps',float('inf'))):errors.append('no_accepted_action_after_peer_close')
    return errors


def cleanup_owned(cohort, workers, evidence=None, *, instance_ids=(81,82)):
    """Escalation only for identity-matched worker and its cohort session."""
    from learning.instance import INSTANCE_IDS
    if (not instance_ids or len(set(instance_ids))!=len(instance_ids)
            or any(type(i) is not int or i not in INSTANCE_IDS for i in instance_ids)):
        raise ValueError('Invalid cleanup instance scope')
    errors=[]
    checked=[identity for _,identity in workers]
    # Capture children while the recorded worker still owns them, covering the
    # short interval between Popen and session.remember(). Never scan by name.
    descendants=[]
    for process,identity in workers:
        if process.poll() is None:
            try:
                if Session.matches(identity):
                    descendants.extend(dict(pid=p.pid,created=p.create_time(),name=p.name())
                        for p in psutil.Process(identity['pid']).children(recursive=True))
            except psutil.Error as exc:errors.append(repr(exc))
    # A Windows venv python.exe may supervise the actual Python worker as a
    # child. Only accept child identities captured while that parent was alive.
    trusted_workers=[identity for _,identity in workers]+descendants
    for instance_id in instance_ids:
        try:
            base=ROOT/'artifacts'/'instances'/str(instance_id)
            owner=read(base/'owner.json')
            record=read(base/'session.json')
            if (not record or not owner or owner.get('cohort')!=cohort
                    or owner.get('worker') not in trusted_workers):continue
            for row in record.get('processes',[]):
                checked.append(row)
        except (OSError,ValueError,psutil.Error) as exc:errors.append(repr(exc))
    checked=list({(r['pid'],r['created'],r['name']):r for r in [*checked,*descendants]}.values())
    # Stop each owned launcher first. Its Windows Job terminates that game;
    # direct game termination can hit War3's DACL. Keep waiting through brief
    # exit/identity races, rather than declaring cleanup failed immediately.
    launchers=[r for r in checked if r['name'].lower()=='war3_launch.exe']
    game_rows=[r for r in checked if r not in launchers and r['name'].lower().startswith(('war3','warcraft'))]
    other_rows=[r for r in checked if r not in launchers and r not in game_rows]
    attempts=[]
    for row in [*launchers,*other_rows]:
        try:
            if Session.matches(row):psutil.Process(row['pid']).kill()
        except psutil.NoSuchProcess:pass
        except psutil.Error as exc:attempts.append(repr(exc))
    deadline=time.monotonic()+8
    transient=set()
    while True:
        remaining=[]
        for row in checked:
            try:
                if Session.matches(row):remaining.append(row)
            except psutil.Error as exc:
                remaining.append(row);transient.add(repr(exc))
        if not remaining or time.monotonic()>=deadline:break
        time.sleep(.1)
    if remaining:errors.append('Owned process cleanup not confirmed')
    if evidence is not None:evidence.update(checked=checked,remaining=remaining,
        termination_attempt_errors=attempts,transient_identity_errors=sorted(transient))
    return errors


def run_probe(output):
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive file and directory prevent accidental reuse of another probe's evidence.
    with output.open('x',encoding='utf-8') as stream:stream.write('{}\n')
    folder=output.with_suffix('');folder.mkdir(exist_ok=False)
    cohort=uuid.uuid4().hex
    started=time.time();until=started+240
    report=dict(schema='dayuan-parallel-probe-v1',cohort=cohort,status='running',
                started_at=started,until=until,instances=[81,82],training_actor_approved=False)
    workers=[];logs=[]
    try:
        if (ROOT/'artifacts'/'STOP').exists():raise RuntimeError('STOP blocks probe')
        if active_processes():raise RuntimeError('Active game blocks probe')
        report['display']=configure_video()
        for instance_id in (81,82):
            log=(folder/f'{instance_id}.log').open('wb');logs.append(log)
            process=subprocess.Popen([sys.executable,'-X','utf8','-B','-m','learning.parallel_probe',
                '--worker',str(instance_id),'--cohort',cohort,'--folder',str(folder),'--until',str(until)],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            p=psutil.Process(process.pid)
            workers.append((process,dict(pid=p.pid,created=p.create_time(),name=p.name())))
        while any(p.poll() is None for p,_ in workers):
            if time.time()>=until:raise TimeoutError('Total probe wall deadline')
            if (ROOT/'artifacts'/'STOP').exists():raise RuntimeError('User STOP')
            if any(p.poll() not in (None,0) for p,_ in workers):raise RuntimeError('Worker failed')
            time.sleep(.2)
        report['episodes']=[read(folder/f'{i}.json') for i in (81,82)]
        report['errors']=assess(report['episodes'])
        report['status']='failed' if report['errors'] else 'passed'
    except BaseException as exc:report.update(status='failed',error=repr(exc))
    finally:
        (folder/'STOP').touch()
        # Short cooperative grace before identity-checked emergency cleanup.
        deadline=time.monotonic()+5
        while any(p.poll() is None for p,_ in workers) and time.monotonic()<deadline:time.sleep(.1)
        report['cleanup_audit']={}
        report['cleanup_errors']=cleanup_owned(cohort,workers,report['cleanup_audit'])
        for log in logs:log.close()
        try:report['episodes']=[read(folder/f'{i}.json') for i in (81,82)]
        except Exception as exc:report['cleanup_errors'].append('report_read:'+repr(exc))
        try:report['active_processes_after']=active_processes()
        except Exception as exc:report['cleanup_errors'].append(repr(exc))
        if report['cleanup_errors'] or report.get('active_processes_after')!=[]:report['status']='failed'
        report['wall_seconds']=round(time.time()-started,3)
        atomic_json(output,report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--worker',type=int,choices=(81,82))
    parser.add_argument('--cohort')
    parser.add_argument('--folder',type=Path)
    parser.add_argument('--until',type=float)
    args=parser.parse_args()
    if args.worker:
        if not args.cohort or not args.folder or not args.until:parser.error('Worker binding missing')
        return worker(args.worker,args.cohort,args.folder,args.until)
    if not args.output:parser.error('--output is required')
    result=run_probe(args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
