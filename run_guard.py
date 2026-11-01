"""Cooperative local-match cutoffs and separate timing evidence.

Checks at stages, world reads and native lane calls; caps native wait time.
Cannot preempt a stuck C call, OS suspension or Python code with no checkpoints.
Control-flow exceptions bypass broad strategy 'except Exception' fallbacks.
"""
import json
import time
from contextlib import contextmanager


class RunInterrupted(BaseException):
    def __init__(self, reason, clock):
        super().__init__(reason)
        self.reason, self.clock = reason, clock


class RunGuard:
    def __init__(self, game, path, *, game_limit=None, until=None, stage_seconds=None):
        self.read = game.world.read
        initial = self.read()
        if initial is None or not initial.in_game:raise RuntimeError('Guard requires a ready game')
        self.epoch = initial.epoch
        self.clock = initial.clock
        self.speed = max(1, initial.speed_pct)/100
        self.game_limit, self.until, self.stage_seconds = game_limit, until, stage_seconds
        self.stream = path.open('x', encoding='utf-8')
        self.hooks, self.stack, self.stats = [], [], {}
        self.closed = False
        self.write('guard_open', game_limit=game_limit, until=until, stage_seconds=stage_seconds,
                   enforcement='cooperative_checkpoints_native_wait_cap', input_to_policy=False)

    def write(self, event, **data):
        self.stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False)+'\n')
        self.stream.flush()

    def observe(self, raw):
        if raw is not None:
            if not raw.in_game or raw.epoch != self.epoch:
                raise RunInterrupted('game_epoch_changed', self.clock)
            self.clock = max(self.clock, raw.clock)
            self.speed = max(1, raw.speed_pct)/100

    def check(self):
        reason = None
        if self.game_limit is not None and self.clock >= self.game_limit:reason = 'game_time_limit'
        elif self.until is not None and time.time() >= self.until:reason = 'automation_deadline'
        elif self.stack and self.stage_seconds is not None and time.perf_counter()-self.stack[0][1] >= self.stage_seconds:
            reason = 'stage_time_limit'
        if reason:
            self.write('cutoff', reason=reason, clock=self.clock, stage=self.stack[-1][0] if self.stack else None)
            raise RunInterrupted(reason, self.clock)

    def checkpoint(self):
        self.check()
        started = time.perf_counter()
        try:self.observe(self.read())
        finally:self.measure('checkpoint_read', started)
        self.check()

    def measure(self, name, started):
        seconds = time.perf_counter()-started
        stat = self.stats.setdefault(name, dict(count=0,total_seconds=0.,max_seconds=0.))
        stat['count'] += 1
        stat['total_seconds'] += seconds
        stat['max_seconds'] = max(stat['max_seconds'], seconds)
        if seconds >= .1:
            self.write('slow_call', name=name, wall_seconds=seconds, clock=self.clock,
                       stage=self.stack[-1][0] if self.stack else None)

    @contextmanager
    def stage(self, name):
        self.checkpoint()
        started = time.perf_counter()
        self.stack.append((name, started))
        self.write('stage_begin', name=name, clock=self.clock, wall_time=time.time())
        try:
            yield
            self.checkpoint()  # Fail on a slow stage even if it made no API calls.
        finally:
            self.write('stage_end', name=name, clock=self.clock, wall_seconds=time.perf_counter()-started)
            self.measure('stage:'+name, started)
            self.stack.pop()

    def attach(self, game, label):
        def hook(obj, name, wrapper):
            original = getattr(obj, name)
            setattr(obj, name, wrapper(original))
            self.hooks.append((obj, name, getattr(obj, name), original))

        def wrap_read(original):
            def read(*args, **kwargs):
                self.check()
                started = time.perf_counter()
                try:
                    raw = original(*args, **kwargs)
                    self.observe(raw)
                finally:self.measure(label+':world_read', started)
                self.check()
                return raw
            return read

        def wrap_run(original):
            def run(calls, timeout=.25):
                self.checkpoint()
                limits = [timeout, .25]
                if self.until is not None:limits.append(self.until-time.time())
                if self.game_limit is not None:limits.append((self.game_limit-self.clock)/self.speed)
                if self.stack and self.stage_seconds is not None:
                    limits.append(self.stage_seconds-(time.perf_counter()-self.stack[0][1]))
                self.check()
                started = time.perf_counter()
                try:result = original(calls, timeout=max(.001,min(limits)))
                finally:self.measure(label+':lane_run', started)
                self.checkpoint()
                return result
            return run

        hook(game.world, 'read', wrap_read)
        if hasattr(game.lane, 'run'):hook(game.lane, 'run', wrap_run)

    def close(self):
        if self.closed:return
        self.closed = True
        # Remove guards before any game/client teardown commands.
        for obj, name, wrapped, original in reversed(self.hooks):
            if getattr(obj, name) is wrapped:setattr(obj, name, original)
        try:self.write('guard_closed', clock=self.clock, statistics=self.stats)
        finally:self.stream.close()
