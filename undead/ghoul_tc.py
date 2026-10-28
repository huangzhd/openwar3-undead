"""Ghoul opening: give Silence time to land before committing into TC."""
from math import cos, sin, pi
from .targeting import abilities, buffs, can_engage, enemy_player, unit_stats
from .nc_combo import DISABLED_CASTERS, spell_data
from .policy import Action


def opening_target(g, army, foes):
    alive = [u for u in army if u.hp > 0]
    if sum(u.type == 'ugho' for u in alive) < 3:return None
    if not {'Udea', 'Ulic', 'Nbrn'} <= {u.type for u in alive}:return None
    if any(u.type in {'uabo', 'Ucrl'} for u in alive):return None
    dark = next(u for u in alive if u.type == 'Nbrn')
    if not abilities(g, dark).get('ANsi', {}).get('level'):return None
    chiefs = [e for e in foes if e.type == 'Otch' and can_engage(e)
              and enemy_player(g, e) and getattr(e, 'has_detail', False)
              and not buffs(g, e) & {'Bvul', 'BHds'} and 'Avul' not in abilities(g, e)
              and g.dist(dark, e) <= 1000]
    return min(chiefs, key=lambda e: g.dist(dark, e), default=None)


def waiting(g, target):
    # Accepted casts and predicted duration never establish that Silence landed.
    return target is not None and not buffs(g, target) & {'BNsi', 'BNso'}


def retreat_ghouls(b, army, foes, now, pulls, blocked=()):
    g = b.g
    previous = b.ghoul_tc_waiting
    b.ghoul_tc_waiting = set()
    tc = opening_target(g, army, foes)
    if (not waiting(g, tc) or b.teleport or b.action == Action.RETREAT
            or b.army_recovery.active):
        if previous:
            b.log('battle_ghoul_tc_release', clock=now, target=tc.handle if tc else None,
                  reason='target_unavailable' if tc is None else
                  'silence_observed' if not waiting(g, tc) else 'higher_priority_retreat')
        return
    excluded = (set(pulls) | set(blocked) | b.micro.pulling | b.shopping
                | set(b.shield_moves) | b.battle_shop.reserved)
    row = abilities(g, tc).get('AOws', {})
    level = min(3, max(1, row.get('level') or 3))
    clearance = float(spell_data()[0]['AOws']['Area' + str(level)]) + 180
    threats = [(e, max((w.range for w in stats.weapons if 'ground' in w.targets), default=0))
               for e in foes if can_engage(e) and (stats := unit_stats(e.type))]
    grid = g.map()
    for u in army:
        if (u.type != 'ugho' or u.hp <= 0 or u.handle in excluded
                or now < b.cast_until.get(u.handle, 0) or buffs(g, u) & DISABLED_CASTERS):continue
        distance = g.dist(u, tc)
        if distance > 1000:continue
        point = (u.x, u.y)
        if distance < clearance:
            dx, dy = (u.x-tc.x)/max(1, distance), (u.y-tc.y)/max(1, distance)
            if distance < 1:dx, dy = -1, 0
            candidates = []
            for degrees in (0, 25, -25, 50, -50, 75, -75):
                angle = degrees*pi/180
                vx, vy = dx*cos(angle)-dy*sin(angle), dx*sin(angle)+dy*cos(angle)
                p = (tc.x+vx*clearance, tc.y+vy*clearance)
                travel = g.dist(u, p)
                samples = [(u.x+(p[0]-u.x)*j/8, u.y+(p[1]-u.y)*j/8) for j in range(1, 9)]
                if not grid or any(not grid.walkable(*s) for s in samples):continue
                if any(g.dist(s, tc) < distance-5 for s in samples):continue
                if any(reach and any(g.dist(s, e) < min(reach+60, g.dist(u, e))-15
                                    for s in samples) for e, reach in threats if e.handle != tc.handle):continue
                route = g.path_distance((u.x, u.y), p)
                if route is not None and route <= travel+80:candidates.append((travel, p))
            if candidates:point = min(candidates)[1]
            # No safe path: hold instead of issuing a doomed move through enemies.
        pulls[u.handle] = point
        b.ghoul_tc_waiting.add(u.handle)
        if u.handle not in previous:b.last.pop(('go', u.handle), None)
        if u.handle not in previous or b.due(('ghoul_tc_wait', u.handle), now, 2):
            b.log('battle_ghoul_tc_wait', clock=now, handle=u.handle, target=tc.handle,
                  point=point, silence_confirmed=False)
