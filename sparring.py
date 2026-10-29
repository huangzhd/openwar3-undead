"""One owned local duel. P0 observes; fair P1/P2 controllers tick serially."""
import time
from collections import Counter
from bootstrap import ROOT
from human_practice import HumanPracticeSession, source_files as practice_sources, helper
import farm
from human_opponents import HumanOpponent, PROFILES
from undead.game_view import Game
from sparring_map import prepare_map,stage_map
from undead.speed_control import speed_percent

OPPONENTS=(*PROFILES,'kfai-human')


def source_files():
    return [*practice_sources(),ROOT/'human_opponents.py',ROOT/'sparring.py',ROOT/'sparring_map.py',
            ROOT/'training_map.py',ROOT/'kfai_map.py',ROOT/'kfai_strategy.py']


class SparringSession(HumanPracticeSession):
    def __init__(self,profile,map_alias='LR',speed=400):
        if profile not in OPPONENTS:raise ValueError('Unknown opponent profile')
        if map_alias!='LR':raise ValueError('Observer sparring currently supports LR')
        super().__init__(1,map_alias)
        self.speed=speed_percent(speed)
        self.profile=profile;self.opponent_game=None;self.opponent=None;self.missing_since=None
        self.strategy_trace_path=None;self.strategy_trace=None

    def practice_map(self):
        builder=prepare_map
        if self.profile=='kfai-human':
            from kfai_map import prepare_map as builder
        path,catalog=builder(self.map_alias,**({'strategy_trace':True} if self.strategy_trace_path else {}))
        return stage_map(path,farm.w3paths.game_dir()),catalog

    def launch(self,config):
        """Use the original windowed launcher for observer verification."""
        self.foreground=helper('w3window').game_active
        farm.new_instance_dir(self.instance)
        exe=farm.instance_exe(self.instance,config.game_dir())
        args=farm.launch_args(exe,self.instance,self.settings,2500,False,'30,30,1280,720')
        self.settings.update(window_mode='windowed',client_rectangle='30,30,1280,720')
        self.remember(farm.start_launcher(args,farm.out_path(self.instance)))

    def prepare_players(self,pid):
        with Game(pid=pid,fair=False) as setup:
            raw=setup.world.read()
            if raw is None or not raw.in_game or raw.me!=0:raise RuntimeError('Expected local observer P0')
            j=setup.jass
            active={i for i in range(12) if j.GetPlayerSlotState(j.Player(i))==1}
            self.settings['active_player_slots']=sorted(active)
            if not {1,2}<=active or active-{0,1,2}:raise RuntimeError('Unexpected observer scenario player slots: '+repr(sorted(active)))
            rows=[dict(slot=i,controller=j.GetPlayerController(j.Player(i)),race=j.GetPlayerRace(j.Player(i))) for i in (1,2)]
            native=self.profile=='kfai-human'
            if [(r['controller'],r['race']) for r in rows]!=[(1,3),(1,1)]:raise RuntimeError('Wrong bot races/controllers: '+repr(rows))
            if not j.IsPlayerObserver(j.Player(0)) or any(u.alive and u.owner==0 for u in raw.units):
                raise RuntimeError('P0 is not an empty observer: refuse participant-view fallback')
            for a,b in ((1,2),(2,1)):
                if not j.IsPlayerEnemy(j.Player(a),j.Player(b)):raise RuntimeError('Bot players are not enemies')
                if any(j.GetPlayerAlliance(j.Player(a),j.Player(b),kind) for kind in (5,6,7,9)):
                    raise RuntimeError('Bot players share vision/control')
            for i in ((1,) if native else (1,2)):j.PauseCompAI(j.Player(i),True)
            w=setup._w3fast
            receipts=setup.lane.commands([w.command('cam_field',code=0,x=2500.0,y=0.0),
                                          w.command('cam_field',code=1,x=10000.0,y=0.0)])
            if not all(r.ok for r in receipts):raise RuntimeError('Observer camera setup rejected')
            self.settings.update(mode='bot_vs_bot',observer_player=0,controlled_player=1,opponent_player=2,
                                 opponent_profile=self.profile,verified_players=rows,native_ai_paused=not native,
                                 native_ai_paused_players=[1] if native else [1,2],camera_distance=2500,
                                 opponent_fairness='native_KFAI_unverified' if native else 'fair_python_controller',
                                 fair=True,background_supported=False,auto_restart=False)

    def start_opponent(self,log):
        self.opponent_game=Game(pid=self.game.pid,player=2,fair=True)
        self.opponent_log=log;self.opponent_summary_at=-100
        if self.profile!='kfai-human':self.opponent=HumanOpponent(self.opponent_game,log,self.profile,self.map_catalog)
        if self.strategy_trace_path:
            from kfai_strategy import StrategyTrace
            trace_game=None
            try:
                trace_game=Game(pid=self.game.pid,fair=False)
                self.strategy_trace=StrategyTrace(trace_game,self.strategy_trace_path)
            except Exception as exc:
                if trace_game is not None:trace_game.close()
                log('strategy_trace_start_error',error=repr(exc))

    def tick_opponent(self,epoch):
        snap=self.opponent_game.snapshot(max_age=0)
        if snap is None or not snap.resources_known:
            if self.missing_since is None:self.missing_since=time.monotonic()
            if time.monotonic()-self.missing_since>10:raise RuntimeError('Human player snapshot missing for 10s')
            return False
        if not snap.in_game or snap.epoch!=epoch or snap.me!=2:raise RuntimeError('Human opponent match/player identity changed')
        self.missing_since=None
        if self.strategy_trace is not None:self.strategy_trace.poll(epoch,snap.clock,time.monotonic())
        if self.opponent is not None:self.opponent.tick()
        elif snap.clock-self.opponent_summary_at>=15:
            self.opponent_summary_at=snap.clock
            self.opponent_log('human_summary',profile=self.profile,player=2,clock=snap.clock,phase='native_KFAI',
                              resources=self.opponent_game.resources(),units=dict(Counter(u.type for u in self.opponent_game.my_units())))
        return True

    def stop(self):
        try:
            if self.opponent_game is not None:self.opponent_game.close()
        finally:
            self.opponent_game=None
            try:
                if self.strategy_trace is not None:self.strategy_trace.close()
            finally:
                self.strategy_trace=None
                super().stop()
