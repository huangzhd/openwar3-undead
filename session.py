"""Bounded, API-only lifecycle for the project's single game instance."""
import json
import time
from pathlib import Path
import psutil
from bootstrap import ROOT, UPSTREAM
import farm
from openwar3 import Game
from run_window import ensure_time
from game_preferences import apply_defaults,confirm_ally_colors

class Session:
    def __init__(self, speed=100, enemy_race=1, difficulty=2):
        self.speed, self.game = speed, None
        if enemy_race not in (1,2,3,4) or difficulty not in (2,3,4):
            raise ValueError('Invalid opponent race or difficulty')
        self.enemy_race,self.difficulty=enemy_race,difficulty
        self.settings={}
        self.owned = []
        self.record = ROOT / 'artifacts' / 'session.json'

    def start(self,until=None):
        ensure_time(until)
        if self.record.exists():
            previous = json.loads(self.record.read_text(encoding='utf-8'))
            for row in previous.get('processes', []):
                if self.matches(row):
                    raise RuntimeError('A project session is already running; stop it explicitly first')
        defaults=apply_defaults()
        print(json.dumps({'event':'game_preferences_saved','values':defaults}),flush=True)
        args = farm.parse_args(['--first','71','--count','71','--race','3','--enemy-race',str(self.enemy_race),
                                '--difficulty',str(self.difficulty),'--speed',str(self.speed),'--no-director',
                                '--window','30,30,1024,768'])
        launcher_config=farm.Farm(args)
        self.settings=farm.next_game(farm.w3paths.inst_dir(71),launcher_config.base(),launcher_config.maps_dir())
        if (int(self.settings['enemyRace']),int(self.settings['difficulty']))!=(self.enemy_race,self.difficulty):
            raise RuntimeError('next_game.json overrides requested opponent settings')
        print(json.dumps({'event':'match_settings','settings':self.settings}),flush=True)
        ensure_time(until)
        launcher = launcher_config.launch(71)
        self.remember(launcher)
        deadline = time.monotonic() + 120
        last_error = ''
        while time.monotonic() < deadline:
            ensure_time(until)
            if not self.matches(self.owned[0]):
                raise RuntimeError('Launcher exited before game became ready: ' + farm.read_text(farm.out_path(71))[-1600:])
            detail = farm.read_text(farm.out_path(71))
            pid = farm.war3_pid(detail)
            if pid and not any(r['pid'] == pid for r in self.owned):
                self.remember(pid)
            if pid and self.game is None:
                try:
                    self.game = Game(pid=pid, fair=True)
                except Exception as exc:
                    last_error = repr(exc)
            if self.game:
                snap = self.game.snapshot(max_age=0)
                if snap and snap.in_game and snap.clock > 1:
                    own_types = {u.type for u in self.game.my_units()}
                    if 'unpl' not in own_types or 'uaco' not in own_types:
                        raise RuntimeError('Wrong race, reject match: ' + repr(own_types))
                    ally_mode=confirm_ally_colors(pid)
                    print(json.dumps({'event':'ally_color_confirmed','mode':ally_mode}),flush=True)
                    self.settings['verified_opponent']=self.verify_opponent(self.game)
                    print(json.dumps({'event':'opponent_verified',**self.settings['verified_opponent']}),flush=True)
                    print(json.dumps({'event':'ready','pid':pid,'clock':snap.clock,'units':sorted(own_types)},ensure_ascii=False),flush=True)
                    return self.game
            time.sleep(.2)
        raise TimeoutError('Game did not become ready in 120s: ' + last_error)

    def verify_opponent(self,g):
        # Setup metadata only; never expose opponent private economy to the policy.
        audit=Game(pid=g.pid,fair=False)
        try:
            slot=1-g.me();player=audit.jass.Player(slot)
            result=dict(slot=slot,controller=audit.jass.GetPlayerController(player),
                        race=audit.jass.GetPlayerRace(player),ai_difficulty=audit.jass.GetAIDifficulty(player))
            expected={2:0,3:1,4:2}[self.difficulty]
            if (result['controller'],result['race'],result['ai_difficulty'])!=(1,self.enemy_race,expected):
                raise RuntimeError('Actual opponent does not match requested settings: '+repr(result))
            result['difficulty_name']={0:'easy',1:'normal',2:'insane'}[expected]
            return result
        finally:audit.close()

    def remember(self, pid):
        p = psutil.Process(pid)
        self.owned.append({'pid':pid,'created':p.create_time(),'name':p.name()})
        self.record.write_text(json.dumps({'processes':self.owned},indent=2),encoding='utf-8')

    @staticmethod
    def matches(row):
        try:
            p = psutil.Process(row['pid'])
            return p.create_time() == row['created'] and p.name().lower() == row['name'].lower()
        except psutil.Error:
            return False

    def stop(self):
        if not self.owned:
            return
        if self.game:
            try:
                self.game.end_game()
            except Exception as exc:
                print('Game end request failed:',repr(exc),flush=True)
            finally:
                self.game.close()
                self.game = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(self.matches(r) for r in self.owned):
            time.sleep(.2)
        for row in reversed(self.owned):
            if self.matches(row):
                psutil.Process(row['pid']).kill()
        remaining = [r for r in self.owned if self.matches(r)]
        self.record.write_text(json.dumps({'processes':remaining,'closed':not remaining},indent=2),encoding='utf-8')
        if remaining:
            psutil.wait_procs([psutil.Process(r['pid']) for r in remaining],timeout=3)
            if any(self.matches(r) for r in remaining):
                raise RuntimeError('Owned process did not exit')
            self.record.write_text(json.dumps({'processes':[],'closed':True}),encoding='utf-8')
        self.owned = []
