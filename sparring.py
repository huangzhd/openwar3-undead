"""One owned local duel. P0 observes; fair P1/P2 controllers tick serially."""
import time
from bootstrap import ROOT
from human_practice import HumanPracticeSession, source_files as practice_sources
from human_opponents import HumanOpponent, PROFILES
from undead.game_view import Game
from sparring_map import prepare_map


def source_files():
    return [*practice_sources(),ROOT/'human_opponents.py',ROOT/'sparring.py',ROOT/'sparring_map.py']


class SparringSession(HumanPracticeSession):
    def __init__(self,profile,map_alias='LR'):
        if profile not in PROFILES:raise ValueError('Unknown opponent profile')
        if map_alias!='LR':raise ValueError('Observer sparring currently supports LR')
        super().__init__(1,map_alias)
        self.profile=profile;self.opponent_game=None;self.opponent=None;self.missing_since=None

    def practice_map(self):return prepare_map(self.map_alias)

    def prepare_players(self,pid):
        with Game(pid=pid,fair=False,owner='sparring-setup') as setup:
            raw=setup.world.read()
            if raw is None or not raw.in_game or raw.me!=0:raise RuntimeError('Expected local observer P0')
            j=setup.jass
            active={i for i in range(12) if j.GetPlayerSlotState(j.Player(i))==1}
            if not {1,2}<=active or active-{0,1,2}:raise RuntimeError('Unexpected observer scenario player slots')
            rows=[dict(slot=i,controller=j.GetPlayerController(j.Player(i)),race=j.GetPlayerRace(j.Player(i))) for i in (1,2)]
            if [(r['controller'],r['race']) for r in rows]!=[(1,3),(1,1)]:raise RuntimeError('Wrong bot races/controllers: '+repr(rows))
            if not j.IsPlayerObserver(j.Player(0)) or any(u.alive and u.owner==0 for u in raw.units):
                raise RuntimeError('P0 is not an empty observer: refuse participant-view fallback')
            for a,b in ((1,2),(2,1)):
                if not j.IsPlayerEnemy(j.Player(a),j.Player(b)):raise RuntimeError('Bot players are not enemies')
                if any(j.GetPlayerAlliance(j.Player(a),j.Player(b),kind) for kind in (5,6,7,9)):
                    raise RuntimeError('Bot players share vision/control')
            for i in (1,2):j.PauseCompAI(j.Player(i),True)
            self.settings.update(mode='bot_vs_bot',observer_player=0,controlled_player=1,opponent_player=2,
                                 opponent_profile=self.profile,verified_players=rows,native_ai_paused=True,
                                 fair=True,background_supported=False,auto_restart=False)

    def start_opponent(self,log):
        self.opponent_game=Game(pid=self.game.pid,player=2,fair=True,owner='human-sparring')
        self.opponent=HumanOpponent(self.opponent_game,log,self.profile,self.map_catalog)

    def tick_opponent(self,epoch):
        snap=self.opponent_game.snapshot(max_age=0)
        if snap is None or not snap.resources_known:
            if self.missing_since is None:self.missing_since=time.monotonic()
            if time.monotonic()-self.missing_since>10:raise RuntimeError('Human player snapshot missing for 10s')
            return False
        if not snap.in_game or snap.epoch!=epoch or snap.me!=2:raise RuntimeError('Human opponent match/player identity changed')
        self.missing_since=None
        self.opponent.tick()
        return True

    def stop(self):
        try:
            if self.opponent_game is not None:self.opponent_game.close()
        finally:
            self.opponent_game=None
            super().stop()
