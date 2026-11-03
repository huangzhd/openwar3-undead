"""Bounded P1 research reads and fixed LR undead technology prerequisites."""
from functools import lru_cache
from learning.economy_actions import HALLS, completed, known_number

PRODUCERS = {'Rura':'ugrv', 'Rucr':'ugrv', 'Ruwb':'usep'}
MAX_LEVEL = {'Rura':3, 'Rucr':3, 'Ruwb':1}
MAX_AGE = 8


@lru_cache(maxsize=1)
def costs():
    import w3paths
    from w3slk import read_slk
    result = {}
    for row in read_slk(w3paths.game_data('UpgradeData.slk')):
        code = row.get('upgradeid')
        if code not in MAX_LEVEL:
            continue
        if int(row['maxlevel']) != MAX_LEVEL[code]:
            raise ValueError('Research level catalog mismatch: '+code)
        result[code] = tuple({key:int(row[key+'base'])+i*int(row[key+'mod']) for key in ('gold','lumber')}
                             for i in range(MAX_LEVEL[code]))
    if set(result)!=set(MAX_LEVEL):
        raise ValueError('Missing public research cost')
    return result


def read_level(recorder, code):
    game=recorder.game
    raw=game.world.read()
    recorder.boundary.validate(game,raw)
    value=game.tech(code,player=1)
    after=game.world.read()
    recorder.boundary.validate(game,after)
    if type(value) is not int or not 0<=value<=MAX_LEVEL[code] or not 0<=after.clock-raw.clock<=MAX_AGE:
        value=None
    recorder.research_levels[code]=dict(level=value,clock=raw.clock)
    return value


def preflight(action, observation, source, abilities):
    code, desired = action['code'], action['level']
    if source['type']!=PRODUCERS[code] or 'Aque' not in abilities:
        return 'wrong_research_producer'
    sample=observation.get('research_levels',{}).get(code)
    if not sample or sample['level'] is None:
        return 'research_level_unknown'
    if not 0<=observation['clock']-sample['clock']<=MAX_AGE:
        return 'research_level_stale'
    if sample['level']!=desired-1:
        return 'research_not_next_level'
    production=observation.get('production')
    if not isinstance(production,list) or not completed(source,production):
        return 'research_producer_not_ready'
    if any(p['building']==source['handle'] or code in p['queue'] for p in production):
        return 'research_production_busy'
    tier=2 if code=='Ruwb' else desired
    ready={u['type'] for u in observation['units'] if u['owner']==1 and u['alive'] and completed(u,production)}
    if not ready.intersection(HALLS[tier-1:]) or code=='Ruwb' and 'ugrv' not in ready:
        return 'research_prerequisites_missing'
    resources=observation.get('resources') or {}
    for key,amount in costs()[code][desired-1].items():
        if not known_number(resources.get(key)):
            return 'resources_unknown'
        if resources[key]<amount:
            return 'insufficient_'+key
    return 'allowed'
