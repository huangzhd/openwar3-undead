"""LR melee hero skills. Orders and private opponent state are never inputs."""

KITS = {
    'Udea': ('AUdc', 'AUdp', 'AUau', 'AUan'),
    'Ulic': ('AUfn', 'AUfu', 'AUdr', 'AUdd'),
    'Udre': ('AUav', 'AUsl', 'AUcs', 'AUin'),
    'Ucrl': ('AUim', 'AUts', 'AUcb', 'AUls'),
}
SKILLS = tuple(skill for kit in KITS.values() for skill in kit)


def points(raw):
    rows = []
    for u in raw.units:
        if u.owner == 1 and u.type in KITS:
            value = u.skill_points if u.is_hero and u.has_detail and any(a.code=='AHer' for a in u.abilities) else None
            rows.append(dict(unit=list(u.handle), points=value if type(value) is int and 0 <= value <= 10 else None))
    return sorted(rows, key=lambda r: r['unit'])


def unspent(observation, handle):
    return next((r['points'] for r in observation.get('hero_skill_points', []) if r['unit'] == handle), None)


def learned_rank(source, skill, available):
    abilities = source['abilities']
    if abilities is None or source['type'] not in KITS:
        return None
    ranks = {}
    for a in abilities:
        code = a['code']
        if code not in KITS[source['type']]:
            continue
        value = a['level']
        maximum = 1 if code == KITS[source['type']][-1] else 3
        if type(value) is not int or not 0 <= value <= maximum or code in ranks:
            return None
        ranks[code] = value
    # Missing SDK rows can mean missing telemetry. Infer zero only if every
    # spent point is accounted for by other observed ranks in this melee kit.
    if skill in ranks:
        return ranks[skill]
    if type(available) is int and sum(ranks.values()) + available == source['level']:
        return 0
    return None


def preflight(action, observation, source):
    skill = action['skill']
    kit = KITS.get(source['type'], ())
    if skill not in kit:
        return 'skill_not_in_hero_kit'
    available = unspent(observation, source['handle'])
    if type(available) is not int:
        return 'skill_points_unknown'
    if available <= 0:
        return 'no_skill_points'
    level = source['level']
    if type(level) is not int or not 1 <= available <= level <= 10:
        return 'hero_level_unknown'
    rank = learned_rank(source, skill, available)
    if rank is None:
        return 'skill_rank_unknown'
    ultimate = skill == kit[-1]
    if rank >= (1 if ultimate else 3):
        return 'skill_at_max_rank'
    if level < (6 if ultimate else 1 + 2 * rank):
        return 'hero_level_too_low'
    return 'allowed'
