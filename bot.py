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
    play=sub.add_parser('play',help='Play a local rule-controlled match')
    play.add_argument('--speed',type=speed_percent,choices=SPEEDS,default=400)
    play.add_argument('--minutes',type=positive_minutes,default=None,help='Optional game-time limit; default is no limit')
    play.add_argument('--until',type=parse_deadline,help='Absolute ISO cutoff, including timezone offset')
    play.add_argument('--enemy-race',type=int,choices=(1,2,3,4),default=3,help='1 human, 2 orc, 3 undead, 4 night elf')
    play.add_argument('--difficulty',type=int,choices=(2,3,4),default=3,help='2 easy, 3 normal, 4 insane')
    sub.add_parser('stop',help='Request graceful stop of the project match')
    args=parser.parse_args()
    if args.command=='check':
        config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
        from session import Session
        record=ROOT/'artifacts/session.json'
        live=[r['pid'] for r in json.loads(record.read_text()).get('processes',[]) if Session.matches(r)] if record.exists() else []
        checks={name:(UPSTREAM/'bin'/name).is_file() for name in ('render_hook.dll','war3_launch.exe','war3_ui_command.exe')}
        checks['game_config']=(UPSTREAM/'openwar3.json').is_file()
        checks['python']=Path(ROOT/'.venv/Scripts/python.exe').is_file()
        print(json.dumps(dict(version='0.1.51-dev',rules_version='0.1.51',phase='P1',checks=checks,active_project_pids=live,
                              default_opponent=dict(race='undead',race_id=3,difficulty='normal',difficulty_id=3),
                              default_game_minutes=None,default_wall_minutes=None,default_speed=400,speed_presets=list(SPEEDS),computer_use=False),ensure_ascii=False,indent=2))
        return 0 if all(checks.values()) else 1
    if args.command=='stop':
        (ROOT/'artifacts/STOP').write_text('user requested stop',encoding='utf-8')
        print('Stop requested; the match runner will close only its own game.')
        return 0
    stop=ROOT/'artifacts/STOP'
    if stop.exists():
        stop.unlink()
    from run_match import play_matches
    r=play_matches(args.speed,args.minutes*60 if args.minutes is not None else None,args.until,args.enemy_race,args.difficulty)
    return 1 if r['result']=='error' else 0

if __name__=='__main__': raise SystemExit(main())
