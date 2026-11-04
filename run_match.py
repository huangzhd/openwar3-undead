"""Match runner with optional explicit deadlines; full-map information is used only to determine terminal result."""
import argparse
import json
import time
import traceback
import hashlib
import shutil
import copy
from collections import Counter
from dataclasses import asdict
from contextlib import nullcontext
from bootstrap import ROOT
from session import Session
from run_window import DeadlineReached,ensure_time,parse_deadline,positive_minutes
from run_guard import RunGuard,RunInterrupted
from undead.controller import Controller
from undead.referee import Referee
from undead.structures import is_structure
from undead.speed_control import speed_percent,SPEEDS
from undead.debug_console import DebugConsole,ActionMeter
from undead.version import VERSION, RULES_VERSION, DISPLAY_NAME
from learning.outcome import classify_outcome

def _match_steps(speed=400,max_game_seconds=None,until=None,enemy_race=3,difficulty=3,restarted_from=None,map_alias=None,human_practice=False,practice_status=None,sparring=None,strategy_trace=False,trajectory=False,step_mode=False,instance_context=None,control='rule',teacher_trajectory=False):
    """Shared lifecycle; optional decision boundaries never pause the engine."""
    if teacher_trajectory:
        if control!='rule' or step_mode or sparring!='kfai-human' or strategy_trace:
            raise ValueError('Teacher capture requires standalone LR/KFAI rule sparring')
        trajectory=True
    policy='rule_teacher' if teacher_trajectory else 'rule' if control=='rule' else 'external_primitives'
    if step_mode and (not sparring or not trajectory):
        raise ValueError('Environment stepping requires sparring and strict trajectory recording')
    if control not in ('rule','primitives') or control != 'rule' and not step_mode:
        raise ValueError('Primitive control requires the explicit environment interface')
    if instance_context is not None and not step_mode:
        raise ValueError('Isolated instances require the environment interface')
    if human_practice and sparring:raise ValueError("Choose human practice or bot sparring")
    if strategy_trace and sparring!='kfai-human':raise ValueError('Strategy trace requires kfai-human')
    if trajectory and not sparring:raise ValueError('Trajectory recording requires P1 observer sparring')
    local_practice=human_practice or sparring is not None
    if sparring:
        from sparring import SparringSession,source_files as sparring_sources,OPPONENTS
        if sparring not in OPPONENTS or map_alias not in (None,"LR"):raise ValueError("Invalid sparring profile/map")
        enemy_race=1
    speed=speed_percent(speed)
    if human_practice and speed!=100:raise ValueError('Human practice requires 100% speed')
    if max_game_seconds is not None:
        positive_minutes(max_game_seconds/60)
    run_id=time.strftime('%Y%m%d-%H%M%S')
    if instance_context:run_id+=f'-i{instance_context.instance_id}-{time.time_ns()}'
    out=ROOT/'artifacts'/run_id
    if out.exists():
        run_id+=f'-{time.time_ns()}'
        out=ROOT/'artifacts'/run_id
    out.mkdir(parents=True,exist_ok=False)
    source=out/'source'
    source.mkdir()
    manifest={}
    practice_sources=[]
    if local_practice:
        from human_practice import HumanPracticeSession,source_files
        practice_sources=sparring_sources() if sparring else source_files()
    practice_sources=[*practice_sources,*sorted((ROOT/'learning').glob('*.py'))]
    if (ROOT/'bootstrap.py').exists():practice_sources.append(ROOT/'bootstrap.py')
    if local_practice and (ROOT/'run_guard.py').exists():practice_sources=[*practice_sources,ROOT/'run_guard.py']
    for path in [ROOT/'session.py',ROOT/'run_match.py',*practice_sources,*([ROOT/'extract_map_pool.py'] if (ROOT/'extract_map_pool.py').exists() else []),ROOT/'game_preferences.py',*([ROOT/'run_window.py'] if (ROOT/'run_window.py').exists() else []),*sorted((ROOT/'undead').glob('*.py')),*sorted((ROOT/'data').glob('*.json'))]:
        name=path.relative_to(ROOT).as_posix()
        manifest[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        dest=source/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
    fh=(out/'events.jsonl').open('w',encoding='utf-8')
    started=time.monotonic()
    result={'id':run_id,'version':VERSION,'rules_version':RULES_VERSION,'bot_name':DISPLAY_NAME,
            'policy':policy,'requested_speed':speed,
            'opponent':{'race':enemy_race,'difficulty':difficulty},'result':'unknown','reason':'not_started','until_epoch':until,'max_game_seconds':max_game_seconds}
    if restarted_from is not None:result['restarted_from']=restarted_from
    if local_practice:
        result.update(mode='human_vs_dayuan',human_player=0,controlled_player=1,fair=True,
                      opponent={'race':enemy_race,'controller':'human'},auto_restart=False)
    if sparring:
        result.update(mode="bot_vs_bot",observer_player=0,opponent_player=2,opponent={"race":1,"controller":sparring},background_supported=True)
        result.pop("human_player",None)
    def log(event,**data):
        row={'event':event,**data}
        fh.write(json.dumps(row,ensure_ascii=False)+'\n')
        fh.flush()
        if event in ('decision','new_units','item_confirmed','buy','hire','clock_waiting','clock_resumed'):
            print(json.dumps(row,ensure_ascii=False),flush=True)
    status_at=-100
    def report_practice(phase,**data):
        nonlocal status_at
        if practice_status is None:return
        now=time.monotonic()
        if phase=='running' and now-status_at<1:return
        status_at=now
        try:practice_status(phase,run_id=run_id,artifacts=str(out),**data)
        except Exception as exc:log('practice_status_error',error=repr(exc))
    session=(SparringSession(sparring,map_alias or 'LR',speed=speed,**({'instance_context':instance_context} if instance_context else {})) if sparring else HumanPracticeSession(enemy_race,map_alias or 'LR') if local_practice else
             Session(speed,enemy_race,difficulty,**({"map_alias":map_alias} if map_alias else {})))
    console=None
    meter=None
    trajectory_recorder=None
    primitive_executor=None
    point_visibility=None
    natural_confirmed=False
    guard=None
    def stopped():
        return (ROOT/'artifacts'/'STOP').exists() or bool(instance_context and instance_context.stop.exists())
    def frame(event):
        extra={}
        if primitive_executor:
            from learning.actions import SCHEMA,MAX_AGE,OPS,SCHEMA_OPS
            from learning.trees import RADIUS,MAX_SIGHTINGS,MAX_AGE as TREE_AGE
            primitive_executor.observe()
            extra=dict(action_context=dict(schema=SCHEMA,bounds=primitive_executor.bounds,
                                           supported_schemas=list(SCHEMA_OPS),supported_operations=OPS,
                                           economic_catalog=primitive_executor.costs,
                                           tree_query=dict(radius=RADIUS,max_sightings=MAX_SIGHTINGS,
                                                           sighting_max_age=TREE_AGE,life_observed=False),
                                           max_decision_age_game_seconds=MAX_AGE),
                       action_receipts=primitive_executor.drain_receipts())
        return dict(event=event,run_id=run_id,pid=g.pid,epoch=practice_epoch,player=1,
                    observation_id=trajectory_recorder.observation_id,
                    observation=copy.deepcopy(trajectory_recorder.last_observation),
                    receipts=trajectory_recorder.drain_receipts(),**extra)
    def validate_command(command):
        if control == 'rule':
            if command!='rule_tick':raise ValueError('Expected rule_tick environment step')
        else:
            from learning.actions import validate
            validate(command)
    def timed(name):return guard.stage(name) if guard is not None else nullcontext()
    if strategy_trace:
        session.strategy_trace_path=out/'opponent-strategy.jsonl'
        result['opponent_strategy_trace']='experimental_observer_only'
    if local_practice:session.startup_log=log
    try:
        if local_practice:report_practice('launching')
        ensure_time(until)
        g=session.start(until=until) if until is not None else session.start()
        result['launch_settings']=getattr(session,'settings',{})
        if sparring:
            from learning.evidence import freeze_contract
            ready=g.snapshot(max_age=0)
            freeze_contract(ROOT,out,manifest,result['launch_settings'],rules_version=RULES_VERSION,
                            opponent=sparring,pid=g.pid,epoch=ready.epoch,control='teacher' if teacher_trajectory else control)
        log('match_settings',settings=result['launch_settings'])
        spawn=result['launch_settings'].get('own_start_sample')
        if spawn is not None:
            (out/'spawn-audit.json').write_text(json.dumps(spawn,indent=2),encoding='utf-8')
        bot=Controller(g,log,enemy_race) if control == 'rule' else None
        if sparring:session.start_opponent(log)
        if bot is not None and getattr(session,'map_catalog',None):
            catalog=session.map_catalog
            bot.creeping.catalog=catalog['camps']
            bot.creeping.map_alias=result['launch_settings'].get('map_alias')
            bot.start_search.camps=catalog['camps']
            bot.critter_search.spawns=catalog['critters']
            bot.tavern_sites=[(b['x'],b['y']) for b in catalog.get('neutral_buildings',[]) if b['code']=='ntav']
            log('map_catalog_bound',name=catalog['name'],map_sha256=catalog['map_sha256'],
                camps=len(catalog['camps']),critters=len(catalog['critters']))
        if local_practice:
            # Human input and the camera belong to P0. Do not install bot HUD controls.
            meter=ActionMeter(g,trace=lambda event,**data:log(event.replace('attachment_','practice_'),**data))
            practice_epoch=g.snapshot(max_age=0).epoch
            report_practice('running',clock=g.clock(),background=False)
        else:console=DebugConsole(g,log)
        if trajectory:
            from learning.trajectory import TrajectoryRecorder,PointVisibility
            from undead.game_view import Game
            point_visibility=PointVisibility(Game(pid=g.pid,fair=False),g.pid,practice_epoch)
            # Public map candidates only: discard slot IDs, never label the enemy's spawn.
            public_points=[(p['x'],p['y']) for p in session.map_catalog.get('starts',[])]
            trajectory_recorder=TrajectoryRecorder(g,out/'trajectory.jsonl',visibility=point_visibility,
                                                    public_points=public_points,capture_receipts=step_mode,
                                                    policy=policy)
            result['trajectory']='experimental_p1_whitelist_v2' if control == 'primitives' else 'experimental_p1_whitelist_v1'
            if teacher_trajectory:
                result['trajectory']='teacher_tick_p1_v2'
                bot.teacher_recorder=trajectory_recorder
                trajectory_recorder.execution_state=lambda:bot.action.name
            if control == 'primitives':
                from learning.actions import PrimitiveExecutor
                primitive_executor=PrimitiveExecutor(g,trajectory_recorder,out/'primitive-actions.jsonl')
                result['control']='external_primitives'
        if local_practice and (trajectory or max_game_seconds is not None or until is not None):
            guard=RunGuard(g,out/'runtime-timing.jsonl',game_limit=max_game_seconds,until=until,
                           stage_seconds=2.0 if max_game_seconds is not None or until is not None else None)
            clients=[('P1',g),('P1_visibility',getattr(getattr(g,'_player_visibility',None),'client',None)),
                     ('P2',getattr(session,'opponent_game',None)),
                     ('P2_visibility',getattr(getattr(getattr(session,'opponent_game',None),'_player_visibility',None),'client',None)),
                     ('strategy_trace',getattr(getattr(session,'strategy_trace',None),'game',None)),
                     ('trajectory_visibility',getattr(point_visibility,'client',None))]
            for label,client in clients:
                if client is not None:guard.attach(client,label)
            result['runtime_guard']='cooperative_stages_world_reads_native_wait_cap_v1'
        speed_control=console.speed if console else None
        last_pub=None
        last_speed=None
        result['speed_history']=[]
        published=time.monotonic()
        moved=time.monotonic()
        last_clock=None
        last_own_counts=None
        clock_waiting=False
        last_foreground=None
        background_since=None
        missing_snapshot_since=None
        referee=Referee()
        check_at=-100
        check_wall=-100
        snapshot_at=-100
        if step_mode:
            decision_frame=frame('ready')
            command=yield decision_frame
            validate_command(command)
        while True:
            ensure_time(until)
            if local_practice:
                if stopped():
                    result.update(result='aborted',reason='user_stop');break
                if not session.alive():
                    result.update(result='aborted',reason='human_game_closed');break
            # A dead process can leave readable but stale shared memory. Check
            # ownership/liveness before consulting the guard or any engine API.
            if guard:guard.checkpoint()
            if local_practice:
                with timed('foreground_check'):active=session.active()
                if sparring and active != last_foreground:
                    log('foreground_changed',foreground=active,wall_time=time.time(),
                        clock=guard.clock if guard else last_clock,controller_continues=True)
                    last_foreground=active
                    background_since=None if active else time.monotonic()
                if not active and not sparring:
                    # Native single-player fullscreen pauses when backgrounded.
                    published=moved=time.monotonic()
                    report_practice('running',clock=last_clock,background=True)
                    time.sleep(.2);continue
            with timed('snapshot'):s=g.snapshot(max_age=0)
            if s is None:
                if local_practice:
                    if sparring:
                        if missing_snapshot_since is None:missing_snapshot_since=time.monotonic()
                        if time.monotonic()-missing_snapshot_since>=10:
                            raise RuntimeError('Required sparring snapshot missing for 10s: P1')
                    time.sleep(.2);continue
                raise RuntimeError('Missing snapshot')
            if local_practice and (not s.in_game or s.epoch!=practice_epoch or s.me!=1):
                result.update(result='aborted',reason='practice_match_changed');break
            if local_practice:
                with timed('observer_snapshot'):practice_raw=g.world.read()
                if practice_raw is None:
                    if sparring:
                        if missing_snapshot_since is None:missing_snapshot_since=time.monotonic()
                        if time.monotonic()-missing_snapshot_since>=10:
                            raise RuntimeError('Required sparring snapshot missing for 10s: observer')
                    time.sleep(.2);continue
                if not practice_raw.in_game or practice_raw.epoch!=practice_epoch or practice_raw.me!=0:
                    result.update(result='aborted',reason='practice_match_changed');break
                missing_snapshot_since=None
                report_practice('running',clock=s.clock,background=not active)
            if trajectory_recorder:
                with timed('trajectory_observation'):trajectory_recorder.observe()
            if speed_control:speed_control.observe(s)
            if bot is not None:
                with timed('controller_events'):bot.observe_events(g.events())
            if s.speed_pct!=last_speed:
                last_speed=s.speed_pct
                result['speed_history'].append({'clock':s.clock,'percent':last_speed})
                log('speed_changed',clock=s.clock,percent=last_speed)
            if stopped():
                result.update(result='aborted',reason='user_stop')
                break
            if s.publish_count!=last_pub:
                last_pub,published=s.publish_count,time.monotonic()
            elif not human_practice and time.monotonic()-published>10:
                raise RuntimeError('World publication stopped')
            # The engine can freeze the simulation immediately after the final kill.
            # Judge by wall time as well, before the pause branch skips strategy orders.
            wall_now=time.monotonic()
            if s.clock-check_at>=2 or wall_now-check_wall>=.5:
                check_at,check_wall=s.clock,wall_now
                with timed('referee'):terminal=referee.observe(practice_raw if local_practice else g.world.read(),s.me,is_structure)
                if terminal:
                    natural_confirmed=True
                    result.update(result=terminal[0],reason=terminal[1])
                    log('terminal_confirmed',clock=s.clock,result=terminal[0],reason=terminal[1])
                    break
            action=getattr(console,'match_action',None)
            if action in ('surrender','restart'):
                result.update(result='loss' if action=='surrender' else 'aborted',
                              reason='manual_surrender' if action=='surrender' else 'manual_restart')
                if action=='restart':result['restart_speed']=s.speed_pct
                log('match_control_committed',clock=s.clock,action=action,source='manual_panel')
                break
            if s.clock!=last_clock:
                if clock_waiting:
                    log('clock_resumed',clock=s.clock,waited_wall_seconds=round(time.monotonic()-moved,2))
                    clock_waiting=False
                last_clock,moved=s.clock,time.monotonic()
            else:
                if sparring and not active and time.monotonic()-max(moved,background_since)>15:
                    raise RuntimeError('Background game clock stopped for 15s')
                # Menu/user pauses do not advance simulation. Keep UI/STOP responsive,
                # skip duplicate orders; explicit deadlines and STOP still apply.
                if not clock_waiting and time.monotonic()-moved>3:
                    clock_waiting=True
                    log('clock_waiting',clock=s.clock,reason='clock_not_advancing')
                if console:console.observe(s,bot,paused=clock_waiting)
                time.sleep(.2)
                continue
            if max_game_seconds is not None and s.clock>=max_game_seconds:
                result.update(result='timeout',reason='game_time_limit')
                break
            if sparring:
                with timed('opponent_tick'):opponent_ready=session.tick_opponent(practice_epoch)
                if not opponent_ready:
                    time.sleep(.2);continue
            if trajectory_recorder:
                with timed('trajectory_points'):trajectory_recorder.observe_points()
            if primitive_executor:
                with timed('primitive_action'):
                    primitive_executor.execute(command,decision_frame['observation'],decision_frame['observation_id'])
            else:
                with timed('controller_tick'), (trajectory_recorder.teacher_tick() if teacher_trajectory else nullcontext()):bot.tick()
            if console:console.observe(s,bot)
            if s.clock-snapshot_at>=15:
                snapshot_at=s.clock
                with timed('summary'):
                    own=Counter(u.type for u in g.my_units())
                    last_own_counts=dict(own)
                    log('summary',clock=s.clock,resources=g.resources(),units=dict(own),situation=asdict(bot.situation) if bot else None,
                        heroes=[{'type':h.type,'level':h.level,'hp':h.hp,'mana':h.mana,'inventory':g.inventory(h),'abilities':g.abilities(h)} for h in g.my_heroes()],
                        own_upgrades=g.tech_many(['Rura','Rucr','Ruwb']),
                        production=[{'type':b.type,'kind':p.kind,'queue':p.queue,'progress':p.progress} for b,p in g.all_production('me')])
            # At 4x, the usual idle sleep alone consumes 0.8 game seconds.
            fast_opening=sparring and bot is not None and speed>=400 and s.clock<76
            time.sleep(.025 if fast_opening else .2)
            if step_mode:
                with timed('environment_observation'):trajectory_recorder.observe()
                decision_frame=frame('step')
                command=yield decision_frame
                validate_command(command)
        disconnected=local_practice and (not session.alive() or result.get('reason')=='practice_match_changed')
        result['game_seconds']=(guard.clock if guard else last_clock) if disconnected else g.clock()
        result['units_at_end']=last_own_counts if disconnected else dict(Counter(u.type for u in g.my_units()))
        if disconnected:result['units_at_end_basis']='last_summary_before_process_exit'
        if meter:result.update(meter.summary(result['game_seconds']))
    except GeneratorExit:
        result.update(result='aborted',reason='environment_close',
                      game_seconds=guard.clock if guard is not None else None)
    except RunInterrupted as exc:
        result.update(result='aborted' if exc.reason in ('automation_deadline','game_epoch_changed','environment_close') else 'timeout',
                      reason=exc.reason,game_seconds=exc.clock)
        if meter:result.update(meter.summary(exc.clock))
    except DeadlineReached:
        result.update(result='aborted',reason='automation_deadline')
        if guard is not None:result['game_seconds']=guard.clock
        elif session.game is not None:
            result['game_seconds']=session.game.clock()
    except Exception as exc:
        result.update(result='error',reason=repr(exc))
        traceback.print_exc()
    finally:
        # A failed launch still needs its map identity/configuration for stage 0.
        result.setdefault('launch_settings',dict(getattr(session,'settings',{})))
        if step_mode and trajectory_recorder is not None:
            try:result['environment_final_frame']=frame('finished')
            except Exception as exc:result['environment_frame_cleanup_error']=repr(exc)
        if guard:
            try:guard.close()
            except Exception as exc:result['runtime_guard_cleanup_error']=repr(exc)
        if primitive_executor:
            try:primitive_executor.close()
            except Exception as exc:result['primitive_cleanup_error']=repr(exc)
        if trajectory_recorder:
            try:trajectory_recorder.finish(result['result'],result['reason'],natural_confirmed=natural_confirmed)
            except Exception as exc:result['trajectory_cleanup_error']=repr(exc)
        if point_visibility:
            try:point_visibility.close()
            except Exception as exc:result['visibility_cleanup_error']=repr(exc)
        if meter is not None:
            try:meter.close()
            except Exception as exc:result['meter_cleanup_error']=repr(exc)
        if console is not None:
            try:console.close()
            except Exception as exc:result['ui_cleanup_error']=repr(exc)
        try:
            session.stop()
        except Exception as exc:
            result['cleanup_error']=repr(exc)
        result['termination']=classify_outcome(result['result'],result['reason'],natural_confirmed=natural_confirmed)
        if sparring:
            from learning.evidence import freeze_contract,audit_sources
            try:
                if not (out/'interface-contract.json').exists():
                    freeze_contract(ROOT,out,manifest,result['launch_settings'],rules_version=RULES_VERSION,opponent=sparring,control='teacher' if teacher_trajectory else control)
                audit_sources(ROOT,out,manifest,**({'instance_context':instance_context} if instance_context else {}))
            except Exception as exc:result['evidence_error']=repr(exc)
        result['wall_seconds']=round(time.monotonic()-started,2)
        fh.close()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


def run_match(speed=400,max_game_seconds=None,until=None,enemy_race=3,difficulty=3,restarted_from=None,map_alias=None,human_practice=False,practice_status=None,sparring=None,strategy_trace=False,trajectory=False,teacher_trajectory=False):
    """Run the same lifecycle continuously for the existing CLI/panels."""
    runner=_match_steps(speed,max_game_seconds,until,enemy_race,difficulty,restarted_from,map_alias,
                        human_practice,practice_status,sparring,strategy_trace,trajectory,teacher_trajectory=teacher_trajectory)
    try:
        while True:next(runner)
    except StopIteration as done:
        return done.value

def play_matches(speed=400,max_game_seconds=None,until=None,enemy_race=3,difficulty=3,map_alias=None):
    """Each manual restart consumes one click, only after the old session closes."""
    previous=None
    while True:
        kwargs={'restarted_from':previous} if previous is not None else {}
        if map_alias:kwargs['map_alias']=map_alias
        result=run_match(speed,max_game_seconds,until,enemy_race,difficulty,**kwargs)
        if result.get('reason')!='manual_restart':return result
        blocked=None
        if result.get('cleanup_error') or result.get('ui_cleanup_error'):blocked='cleanup_failed'
        elif (ROOT/'artifacts/STOP').exists():blocked='user_stop'
        else:
            try:ensure_time(until)
            except DeadlineReached:blocked='automation_deadline'
        if blocked is None:
            record=ROOT/'artifacts/session.json'
            try:
                if record.exists() and any(Session.matches(row) for row in json.loads(record.read_text(encoding='utf-8')).get('processes',[])):
                    blocked='previous_session_still_running'
            except Exception as exc:blocked='session_check_failed: '+repr(exc)
        if blocked:
            result['restart_blocked']=blocked
            (ROOT/'artifacts'/result['id']/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'event':'restart_blocked','reason':blocked},ensure_ascii=False),flush=True)
            return result
        previous=result['id'];speed=speed_percent(result['restart_speed'])

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--speed',type=speed_percent,choices=SPEEDS,default=400)
    parser.add_argument('--minutes',type=positive_minutes,default=None,help='Optional game-time limit; default is no limit')
    parser.add_argument('--until',type=parse_deadline,help='Absolute ISO cutoff, including timezone offset')
    parser.add_argument('--enemy-race',type=int,choices=(0,1,2,3,4),default=3)
    parser.add_argument('--map',dest='map_alias',choices=('AZ','AL','CH','LR','NI','TH','TR','TM'))
    parser.add_argument('--difficulty',type=int,choices=(2,3,4),default=3)
    args=parser.parse_args()
    r=play_matches(args.speed,args.minutes*60 if args.minutes is not None else None,args.until,args.enemy_race,args.difficulty,map_alias=args.map_alias)
    raise SystemExit(1 if r['result']=='error' else 0)
