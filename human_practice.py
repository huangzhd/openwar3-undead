"""One local human P0 versus dayuan P1; no multiplayer attachment or restart."""
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path

from bootstrap import ROOT, UPSTREAM
from session import Session
from undead.game_view import Game
import farm

FORK = ROOT/'artifacts/human-vs-ai-source-20261028'
FORK_COMMIT = '68c40c0d0f2149f44584195a7cdb91ba975bf90e'
HELPERS = {
    'w3fullscreen': '81d4b342dae4687f8bd577c22e91ea22b7b6258217705c00f13c21e852cbcada',
    'w3window': '0fc2c5fa838021faaa81857dff120444dae83f916ac2d38ba0fc41552cbea071',
}


def source_files():
    """Freeze the reviewed fork helpers too; never execute a changed helper."""
    files = [Path(__file__),ROOT/'practice_video.py',ROOT/'practice_control.py',ROOT/'machine_start.py']
    for name, expected in HELPERS.items():
        path = FORK/'sdk/python'/f'{name}.py'
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Human practice helper differs from reviewed fork: '+str(path))
        files.append(path)
    return files


def helper(name):
    source_files()
    path = FORK/'sdk/python'/f'{name}.py'
    spec = importlib.util.spec_from_file_location('practice_'+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HumanPracticeSession(Session):
    def __init__(self, human_race=2, map_alias='LR'):
        if human_race not in (1, 2, 3, 4):
            raise ValueError('Choose a concrete human race')
        super().__init__(100, human_race, 2, map_alias)
        self.instance = 73
        self.foreground = None

    def launch(self, config):
        launcher = helper('w3fullscreen').fullscreen_launcher(farm.w3paths.LAUNCH_EXE)
        self.foreground = helper('w3window').game_active
        farm.new_instance_dir(self.instance)
        exe = farm.instance_exe(self.instance, config.game_dir())
        args = farm.launch_args(exe, self.instance, self.settings, 1650, False, '0,0,1024,768')
        # Native fullscreen: the fork likewise omits the window sizing argument.
        del args[args.index('--client'):]
        output = Path(farm.out_path(self.instance))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('wb') as fh:
            process = subprocess.Popen([launcher, *args], cwd=farm.BIN, stdin=subprocess.DEVNULL,
                                       stdout=fh, stderr=subprocess.STDOUT, creationflags=farm.NO_WINDOW)
        self.remember(process.pid)

    def prepare_players(self, pid):
        """Setup-only full view; no human economy/hidden positions enter dayuan."""
        with Game(pid=pid, fair=False) as setup:
            raw = setup.world.read()
            if raw is None or not raw.in_game or raw.me != 0:
                raise RuntimeError('Expected local human P0')
            j = setup.jass
            active = [i for i in range(12) if j.GetPlayerSlotState(j.Player(i)) == 1]
            rows = [dict(slot=i, controller=j.GetPlayerController(j.Player(i)),
                         race=j.GetPlayerRace(j.Player(i))) for i in (0, 1)]
            if (active != [0, 1] or [(r['controller'], r['race']) for r in rows] != [(0, self.enemy_race), (1, 3)]
                    or not j.IsPlayerEnemy(j.Player(0), j.Player(1)) or not j.IsPlayerEnemy(j.Player(1), j.Player(0))):
                raise RuntimeError('Expected one human P0 and undead computer P1: '+repr(rows))
            # This native is only used in this owned, single-client local game.
            j.PauseCompAI(j.Player(1), True)
            self.settings.update(verified_players=rows, native_ai_paused=True,
                                 controlled_player=1, human_player=0, fair=True,
                                 mode='human_vs_dayuan', fork_commit=FORK_COMMIT)

    def practice_map(self):
        from undead.maps import resolve_map
        return resolve_map(self.map_alias)

    def start(self, until=None):
        from machine_start import active_processes
        from run_window import ensure_time
        ensure_time(until)
        active = active_processes()
        if active:
            raise RuntimeError('An existing game/session blocks practice launch: '+repr(active))
        self.map_path, self.map_catalog = self.practice_map()
        args = farm.parse_args(['--first','73','--count','73','--race',str(self.enemy_race),
                                '--enemy-race','3','--difficulty','2','--speed',str(self.speed),'--no-director',
                                '--cam-distance','1650'])
        args.map = str(self.map_path)
        config = farm.Farm(args)
        self.settings = farm.next_game(farm.w3paths.inst_dir(73), config.base(), config.maps_dir())
        expected = (self.enemy_race, 3, 2, self.speed)
        if tuple(int(self.settings[k]) for k in ('race','enemyRace','difficulty','speed')) != expected:
            raise RuntimeError('next_game.json overrides practice player/race/speed')
        if Path(self.settings['map']).resolve() != self.map_path.resolve():
            raise RuntimeError('next_game.json overrides practice map')
        self.settings.update(map_alias=self.map_alias, map_sha256=self.map_catalog['map_sha256'])
        from practice_video import configure_video
        self.settings['display']=configure_video()
        self.launch(config)
        deadline = time.monotonic()+120
        last_error = ''
        while time.monotonic() < deadline:
            ensure_time(until)
            if not self.matches(self.owned[0]):
                raise RuntimeError('Practice launcher exited: '+farm.read_text(farm.out_path(73))[-1600:])
            pid = farm.war3_pid(farm.read_text(farm.out_path(73)))
            if pid and not any(r['pid'] == pid for r in self.owned):
                self.remember(pid)
            if pid and self.game is None:
                try:
                    self.game = Game(pid=pid, player=1, fair=True)
                except Exception as exc:
                    last_error = repr(exc)
            if self.game:
                snap = self.game.snapshot(max_age=0)
                if snap and snap.in_game and snap.clock > 1:
                    own_types = {u.type for u in self.game.my_units()}
                    if snap.me != 1 or snap.speed_pct != self.speed or not {'unpl','uaco'} <= own_types:
                        raise RuntimeError('Wrong practice identity/race/speed: '+repr(own_types))
                    if not snap.resources_known:
                        time.sleep(.2)
                        continue
                    if self.game.map() is None:
                        time.sleep(.2)
                        continue
                    self.verify_map(self.game)
                    self.prepare_players(pid)
                    self.settings['own_start_sample'] = dict(clock=snap.clock,
                        own_halls=[dict(type=h.type,x=h.x,y=h.y) for h in self.game.my_units() if h.type=='unpl'],
                        basis='first_ready_fair_P1_buildings')
                    print(json.dumps(dict(event='human_practice_ready',pid=pid,clock=snap.clock,
                                          settings=self.settings),ensure_ascii=False),flush=True)
                    return self.game
            time.sleep(.2)
        raise TimeoutError('Practice did not become ready in 120s: '+last_error)

    def alive(self):
        return self.game is not None and any(r['pid']==self.game.pid and self.matches(r) for r in self.owned)

    def active(self):
        return self.foreground(self.game.pid)
