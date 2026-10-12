"""Local commands; gameplay is driven through the API, never desktop automation."""
import argparse
import json
from pathlib import Path
from bootstrap import ROOT, UPSTREAM
from run_window import parse_deadline,positive_minutes
from undead.speed_control import speed_percent,SPEEDS


def main():
    parser=argparse.ArgumentParser(description='Undead tech-fiend bot (P1 development build)')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check',help='Check local files without launching the game')
    autoload=sub.add_parser('auto-load',help='Experimental runtime loader for the next new KK practice game')
    autoload.add_argument('--auto-resume',action='store_true',help='Start bot orders after verified attachment; default pauses')
    autoload.add_argument('--watch-restarts',action='store_true',help='Handle subsequent newly launched KK games until stopped')
    autoload.add_argument('--wait-seconds',type=int,default=1200)
    autoload.add_argument('--enemy-race',type=int,choices=(1,2,3,4),default=3)
    sub.add_parser('auto-load-build',help='Compile and verify the x86 helper without loading it into any game')
    sub.add_parser('auto-load-stop',help='Stop the watcher and its bot; leave the game running')
    sub.add_parser('auto-load-status',help='Read startup watcher status')
    retry=sub.add_parser('auto-load-retry',help='Explicitly retry the exact existing game from a prior target record, initially paused')
    retry.add_argument('--target-record',type=Path,required=True)
    inspect=sub.add_parser('attach-check',help='Read-only scan for an existing supported game bridge')
    inspect.add_argument('--pid',type=int,help='Inspect a specific game PID; omit to list candidates')
    attach=sub.add_parser('attach',help='Connect to an existing runtime, initially paused; never launch/inject')
    attach.add_argument('--pid',type=int,required=True)
    attach.add_argument('--enemy-race',type=int,choices=(1,2,3,4),default=3)
    for command in ('attach-pause','attach-resume','attach-release','attach-status'):
        sub.add_parser(command,help='Control or inspect the attached bot without closing the game')
    play=sub.add_parser('play',help='Play a local rule-controlled match')
    play.add_argument('--speed',type=speed_percent,choices=SPEEDS,default=400)
    play.add_argument('--minutes',type=positive_minutes,default=None,help='Optional game-time limit; default is no limit')
    play.add_argument('--until',type=parse_deadline,help='Absolute ISO cutoff, including timezone offset')
    play.add_argument('--enemy-race',type=int,choices=(0,1,2,3,4),default=3,help='0 uniform random; 1 human, 2 orc, 3 undead, 4 night elf')
    play.add_argument('--map',dest='map_alias',choices=('AZ','AL','CH','LR','NI','TH','TR','TM'))
    play.add_argument('--difficulty',type=int,choices=(2,3,4),default=3,help='2 easy, 3 normal, 4 insane')
    sub.add_parser('stop',help='Request graceful stop of the project match')
    args=parser.parse_args()
    if args.command.startswith('auto-load'):
        from auto_load import watch,build_helper,verified_runtime,STATE,STOP
        try:
            if args.command=='auto-load-build':
                result={'helper':str(build_helper()),'runtime':str(verified_runtime()),'game_loaded':False}
            elif args.command=='auto-load-stop':
                STOP.write_text('user requested watcher stop',encoding='utf-8');result={'stop_requested':True}
            elif args.command=='auto-load-status':
                result=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'closed':True,'stage':'not_started'}
            elif args.command=='auto-load-retry':
                result=watch(target_record=args.target_record)
            else:
                if args.wait_seconds<=0:raise ValueError('wait-seconds must be positive')
                result=watch(args.auto_resume,not args.watch_restarts,args.wait_seconds,args.enemy_race)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 1 if result.get('result')=='error' else 0
        except Exception as exc:
            print(json.dumps({'result':'error','reason':str(exc)},ensure_ascii=False));return 1
    if args.command.startswith('attach'):
        from attach_match import probe,candidates,run_attachment,control,STATE
        try:
            if args.command=='attach-check':
                result=probe(args.pid) if args.pid is not None else candidates()
                ok=result['ready'] if isinstance(result,dict) else any(r['ready'] for r in result)
            elif args.command=='attach':
                result=run_attachment(args.pid,args.enemy_race);ok=result['result']!='error'
            elif args.command=='attach-status':
                result=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'closed':True,'reason':'no_attachment'}
                ok=True
            else:result=control(args.command.removeprefix('attach-'));ok=True
        except Exception as exc:result={'result':'error','reason':str(exc)};ok=False
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if ok else 1
    if args.command=='check':
        config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
        from session import Session
        record=ROOT/'artifacts/session.json'
        live=[r['pid'] for r in json.loads(record.read_text()).get('processes',[]) if Session.matches(r)] if record.exists() else []
        checks={name:(UPSTREAM/'bin'/name).is_file() for name in ('render_hook.dll','war3_launch.exe','war3_ui_command.exe')}
        checks['game_config']=(UPSTREAM/'openwar3.json').is_file()
        checks['python']=Path(ROOT/'.venv/Scripts/python.exe').is_file()
        print(json.dumps(dict(version='0.1.87-dev',rules_version='0.1.87',phase='P1',checks=checks,active_project_pids=live,
                              default_opponent=dict(race='undead',race_id=3,difficulty='normal',difficulty_id=3),
                              default_game_minutes=None,default_wall_minutes=None,default_speed=400,speed_presets=list(SPEEDS),computer_use=False),ensure_ascii=False,indent=2))
        return 0 if all(checks.values()) else 1
    if args.command=='stop':
        (ROOT/'artifacts/STOP').write_text('user requested stop',encoding='utf-8')
        print('Stop requested for the local match only. For an attached game use attach-release; it leaves the game running.')
        return 0
    stop=ROOT/'artifacts/STOP'
    if stop.exists():
        stop.unlink()
    from run_match import play_matches
    r=play_matches(args.speed,args.minutes*60 if args.minutes is not None else None,args.until,args.enemy_race,args.difficulty,map_alias=args.map_alias)
    return 1 if r['result']=='error' else 0

if __name__=='__main__': raise SystemExit(main())
