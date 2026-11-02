"""Four bounded live environments, one independent reset, no learning actor."""
import argparse
import json
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

import psutil
from bootstrap import ROOT
from attach_match import atomic_json
from learning.environment import RuleEnvironment
from learning.parallel_probe import read, cleanup_owned
from machine_start import active_processes
from practice_video import configure_video

INSTANCES=(81,82,83,84)
BINDING_KEYS=('instance','episode','run_id','pid','epoch')


def worker(instance_id,cohort,folder,until):
    folder=Path(folder);path=folder/f'{instance_id}.json'
    until=min(until,time.time()+540)
    state=dict(instance_id=instance_id,cohort=cohort,status='starting',episodes=[],resets=0)
    env=RuleEnvironment(instance_id=instance_id,cohort=cohort)
    def save():atomic_json(path,state)
    def check():
        if time.time()>=until:raise TimeoutError('Worker deadline')
        if any(p.exists() for p in (ROOT/'artifacts'/'STOP',folder/'STOP',
                                   ROOT/'artifacts'/'instances'/str(instance_id)/'STOP')):
            raise RuntimeError('Probe stopped')
    def mark(ep):
        return dict(at=time.time(),clock=ep['last_clock'],steps=ep['steps'],accepted=ep['accepted'])
    def begin():
        check();state['resets']+=1
        state['status']='starting' if state['resets']==1 else 'resetting';save()
        frame=env.reset(game_seconds=1800,wall_seconds=540,until=until)
        if frame['done']:
            state['pending_reset_result']=env.result()
            raise RuntimeError('Episode ended before ready')
        ep=dict(binding=frame['token'],ready_at=time.time(),first_clock=frame['observation']['clock'],
                last_clock=frame['observation']['clock'],steps=0,accepted=0,max_observation_gap=0.)
        state['episodes'].append(ep);state['current']=ep;state['status']='ready';save()
        return frame,ep
    def reject(token,frame):
        try:env.step(dict(kind='rule_tick',token=token))
        except ValueError:pass
        else:raise RuntimeError('Foreign or stale token accepted')
        if env.observe()['token']!=frame['token']:raise RuntimeError('Rejected token consumed current token')
    save()
    try:
        frame,ep=begin()
        for _ in range(100000):
            check()
            rows={i:state if i==instance_id else read(folder/f'{i}.json') for i in INSTANCES}
            if any(r and r['status']=='failed' for r in rows.values()):raise RuntimeError('Peer failed')
            if all(r and r.get('episodes') for r in rows.values()):
                if 'common_start' not in state:
                    state['common_start']=mark(ep)
                    peer_id=INSTANCES[(INSTANCES.index(instance_id)+1)%4]
                    reject(rows[peer_id]['episodes'][0]['binding'],frame)
                    state['cross_token_rejected']=True;save()
                start=state['common_start']
                if (len(state['episodes'])==1 and 'common_done' not in state
                        and ep['last_clock']-start['clock']>=20
                        and ep['steps']-start['steps']>=5 and ep['accepted']>start['accepted']):
                    state['common_done']=mark(ep);save()
                leader=rows[81]
                if instance_id==81 and len(state['episodes'])==1:
                    if all(r.get('common_done') for r in rows.values()):
                        state['reset_intent_at']=state.get('reset_intent_at',time.time());save()
                        if all(rows[i].get('reset_seen') for i in INSTANCES[1:]):
                            old=frame['token'];state['first_close_started_at']=time.time();save()
                            ep['result']=env.close();ep['closed_at']=time.time();save()
                            if not ep['result'] or not ep['result']['cleanup_confirmed']:
                                raise RuntimeError('First cleanup unconfirmed')
                            state.update(status='resetting',reset_started_at=time.time());save()
                            frame,ep=begin()
                            if any(old[k]==frame['token'][k] for k in ('pid','run_id','episode')):
                                raise RuntimeError('Reset reused binding')
                            reject(old,frame)
                            state.update(old_token_rejected=True,restarted_at=time.time());save()
                            continue
                elif instance_id!=81:
                    if leader.get('reset_intent_at') and 'reset_seen' not in state:
                        state['reset_seen']=mark(ep);save()
                    if leader.get('reset_started_at') and 'reset_running_seen' not in state:
                        state['reset_running_seen']=mark(ep);save()
                    if leader.get('restarted_at') and 'restart_seen' not in state:
                        state['restart_seen']=mark(ep);save()
                    marker=state.get('restart_seen')
                    if (marker and ep['last_clock']-marker['clock']>=10
                            and ep['accepted']>marker['accepted']):
                        state['post_restart_progress']=True;save()
                    if leader['status']=='closed' and state.get('post_restart_progress'):break
                elif len(state['episodes'])==2:
                    if (ep['last_clock']-ep['first_clock']>=10 and ep['accepted']>0
                            and all(rows[i].get('post_restart_progress') for i in INSTANCES[1:])):break
            new=env.step(dict(kind='rule_tick',token=frame['token']))
            if new['done']:raise RuntimeError('Unexpected episode termination')
            if any(new['token'][k]!=ep['binding'][k] for k in BINDING_KEYS):raise RuntimeError('Live binding changed')
            clock=new['observation']['clock']
            ep['max_observation_gap']=max(ep['max_observation_gap'],clock-ep['last_clock'])
            ep['last_clock']=clock;ep['steps']+=1
            ep['accepted']+=sum(r['accepted'] is True for r in new['receipts'])
            frame=new;save()
        else:raise RuntimeError('Worker step budget exhausted')
        state.update(status='closing',close_started_at=time.time());save()
        ep['result']=env.close();ep['closed_at']=time.time()
        if not ep['result'] or not ep['result']['cleanup_confirmed']:raise RuntimeError('Final cleanup unconfirmed')
        state.update(status='closed',closed_at=time.time())
    except BaseException as exc:
        state.update(status='failed',error=repr(exc),error_text=str(exc),traceback=traceback.format_exc())
    finally:
        try:
            result=env.close()
            if result:
                if not state['episodes'] or state['resets']>len(state['episodes']):state['pending_reset_result']=result
                else:state['episodes'][-1]['result']=result
        except BaseException as exc:
            state.update(status='failed',cleanup_error=repr(exc),cleanup_error_text=str(exc),cleanup_traceback=traceback.format_exc())
        save()
    return 0 if state['status']=='closed' else 1


