"""Owned hero inventory access and bounded recovery of missing Coil telemetry."""
from openwar3 import Game as SDKGame
from .coil import CoilTelemetry


class Game(SDKGame):
    def _coil(self):
        if not hasattr(self, '_coil_telemetry'):
            self._coil_telemetry = CoilTelemetry()
        return self._coil_telemetry

    def observe_coil(self, heroes, now, log):
        telemetry = self._coil()
        telemetry.log = log
        telemetry.observe(self, next((h for h in heroes if h.type == 'Udea'), None), now)

    def coil_ready(self, hero, now=None):
        return self._coil().can_attempt(self, self._fresh(hero), self.clock() if now is None else now)

    def coil_level(self, hero):
        s = self._coil().observe(self, self._fresh(hero), self.clock())
        return s['level'] if s else 0

    def cast(self, u, spell, target=None, x=None, y=None):
        if spell != 'deathcoil':return super().cast(u, spell, target=target, x=x, y=y)
        current = self._fresh(u)
        now = self.clock()
        if not self._coil().can_attempt(self, current, now):return False
        result = super().cast(current, spell, target=target, x=x, y=y)
        self._coil().attempted(current, now, bool(result))
        return result

    def inventory(self, hero):
        bag = super().inventory(hero)
        if bag is not None or hero is None:
            return bag
        # LR 20261012-144835: after 681.98s Lich abilities omitted AInv,
        # although the same fair detailed snapshot still contained the orb.
        # Read current own slots, never infer possession from an older bag.
        current = self.unit(hero.handle)
        if (current is None or current.owner != self.me() or not current.alive
                or not current.is_hero or not current.has_detail):
            return None
        items = current.items
        return list(items) if items is not None and len(items) == 6 else None
