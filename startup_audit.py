"""Bounded startup readiness and native diagnostics; never retries a command."""
import time
from contextlib import contextmanager
from run_window import ensure_time


class StartupAudit:
    def __init__(self, session, deadline, until=None):
        self.session, self.deadline, self.until = session, deadline, until
        self.epoch = None
        self.speed_wait_started = None

    def emit(self, event, **data):
        self.session.startup_log(event, **data)

    def check_deadline(self):
        ensure_time(self.until)
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Startup readiness deadline exceeded')
        if self.speed_wait_started is not None and time.monotonic()-self.speed_wait_started>=5:
            raise TimeoutError('Startup speed did not reach requested value within 5s')

    def speed_ready(self, snapshot):
        """Launcher configuration is asynchronous; never write speed or accept a mismatch."""
        self.check_deadline()
        if self.epoch is None:self.epoch=snapshot.epoch
        if snapshot.epoch!=self.epoch:raise RuntimeError('Startup epoch changed')
        if snapshot.speed_pct!=self.session.speed:
            if self.speed_wait_started is None:
                self.speed_wait_started=time.monotonic()
                self.emit('startup_speed_wait',actual=snapshot.speed_pct,expected=self.session.speed,
                          clock=snapshot.clock,max_wall_seconds=5)
            return False
        if self.speed_wait_started is not None:
            self.emit('startup_speed_ready',actual=snapshot.speed_pct,clock=snapshot.clock,
                      waited_wall_seconds=time.monotonic()-self.speed_wait_started)
            self.speed_wait_started=None
        return True

    def sample(self):
        self.check_deadline()
        raw = self.session.game.world.read()
        if raw is None or not raw.in_game or raw.me != 0:
            raise RuntimeError('Startup observer snapshot unavailable or changed')
        if self.epoch is None:self.epoch = raw.epoch
        if raw.epoch != self.epoch:raise RuntimeError('Startup epoch changed')
        return dict(clock=raw.clock, epoch=raw.epoch,
                    foreground=bool(self.session.active()))

    def wait_ready(self):
        previous = None
        waiting = False
        while True:
            state = self.sample()
            can_run = state['foreground'] or getattr(self.session, 'background_allowed', False)
            if can_run and previous is not None and state['clock'] > previous:
                self.emit('startup_ready', **state)
                return
            if not waiting:
                self.emit('startup_wait', **state)
                waiting = True
            previous = state['clock'] if can_run else None
            time.sleep(.2)

    @contextmanager
    def stage(self, name):
        self.session.settings['startup_stage'] = name
        self.emit('startup_stage_begin', stage=name)
        started = time.monotonic()
        try:
            yield
        except BaseException as exc:
            self.emit('startup_stage_failed', stage=name, error=repr(exc),
                      wall_seconds=time.monotonic()-started)
            raise
        else:
            self.emit('startup_stage_end', stage=name, wall_seconds=time.monotonic()-started)

    @contextmanager
    def trace_client(self, client):
        jass = client.jass
        original = jass.call
        def call(name, *args):
            state = self.sample()
            if not state['foreground'] and not getattr(self.session, 'background_allowed', False):
                self.wait_ready()
                state = self.sample()
            self.emit('startup_native_begin', native=name, **state)
            started = time.monotonic()
            try:
                result = original(name, *args)
            except BaseException as exc:
                self.emit('startup_native_failed', native=name, error=repr(exc),
                          wall_seconds=time.monotonic()-started)
                raise
            self.emit('startup_native_end', native=name,
                      wall_seconds=time.monotonic()-started)
            return result
        jass.call = call
        try:yield
        finally:jass.call = original
