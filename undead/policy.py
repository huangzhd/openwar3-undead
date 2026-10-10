"""Policy data is copied from visible units only; never expose SDK/raw snapshots."""
from dataclasses import dataclass
from enum import IntEnum
from math import hypot

class Action(IntEnum):
    CREEP = 0
    HARASS = 1
    ATTACK = 2
    DEFEND = 3
    RETREAT = 4

@dataclass(frozen=True)
class Seen:
    handle: tuple
    type: str
    owner: int
    x: float
    y: float
    hp: float
    hp_max: float
    level: int
    hero: bool
    building: bool
    at: float

class ScoutMemory:
    def __init__(self):
        self.units = {}

    def update(self, visible, now, me, classify):
        for u in visible:
            if u.owner == me or not u.visible_to(me):
                continue
            key = tuple(u.handle)
            if not u.alive:
                self.units.pop(key, None)
                continue
            self.units[key] = Seen(key,u.type,u.owner,u.x,u.y,u.hp,u.hp_max,
                                   u.level,u.is_hero,classify(u),now)
        self.units = {k:v for k,v in self.units.items() if v.building or now - v.at <= 120}

    def clear_visible_empty_sites(self,visible_buildings,visible_at,near):
        present={tuple(u.handle) for u in visible_buildings}
        removed=[]
        for key,seen in list(self.units.items()):
            if seen.building and key not in present and near(seen) and visible_at(seen.x,seen.y):
                removed.append(seen)
                self.units.pop(key)
        return removed

    def expansions(self, enemy_main, now):
        if enemy_main is None:
            return []
        return [u for u in self.units.values()
                if u.type in {'htow','hkee','hcas'} and now-u.at <= 60
                and hypot(u.x-enemy_main[0],u.y-enemy_main[1]) > 1800]

@dataclass
class Situation:
    now: float
    hero_health: float = 1.0
    threatened: bool = False
    expansion: bool = False
    local_enemy_hp: float = 0
    army_hp: float = 0
    fiends: int = 0
    tier: int = 1
    lich: bool = False
    orb: bool = False
    statues: int = 0
    dk_level: int = 1
    army_health: float = 1.0
    recent_losses: int = 0
    creep_targets_available: bool = False
    attack_committed: bool = False
    third_hero: bool = False
    dk: bool = True

def attack_ready(s):
    return s.tier==3 and s.dk and s.lich and s.orb and s.third_hero

def choose_rule(s):
    if s.local_enemy_hp > s.army_hp * 1.4 and s.local_enemy_hp > 600:
        return Action.RETREAT
    # Dead units leave the health denominator: healthy survivors do not erase attrition.
    if s.recent_losses>=2 and s.local_enemy_hp>400 and (s.army_health<.5 or s.local_enemy_hp>s.army_hp):
        return Action.RETREAT
    if s.threatened:
        return Action.DEFEND
    # Actual current composition is required; a previous commitment cannot bypass losses.
    if attack_ready(s):
        return Action.ATTACK
    if s.expansion:
        return Action.HARASS
    return Action.CREEP
