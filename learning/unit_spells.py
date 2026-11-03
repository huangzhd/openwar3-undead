"""Direct unit-target spell orders within the LR primitive target subset."""
from functools import lru_cache
import math

SPELLS = {
    'AUdc': ('Udea', 'deathcoil', 0xD00FE),
    'AUfn': ('Ulic', 'frostnova', 0xD0102),
    'AUfu': ('Ulic', 'frostarmor', 0xD0101),
}
OWN_TARGETS = frozenset(('Udea','Udre','Ucrl','Ulic','uaco','ugho','ucry','uabo','uban','unec','ugar'))
HUMAN_TARGETS = frozenset(('Hamg','Hmkg','Hpal','Hblm','hpea','hmil','hfoo','hrif','hkni','hmpr','hsor','hdhw','hgry'))
DISABLES = ('BNsi','BEsh','BPse','BPSE','BUsl','BSTN','Bstn','Bply','Bcyc','BOhx')
BUFFS = ('BUfa', *DISABLES)


@lru_cache(maxsize=1)
def parameters():
    import w3paths
    from w3slk import read_slk
    rows = {r['alias']:r for r in read_slk(w3paths.game_data('AbilityData.slk')) if r.get('alias') in SPELLS}
    return {skill:tuple((int(rows[skill]['Cost'+str(i)]),int(rows[skill]['Rng'+str(i)])) for i in (1,2,3))
            for skill in SPELLS}


def statuses(raw):
    return [dict(unit=list(u.handle),buffs=sorted(set(u.buffs).intersection(BUFFS)) if u.has_detail else None)
            for u in raw.units if u.owner==1]


def buffs(observation, handle):
    return next((r['buffs'] for r in observation.get('own_spell_status',[]) if r['unit']==handle), None)


def preflight(action, observation, source, target):
    skill = action['skill']
    if source['type'] != SPELLS[skill][0]:
        return 'wrong_spell_caster'
    status = buffs(observation, source['handle'])
    if status is None:
        return 'caster_status_unknown'
    if any(b in DISABLES for b in status):
        return 'caster_disabled'
    rows = [a for a in source['abilities'] or () if a['code']==skill]
    if len(rows)!=1 or type(rows[0]['level']) is not int or not 1<=rows[0]['level']<=3:
        return 'spell_rank_unknown'
    if rows[0]['cooldown'] != 0 or type(rows[0]['cooldown']) not in (int,float):
        return 'spell_not_ready'
    cost, distance = parameters()[skill][rows[0]['level']-1]
    if type(source['mana']) not in (int,float) or not math.isfinite(source['mana']) or source['mana'] < cost:
        return 'spell_mana_insufficient_or_unknown'
    if target is None or not target['alive'] or target.get('hp') is None or target['hp'] <= 0:
        return 'spell_target_not_observed_alive'
    friendly = target['owner']==1 and target['type'] in OWN_TARGETS
    enemy = target['owner']==2 and target['type'] in HUMAN_TARGETS
    if skill=='AUdc' and not (enemy or friendly and source['handle']!=target['handle']):
        return 'invalid_coil_target'
    if skill=='AUfn' and not enemy:
        return 'invalid_nova_target'
    if skill=='AUfu' and not friendly:
        return 'invalid_armor_target'
    if any(type(u[k]) not in (float,int) or not math.isfinite(u[k]) for u in (source,target) for k in ('x','y')):
        return 'spell_position_unknown'
    if math.hypot(source['x']-target['x'],source['y']-target['y']) > distance:
        return 'spell_target_out_of_range'
    return 'allowed'
