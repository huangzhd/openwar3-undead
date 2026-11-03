"""Conservative undead economic legality, never a build-order policy."""
import math

BUILD_CODES = ('uaod', 'usep', 'uzig', 'ugrv', 'utom')
TRAIN_SOURCES = {'uaco': ('unpl', 'unp1', 'unp2'), 'ugho': ('usep',), 'ucry': ('usep',)}
HALLS = ('unpl', 'unp1', 'unp2')
OPS = ('gather_gold', 'build', 'train')


def catalog():
    # Public 1.27a data, hashed in the episode's dependency contract.
    from openwar3.game import unit_table
    table = unit_table()
    result = {}
    for code in (*BUILD_CODES, *TRAIN_SOURCES):
        row = table.get(code, {})
        fields = ('gold', 'lumber', 'food', 'foot')
        if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) or row[k] < 0 for k in fields):
            raise ValueError('Incomplete public economic cost: '+code)
        result[code] = {k: row[k] for k in fields}
    return result


def known_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def completed(unit, production):
    # Conservative first version: damaged buildings remain unknown, not complete.
    return (known_number(unit.get('hp')) and known_number(unit.get('hp_max'))
            and unit['hp_max'] > 0 and unit['hp'] >= unit['hp_max']*.999
            and not any(p['building'] == unit['handle'] and p['kind'] in ('construction', 'upgrade')
                        for p in production))


def preflight(action, observation, source, abilities, costs):
    op = action['op']
    production = observation.get('production')
    if not isinstance(production, list):return 'production_unknown'
    units = observation['units']
    if op == 'gather_gold':
        if source['type'] != 'uaco' or 'Aaha' not in abilities or 'Amov' not in abilities:
            return 'source_cannot_gather_gold'
        target = next((u for u in units if u['handle'] == action['target']), None)
        if (target is None or target['owner'] != 1 or target['type'] != 'ugol'
                or not target['alive'] or not completed(target, production)):
            return 'gold_target_not_owned_ready_mine'
        return 'allowed'
    code = action['code']
    row = costs.get(code)
    if row is None:return 'economic_catalog_unknown'
    resources = observation.get('resources')
    required = ('gold', 'lumber', 'food_used', 'food_cap') if op == 'train' else ('gold', 'lumber')
    if not isinstance(resources, dict) or any(not known_number(resources.get(k)) for k in required):
        return 'resources_unknown'
    if resources['gold'] < row['gold']:return 'insufficient_gold'
    if resources['lumber'] < row['lumber']:return 'insufficient_lumber'
    if op == 'build':
        if source['type'] != 'uaco' or not {'AUbu', 'Amov'} <= abilities:return 'source_cannot_build'
        if not any(u['owner'] == 1 and u['alive'] and u['type'] in HALLS and completed(u, production) for u in units):
            return 'ready_hall_required'
    elif op == 'train':
        if source['type'] not in TRAIN_SOURCES[code] or 'Aque' not in abilities:
            return 'wrong_producer'
        if not completed(source, production):return 'producer_not_ready'
        if resources['food_used'] + row['food'] > resources['food_cap']:return 'insufficient_food'
        if sum(len(p['queue']) for p in production if p['building'] == source['handle'] and p['kind'] == 'queue') >= 7:
            return 'producer_queue_full'
        if code == 'ucry' and not any(u['owner'] == 1 and u['alive'] and u['type'] == 'ugrv'
                                     and completed(u, production) for u in units):
            return 'ready_graveyard_required'
    return 'allowed'


def placement_reason(game, action, costs, bounds):
    """Only public terrain and explicit P1 point visibility; no hidden occupants."""
    if game.visible(action['x'], action['y']) is not True:return 'build_point_not_visible'
    grid = game.map()
    buildable = getattr(grid, 'buildable', None)
    if not callable(buildable):return 'placement_grid_unknown'
    half = costs[action['code']]['foot']/2
    xmin, xmax, ymin, ymax = bounds
    if not (xmin <= action['x']-half and action['x']+half <= xmax
            and ymin <= action['y']-half and action['y']+half <= ymax):
        return 'footprint_outside_map'
    offsets = range(-int(half)+16, int(half), 32)
    if any(buildable(action['x']+dx, action['y']+dy) is not True for dx in offsets for dy in offsets):
        return 'terrain_not_buildable'
    # Blight, dynamic collision and later execution still belong to the engine.
    return 'allowed'
