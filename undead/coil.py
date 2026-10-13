"""Death Coil targets from local 1.27a data; no enemy state queries."""
from functools import lru_cache
import bootstrap
import w3paths
from w3slk import read_slk

@lru_cache(maxsize=1)
def damage_types():
    data={r['unitID']:r for r in read_slk(w3paths.game_data('UnitData.slk')) if r.get('unitID')}
    allowed=set()
    for row in read_slk(w3paths.game_data('UnitBalance.slk')):
        code=row.get('unitBalanceID')
        info=data.get(code)
        kinds=set(row.get('type','').lower().split(','))
        if info and info.get('race')!='critters' and not kinds & {'undead','mechanical','ward'} and row.get('isbldg')=='0':
            allowed.add(code)
    return frozenset(allowed)

def can_damage(code):
    # Unknown types are not assumed to be valid living targets.
    return code in damage_types()
