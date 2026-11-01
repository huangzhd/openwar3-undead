"""Explicit player point visibility; never fall back to the local observer."""
import math


class PlayerVisibility:
    def __init__(self, client, pid, epoch, player=1):
        if type(player) is not int or not 0 <= player < 12:
            raise ValueError('Expected a concrete player slot')
        if type(epoch) is not int or epoch <= 0:
            raise ValueError('Expected a live game epoch')
        self.client, self.pid, self.epoch, self.player = client, pid, epoch, player
        self.player_handle = None
        self.closed = False

    def valid(self, raw):
        return (not self.closed and self.client.pid == self.pid and raw is not None
                and raw.in_game and raw.me == 0 and raw.epoch == self.epoch)

    def query(self, x, y):
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (x, y)):
            raise ValueError('Invalid point')
        unknown = dict(x=x, y=y, visible=None, clock=None)
        if self.closed:return unknown
        try:
            before = self.client.world.read()
            if not self.valid(before):return unknown
            jass = self.client.jass
            if self.player_handle is None:self.player_handle = jass.Player(self.player)
            if not self.player_handle:return unknown
            visible = jass.IsVisibleToPlayer(float(x), float(y), self.player_handle)
            after = self.client.world.read()
            if not self.valid(after) or after.clock < before.clock:return unknown
            return dict(x=x, y=y, visible=visible if type(visible) is bool else None,
                        clock=after.clock if math.isfinite(after.clock) else None)
        except Exception:
            # RunInterrupted deliberately propagates: it is control flow, not a query error.
            return unknown

    def close(self):
        if not self.closed:
            self.closed = True
            self.client.close()
