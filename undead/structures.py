"""Building identity from the installed public unit data, including mobile ancients."""
from functools import lru_cache
import bootstrap
import w3paths
from w3slk import read_slk

@lru_cache(maxsize=1)
def structure_types():
    return frozenset(row['unitBalanceID'] for row in read_slk(w3paths.game_data('UnitBalance.slk'))
                     if row.get('isbldg')=='1' and row.get('unitBalanceID')!='ngol')

def is_structure(unit):
    # Neutral resource nodes are not enemy structures; player-owned ugol/egol are.
    # Movement speed is not a building flag: Night Elf ancients can uproot.
    return unit.type in structure_types()
