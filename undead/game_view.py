"""Project compatibility for current, owned hero inventory observations."""
from openwar3 import Game as SDKGame


class Game(SDKGame):
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