def assess(rows):
    if len(rows)!=4 or any(not r or r.get('status')!='closed' for r in rows):return ['workers_not_cleanly_closed']
    if [r['instance_id'] for r in rows]!=list(INSTANCES):return ['incorrect_instances']
    a=rows[0];errors=[]
    if any(len(r['episodes'])!=(2 if i==0 else 1) or r['resets']!=(2 if i==0 else 1) for i,r in enumerate(rows)):
        return ['wrong_episode_count']
    episodes=[e for r in rows for e in r['episodes']]
    if any(not e.get('result',{}).get('cleanup_confirmed') for e in episodes):errors.append('cleanup_unconfirmed')
    if len({e['binding']['pid'] for e in episodes})!=5 or len({e['binding']['run_id'] for e in episodes})!=5:errors.append('binding_collision')
    ready=max(r['episodes'][0]['ready_at'] for r in rows)
    for r in rows:
        start=r.get('common_start',{});done=r.get('common_done',{})
        if (start.get('at',0)<ready or done.get('at',float('inf'))>a['first_close_started_at']
                or done.get('clock',0)-start.get('clock',float('inf'))<20
                or done.get('steps',0)-start.get('steps',float('inf'))<5
                or done.get('accepted',0)<=start.get('accepted',float('inf'))):
            errors.append('no_common_progress:'+str(r['instance_id']))
        if not r.get('cross_token_rejected'):errors.append('cross_token_not_rejected:'+str(r['instance_id']))
    old,new=a['episodes']
    if old['closed_at']>a['reset_started_at']:errors.append('reset_before_cleanup')
    if any(old['binding'][k]==new['binding'][k] for k in ('pid','run_id','episode')):errors.append('reused_binding')
    if not a.get('old_token_rejected'):errors.append('stale_token_not_rejected')
    if new['last_clock']-new['first_clock']<10 or new['accepted']<1:errors.append('new_game_no_progress')
    for r in rows[1:]:
        first=r.get('reset_running_seen',{});last=r.get('restart_seen',{});ep=r['episodes'][0]
        if (first.get('at',0)<a['reset_started_at'] or last.get('at',0)<a['restarted_at']
                or last.get('clock',0)<=first.get('clock',float('inf'))
                or last.get('steps',0)<=first.get('steps',float('inf'))):errors.append('peer_no_reset_progress:'+str(r['instance_id']))
        if (ep['last_clock']-last.get('clock',float('inf'))<10 or ep['accepted']<=last.get('accepted',float('inf'))):
            errors.append('peer_no_post_reset_progress:'+str(r['instance_id']))
    return errors


def run_probe(output):
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive file and directory prevent accidental reuse of another probe's evidence.
    with output.open('x',encoding='utf-8') as stream:stream.write('{}\n')
    folder=output.with_suffix('');folder.mkdir(exist_ok=False)
    cohort=uuid.uuid4().hex
    started=time.time();until=started+600
    report=dict(schema='dayuan-four-instance-probe-v1',cohort=cohort,status='running',
                started_at=started,until=until,instances=list(INSTANCES),training_actor_approved=False)
    workers=[];logs=[]
    try:
        if (ROOT/'artifacts'/'STOP').exists():raise RuntimeError('STOP blocks probe')
        if active_processes():raise RuntimeError('Active game blocks probe')
        report['display']=configure_video()
        for instance_id in INSTANCES:
            log=(folder/f'{instance_id}.log').open('wb');logs.append(log)
            process=subprocess.Popen([sys.executable,'-X','utf8','-B','-m','learning.four_instance_probe',
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
        report['episodes']=[read(folder/f'{i}.json') for i in INSTANCES]
        report['errors']=assess(report['episodes'])
        report['status']='failed' if report['errors'] else 'passed'
    except BaseException as exc:
        report.update(status='failed',error=repr(exc),error_text=str(exc),traceback=traceback.format_exc())
    finally:
        (folder/'STOP').touch()
        # Short cooperative grace before identity-checked emergency cleanup.
        deadline=time.monotonic()+5
        while any(p.poll() is None for p,_ in workers) and time.monotonic()<deadline:time.sleep(.1)
        report['cleanup_audit']={}
        report['cleanup_errors']=cleanup_owned(cohort,workers,report['cleanup_audit'],instance_ids=INSTANCES)
        for log in logs:log.close()
        try:report['episodes']=[read(folder/f'{i}.json') for i in INSTANCES]
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
    parser.add_argument('--worker',type=int,choices=INSTANCES)
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
