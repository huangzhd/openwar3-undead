"""Opt-in observer diagnostics. Never exposes opponent labels to Controller.

The AMAI gamecache bridge requires a live probe; successful JASS compilation
does not prove that AI and dev-lane cache handles share the published data.
"""
import json
import re

CACHE = 'AMAI_AI.w3v'
HUMAN_AI_MEMBER = r'Scripts\human.ai'
MISSION = 'dayuan-strategy-v1'
NAMES = ('Rifle', 'NormalHuman', 'Copters', 'HAntiTower', 'MassSB', 'SanctumMix',
         'BarrackMix', 'Mortars', 'Dragonhawk', 'MassSp', 'VersusOrc', 'Gryph', 'Knight')
FIELDS = ('version', 'player', 'strategy', 'chosen_strategy', 'counter')

PUBLISHER = '''function DAYUAN_RecordStrategy takes nothing returns nothing
  local string mission = "dayuan-strategy-v1"
  local integer sequence = GetStoredInteger(amaiCache, mission, "sequence")
  if GetAiPlayer() != 2 then
    return
  endif
  if sequence > 0 and GetStoredInteger(amaiCache, mission, "strategy") == strategy and GetStoredInteger(amaiCache, mission, "chosen_strategy") == chosen_strategy and GetStoredInteger(amaiCache, mission, "counter") == chosen_counter then
    return
  endif
  // Odd sequence: writing. Even sequence: a complete publication.
  call StoreInteger(amaiCache, mission, "sequence", sequence + 1)
  call StoreInteger(amaiCache, mission, "version", 1)
  call StoreInteger(amaiCache, mission, "player", GetAiPlayer())
  call StoreInteger(amaiCache, mission, "strategy", strategy)
  call StoreInteger(amaiCache, mission, "chosen_strategy", chosen_strategy)
  call StoreInteger(amaiCache, mission, "counter", chosen_counter)
  call StoreInteger(amaiCache, mission, "sequence", sequence + 2)
endfunction

'''


def patch_human_ai(blob):
    text = blob.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    text = text.replace('\r\n', '\n')
    if 'DAYUAN_RecordStrategy' in text:
        raise ValueError('KFAI strategy diagnostics already installed')
    names = dict((int(n), name) for name, n in re.findall(r'constant integer STRAT_(\w+) = (\d+)', text))
    if names != dict(enumerate(NAMES)):
        raise ValueError('KFAI strategy table changed')
    anchor = 'function init_strategy takes nothing returns nothing'
    required = {anchor: 1, 'call init_strategy()': 2, 'call DynamicStrategySelector()': 1, 'call InitAMAI()': 1}
    if any(text.count(marker) != count for marker, count in required.items()):
        raise ValueError('KFAI strategy publication sites changed')
    text = text.replace(anchor, PUBLISHER + anchor)
    text = text.replace('call InitAMAI()', 'call InitAMAI()\n  call FlushStoredMission(amaiCache, "'+MISSION+'")')
    for call in ('call init_strategy()', 'call DynamicStrategySelector()'):
        text = text.replace(call, call + '\n      call DAYUAN_RecordStrategy()')
    return text.replace('\n', newline).encode('utf-8')


def read_publication(jass, cache, last_sequence):
    """Read a coherent latest snapshot; explicitly report skipped publications."""
    for _ in range(2):
        sequence = jass.GetStoredInteger(cache, MISSION, 'sequence')
        if sequence < last_sequence:
            raise RuntimeError('KFAI sequence reset within the bound game epoch')
        if sequence == 0 or sequence % 2 or sequence == last_sequence:
            return None
        data = {key: jass.GetStoredInteger(cache, MISSION, key) for key in FIELDS}
        if jass.GetStoredInteger(cache, MISSION, 'sequence') != sequence:
            continue
        if data['version'] != 1 or data['player'] != 2:
            raise RuntimeError('Unexpected KFAI publication version/player')
        for key in ('strategy', 'chosen_strategy'):
            if not 0 <= data[key] < len(NAMES):
                raise RuntimeError('Unknown human strategy: '+str(data[key]))
            data[key+'_name'] = NAMES[data[key]]
        return dict(data, sequence=sequence, missed_publications=(sequence-last_sequence)//2-1)
    return None


class StrategyTrace:
    def __init__(self, game, path):
        self.game = game
        self.stream = path.open('x', encoding='utf-8')
        self.cache = None
        self.epoch = None
        self.sequence = 0
        self.started = None
        self.last_wall = -float('inf')
        self.failures = 0
        self.disabled = False
        try:
            self.write('strategy_trace_opened', schema='kfai-strategy-trace-v1',
                       status='awaiting_live_publication', input_to_policy=False,
                       clock_semantics='observer_read_time_not_strategy_change_time')
        except Exception:
            self.stream.close()
            raise

    def write(self, event, **data):
        self.stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False)+'\n')
        self.stream.flush()

    def validate_epoch(self, epoch):
        raw = self.game.world.read()
        if raw is None or not raw.in_game or raw.me != 0 or raw.epoch != epoch:
            raise RuntimeError('KFAI trace observer/game identity changed')
        if self.epoch is not None and self.epoch != epoch:
            raise RuntimeError('KFAI trace cannot rebind to another game')
        self.epoch = epoch

    def poll(self, epoch, clock, wall):
        if self.disabled or wall-self.last_wall < 1:
            return
        self.last_wall = wall
        if self.started is None:
            self.started = clock
        try:
            self.validate_epoch(epoch)
            if self.cache is None:
                cache = self.game.jass.InitGameCache(CACHE)
                if not cache:
                    raise RuntimeError('AMAI cache handle unavailable')
                self.cache = cache
            data = read_publication(self.game.jass, self.cache, self.sequence)
            self.validate_epoch(epoch)
            if data:
                self.write('kfai_strategy_snapshot', clock=clock, epoch=epoch, **data)
                self.sequence = data['sequence']
            elif not self.sequence and clock-self.started >= 30:
                self.write('strategy_trace_unavailable', clock=clock,
                           reason='No coherent publication within 30 game seconds; cache bridge is unverified.')
                self.disabled = True
            self.failures = 0
        except Exception as exc:
            self.failures += 1
            self.write('strategy_trace_error', clock=clock, error=repr(exc), attempt=self.failures)
            if self.failures >= 3:
                self.disabled = True
                self.write('strategy_trace_disabled', clock=clock, reason='three_consecutive_errors')

    def close(self):
        try:
            self.write('strategy_trace_closed', last_sequence=self.sequence, disabled=self.disabled,
                       captured_publication=self.sequence > 0)
        finally:
            try:
                self.game.close()
            finally:
                self.stream.close()
