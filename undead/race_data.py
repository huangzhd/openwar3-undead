"""Public base unit race labels; no opponent metadata access."""
from functools import lru_cache
from w3slk import read_slk
import w3paths
@lru_cache(maxsize=1)
def unit_races():
    ids={'human':1,'orc':2,'undead':3,'nightelf':4}
    return {r['unitID']:ids[r['race']] for r in read_slk(w3paths.game_data('UnitData.slk')) if r.get('race') in ids}
