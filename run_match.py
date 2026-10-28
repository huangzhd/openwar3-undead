"""Match runner with optional explicit deadlines; full-map information is used only to determine terminal result."""
import argparse
import json
import time
import traceback
import hashlib
import shutil
from collections import Counter
from dataclasses import asdict
from bootstrap import ROOT
from session import Session
from run_window import DeadlineReached,ensure_time,parse_deadline,positive_minutes
from undead.controller import Controller
from undead.referee import Referee
from undead.structures import is_structure
from undead.speed_control import speed_percent,SPEEDS
from undead.debug_console import DebugConsole,ActionMeter
from undead.version import VERSION, RULES_VERSION, DISPLAY_NAME

def run_match(speed=400,max_game_seconds=None,until=None,enemy_race=3,difficulty=3,restarted_from=None,map_alias=None,human_practice=False,practice_status=None,sparring=None):
    if human_practice and sparring:raise ValueError("Choose human practice or bot sparring")
    local_practice=human_practice or sparring is not None
    if sparring:
        from sparring import SparringSession,source_files as sparring_sources
        from human_opponents import PROFILES
        if sparring not in PROFILES or map_alias not in (None,"LR"):raise ValueError("Invalid sparring profile/map")
        enemy_race=1
    speed=speed_percent(speed)
    if local_practice and speed!=100:raise ValueError('Human practice requires 100% speed')
    if max_game_seconds is not None:
        positive_minutes(max_game_seconds/60)
    run_id=time.strftime('%Y%m%d-%H%M%S')
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
    for path in [ROOT/'session.py',ROOT/'run_match.py',*practice_sources,*([ROOT/'extract_map_pool.py'] if (ROOT/'extract_map_pool.py').exists() else []),ROOT/'game_preferences.py',*([ROOT/'run_window.py'] if (ROOT/'run_window.py').exists() else []),*sorted((ROOT/'undead').glob('*.py')),*sorted((ROOT/'data').glob('*.json'))]:
        name=path.relative_to(ROOT).as_posix()
        manifest[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        dest=source/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
    fh=(out/'events.jsonl').open('w',encoding='utf-8')
    started=time.monotonic()
    result={'id':run_id,'version':VERSION,'rules_version':RULES_VERSION,'bot_name':DISPLAY_NAME,'policy':'rule','requested_speed':speed,
            'opponent':{'race':enemy_race,'difficulty':difficulty},'result':'unknown','reason':'not_started','until_epoch':until,'max_game_seconds':max_game_seconds}
    if restarted_from is not None:result['restarted_from']=restarted_from
    if local_practice:
        result.update(mode='human_vs_dayuan',human_player=0,controlled_player=1,fair=True,
                      opponent={'race':enemy_race,'controller':'human'},auto_restart=False)
    if sparring:
        result.update(mode="bot_vs_bot",observer_player=0,opponent_player=2,opponent={"race":1,"controller":sparring},background_supported=False)
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
    session=(SparringSession(sparring,map_alias or 'LR') if sparring else HumanPracticeSession(enemy_race,map_alias or 'LR') if local_practice else
             Session(speed,enemy_race,difficulty,**({"map_alias":map_alias} if map_alias else {})))
    console=None
    meter=None
    try:
        if local_practice:report_practice('launching')
        ensure_time(until)
        g=session.start(until=until) if until is not None else session.start()
        result['launch_settings']=getattr(session,'settings',{})
        log('match_settings',settings=result['launch_settings'])
        spawn=result['launch_settings'].get('own_start_sample')
        if spawn is not None:
            (out/'spawn-audit.json').write_text(json.dumps(spawn,indent=2),encoding='utf-8')
        bot=Controller(g,log,enemy_race)
        if sparring:session.start_opponent(log)
        if getattr(session,'map_catalog',None):
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
        speed_control=console.speed if console else None
        last_pub=None
        last_speed=None
        result['speed_history']=[]
        published=time.monotonic()
        moved=time.monotonic()
        last_clock=None
        last_own_counts=None
        clock_waiting=False
        referee=Referee()
        check_at=-100
        check_wall=-100
        snapshot_at=-100
        while True:
            ensure_time(until)
            if local_practice:
                if (ROOT/'artifacts'/'STOP').exists():
                    result.update(result='aborted',reason='user_stop');break
                if not session.alive():
                    result.update(result='aborted',reason='human_game_closed');break
                if not session.active():
                    # Native single-player fullscreen pauses when backgrounded.
                    published=moved=time.monotonic()
                    report_practice('running',clock=last_clock,background=True)
                    time.sleep(.2);continue
            s=g.snapshot(max_age=0)
            if s is None:
                if local_practice:
                    time.sleep(.2);continue
                raise RuntimeError('Missing snapshot')
            if local_practice and (not s.in_game or s.epoch!=practice_epoch or s.me!=1):
                result.update(result='aborted',reason='practice_match_changed');break
            if local_practice:
                practice_raw=g.world.read()
                if practice_raw is None:
                    time.sleep(.2);continue
                if not practice_raw.in_game or practice_raw.epoch!=practice_epoch or practice_raw.me!=0:
                    result.update(result='aborted',reason='practice_match_changed');break
                report_practice('running',clock=s.clock,background=False)
            if speed_control:speed_control.observe(s)
            bot.observe_events(g.events())  # Fair death evidence and manual UI event dispatch.
            if s.speed_pct!=last_speed:
                last_speed=s.speed_pct
                result['speed_history'].append({'clock':s.clock,'percent':last_speed})
                log('speed_changed',clock=s.clock,percent=last_speed)
            if (ROOT/'artifacts'/'STOP').exists():
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
                terminal=referee.observe(practice_raw if local_practice else g.world.read(),s.me,is_structure)
                if terminal:
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
            if sparring and not session.tick_opponent(practice_epoch):
                time.sleep(.2);continue
            bot.tick()
            if console:console.observe(s,bot)
            if s.clock-snapshot_at>=15:
                snapshot_at=s.clock
                own=Counter(u.type for u in g.my_units())
                last_own_counts=dict(own)
                log('summary',clock=s.clock,resources=g.resources(),units=dict(own),situation=asdict(bot.situation),
                    heroes=[{'type':h.type,'level':h.level,'hp':h.hp,'mana':h.mana,'inventory':g.inventory(h),'abilities':g.abilities(h)} for h in g.my_heroes()],
                    own_upgrades=g.tech_many(['Rura','Rucr','Ruwb']),
                    production=[{'type':b.type,'kind':p.kind,'queue':p.queue,'progress':p.progress} for b,p in g.all_production('me')])
            time.sleep(.2)
        disconnected=local_practice and (not session.alive() or result.get('reason')=='practice_match_changed')
        result['game_seconds']=last_clock if disconnected else g.clock()
        result['units_at_end']=last_own_counts if disconnected else dict(Counter(u.type for u in g.my_units()))
        if disconnected:result['units_at_end_basis']='last_summary_before_process_exit'
        if meter:result.update(meter.summary(result['game_seconds']))
    except DeadlineReached:
        result.update(result='aborted',reason='automation_deadline')
        if session.game is not None:
            result['game_seconds']=session.game.clock()
    except Exception as exc:
        result.update(result='error',reason=repr(exc))
        traceback.print_exc()
    finally:
        if meter is not None:meter.close()
        if console is not None:
            try:console.close()
            except Exception as exc:result['ui_cleanup_error']=repr(exc)
        try:
            session.stop()
        except Exception as exc:
            result['cleanup_error']=repr(exc)
        result['wall_seconds']=round(time.monotonic()-started,2)
        fh.close()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result

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
