"""Bounded game-process failure and one explicit reset beside a live peer."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil
from bootstrap import ROOT
from attach_match import atomic_json
from learning.environment import RuleEnvironment
from learning.parallel_probe import read, cleanup_owned
from machine_start import active_processes
from practice_video import configure_video
from session import Session


def inject_game_exit(instance_id, cohort, binding, publish=lambda report:None):
    report=dict(method='owned_launcher_job_exit',stage='validate',requested_at=time.time(),exit_confirmed=False)
    def save():publish(dict(report))
    save()
    try:
        if instance_id != 81:raise ValueError('Only the designated fault instance may be terminated')
        base=ROOT/'artifacts'/'instances'/str(instance_id)
        owner=read(base/'owner.json');record=read(base/'session.json')
        current=psutil.Process()
        identity=dict(pid=current.pid,created=current.create_time(),name=current.name())
        report['worker']=identity
        if (not owner or owner.get('closed') or owner.get('instance_id')!=instance_id
                or owner.get('cohort')!=cohort or owner.get('worker')!=identity):
            raise RuntimeError('Fault worker ownership is unconfirmed')
        rows=record.get('processes',[]) if record else []
        games=[row for row in rows if row.get('pid')==binding['pid']]
        launchers=[row for row in rows if row.get('name','').lower()=='war3_launch.exe']
        if (len(games)!=1 or games[0].get('name','').lower()!=f'war3-{instance_id}.exe'
                or games[0]['pid']==current.pid or not Session.matches(games[0])):
            raise RuntimeError('Fault game identity is unconfirmed')
        if (len(launchers)!=1 or launchers[0]['pid'] in (current.pid,games[0]['pid'])
                or not Session.matches(launchers[0])):
            raise RuntimeError('Fault launcher identity is unconfirmed')
        game,launcher=games[0],launchers[0]
        target=psutil.Process(launcher['pid'])
        if target.create_time()!=launcher['created'] or target.name().lower()!=launcher['name'].lower():
            raise RuntimeError('Fault launcher identity changed')
        game_process=psutil.Process(game['pid'])
        if (game_process.create_time()!=game['created'] or game_process.name().lower()!=game['name'].lower()
                or target.ppid()!=current.pid or game_process.ppid()!=launcher['pid']):
            raise RuntimeError('Fault launcher/game parent chain is unconfirmed')
        report.update(game=game,launcher=launcher,stage='terminate_launcher');save()
        target.kill()
        report['stage']='wait_launcher';save()
        target.wait(timeout=5)
        report['stage']='wait_game';save()
        deadline=time.monotonic()+5
        while True:
            try:alive=Session.matches(game)
            except psutil.Error as exc:
                alive=True;report['last_unknown']=repr(exc)
            if not alive:break
            if time.monotonic()>=deadline:raise RuntimeError('Game exit after launcher termination is unconfirmed')
            time.sleep(.1)
        report.update(stage='confirmed',exited_at=time.time(),exit_confirmed=True);save()
        return report
    except BaseException as exc:
        report['error']=repr(exc);save();raise


def worker(instance_id, cohort, folder, until):
    folder=Path(folder);path=folder/f'{instance_id}.json';peer=folder/f'{82 if instance_id==81 else 81}.json'
    until=min(until,time.time()+240)
    state=dict(instance_id=instance_id,cohort=cohort,status='starting',episodes=[],resets=0)
    env=RuleEnvironment(instance_id=instance_id,cohort=cohort)
    def save():atomic_json(path,state)
    def check():
        if time.time()>=until:raise TimeoutError('Worker deadline')
        if any(p.exists() for p in (ROOT/'artifacts'/'STOP',folder/'STOP',
                                   ROOT/'artifacts'/'instances'/str(instance_id)/'STOP')):
            raise RuntimeError('Probe stopped')
    def begin():
        check();state['resets']+=1
        frame=env.reset(game_seconds=600,wall_seconds=240,until=until)
        if frame['done']:
            state['pending_reset_result']=env.result()
            raise RuntimeError('Episode ended before ready')
        ep=dict(binding=frame['token'],ready_at=time.time(),first_clock=frame['observation']['clock'],
                last_clock=frame['observation']['clock'],steps=0,accepted=0)
        state['episodes'].append(ep);state['current']=ep;state['status']='ready';save()
        return frame,ep
    def step(frame,ep):
        check();new=env.step(dict(kind='rule_tick',token=frame['token']))
        if not new['done']:
            for key in ('instance','episode','run_id','pid','epoch'):
                if new['token'][key]!=ep['binding'][key]:raise RuntimeError('Live binding changed')
            ep['steps']+=1;ep['last_clock']=new['observation']['clock']
            ep['accepted']+=sum(r['accepted'] is True for r in new['receipts'])
        save();return new
    save()
    try:
        frame,ep=begin()
        for _ in range(100000):
            check();other=read(peer)
            if other and other['status']=='failed':raise RuntimeError('Peer failed')
            if other and other.get('current'):
                remote=other['current']
                if 'overlap_clock' not in ep:ep['overlap_clock']=ep['last_clock'];save()
                if instance_id==81 and len(state['episodes'])==1:
                    if (ep['last_clock']>ep['overlap_clock'] and remote['last_clock']>remote.get('overlap_clock',float('inf'))):
                        if 'fault_pending_at' not in state:state['fault_pending_at']=time.time();save()
                        if other.get('fault_seen'):
                            state['peer_before_fault']=dict(remote)
                            old_token=frame['token']
                            def publish_fault(report):state['fault']=report;save()
                            state['fault']=inject_game_exit(instance_id,cohort,old_token,publish_fault);save()
                            final=step(frame,ep);result=env.result()
                            ep.update(result=result,closed_at=time.time())
                            if (not final['done'] or not result or not result['cleanup_confirmed']
                                    or result['termination']['classification']!='process_exit'
                                    or result['termination']['reward'] is not None):
                                raise RuntimeError('Game exit did not produce a clean process_exit result')
                            state['reset_started_at']=time.time();state['status']='resetting';save()
                            frame,ep=begin()
                            if any(frame['token'][key]==old_token[key] for key in ('pid','run_id','episode')):
                                raise RuntimeError('Reset reused a prior game binding')
                            fresh=frame['token']
                            try:env.step(dict(kind='rule_tick',token=old_token))
                            except ValueError:pass
                            else:raise RuntimeError('Old game token accepted after reset')
                            if env.observe()['token']!=fresh:raise RuntimeError('Old token consumed the new token')
                            state['old_token_rejected']=True;state['restarted_at']=time.time();save()
                            continue
                elif instance_id==82:
                    if other.get('fault_pending_at') and 'fault_seen' not in state:
                        state['fault_seen']=dict(at=time.time(),clock=ep['last_clock'],steps=ep['steps'],accepted=ep['accepted']);save()
                    if other.get('fault',{}).get('exit_confirmed') and 'fault_observed' not in state:
                        state['fault_observed']=dict(at=time.time(),clock=ep['last_clock'],steps=ep['steps'],accepted=ep['accepted']);save()
                    if other.get('restarted_at') and 'restart_seen' not in state:
                        state['restart_seen']=dict(at=time.time(),clock=ep['last_clock'],steps=ep['steps'],accepted=ep['accepted']);save()
                    marker=state.get('restart_seen')
                    if (marker and ep['last_clock']-marker['clock']>=5 and ep['accepted']>marker['accepted']):
                        state['post_restart_progress']=True;save()
                    if other['status']=='closed' and state.get('post_restart_progress'):break
                elif instance_id==81 and len(state['episodes'])==2:
                    if (ep['last_clock']-ep['first_clock']>=5 and ep['accepted']>0
                            and other.get('post_restart_progress')):break
            frame=step(frame,ep)
            if frame['done']:raise RuntimeError('Unexpected episode termination')
        else:raise RuntimeError('Worker step budget exhausted')
        state.update(status='closing',close_started_at=time.time());save()
        ep['result']=env.close();ep['closed_at']=time.time()
        if not ep['result'] or not ep['result']['cleanup_confirmed']:raise RuntimeError('Final cleanup unconfirmed')
        state.update(status='closed',closed_at=time.time())
    except BaseException as exc:state.update(status='failed',error=repr(exc))
    finally:
        try:
            result=env.close()
            if result and state['episodes']:
                if state['resets']>len(state['episodes']):state['pending_reset_result']=result
                else:state['episodes'][-1]['result']=result
        except BaseException as exc:state.update(status='failed',cleanup_error=repr(exc))
        save()
    return 0 if state['status']=='closed' else 1


def assess(rows):
    if len(rows)!=2 or any(not r or r.get('status')!='closed' for r in rows):return ['workers_not_cleanly_closed']
    a,b=rows;errors=[]
    if len(a['episodes'])!=2 or len(b['episodes'])!=1 or a['resets']!=2 or b['resets']!=1:return ['wrong_episode_count']
    old,new=a['episodes'];peer=b['episodes'][0]
    if any(not e.get('result',{}).get('cleanup_confirmed') for e in (old,new,peer)):errors.append('cleanup_unconfirmed')
    if not a.get('fault',{}).get('exit_confirmed'):errors.append('fault_not_confirmed')
    if old['result']['termination'].get('classification')!='process_exit' or old['result']['termination'].get('reward') is not None:errors.append('incorrect_fault_result')
    if old['closed_at']>a['reset_started_at']:errors.append('reset_before_cleanup')
    if any(old['binding'][k]==new['binding'][k] for k in ('pid','run_id','episode')):errors.append('reused_binding')
    if not a.get('old_token_rejected'):errors.append('stale_token_not_rejected')
    if new['last_clock']-new['first_clock']<5 or new['accepted']<1:errors.append('new_game_no_progress')
    fault=b.get('fault_observed',{});restart=b.get('restart_seen',{})
    if fault.get('at',0)<a['fault'].get('exited_at',float('inf')):errors.append('fault_baseline_before_exit')
    if (restart.get('clock',0)<=fault.get('clock',float('inf')) or restart.get('steps',0)<=fault.get('steps',float('inf'))
            or restart.get('accepted',0)<=fault.get('accepted',float('inf'))):errors.append('peer_no_progress_during_recovery')
    if (peer['last_clock']-restart.get('clock',float('inf'))<5 or peer['accepted']<=restart.get('accepted',float('inf'))):errors.append('peer_no_progress_after_recovery')
    if peer['binding']['pid'] in (old['binding']['pid'],new['binding']['pid']):errors.append('peer_binding_collision')
    return errors


def run_probe(output):
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive file and directory prevent accidental reuse of another probe's evidence.
    with output.open('x',encoding='utf-8') as stream:stream.write('{}\n')
    folder=output.with_suffix('');folder.mkdir(exist_ok=False)
    cohort=uuid.uuid4().hex
    started=time.time();until=started+300
    report=dict(schema='dayuan-recovery-probe-v1',cohort=cohort,status='running',
                started_at=started,until=until,instances=[81,82],training_actor_approved=False)
    workers=[];logs=[]
    try:
        if (ROOT/'artifacts'/'STOP').exists():raise RuntimeError('STOP blocks probe')
        if active_processes():raise RuntimeError('Active game blocks probe')
        report['display']=configure_video()
        for instance_id in (81,82):
            log=(folder/f'{instance_id}.log').open('wb');logs.append(log)
            process=subprocess.Popen([sys.executable,'-X','utf8','-B','-m','learning.recovery_probe',
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
