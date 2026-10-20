"""Death Coil targets from local 1.27a data; no enemy state queries."""
from functools import lru_cache
import bootstrap
import w3paths
from w3slk import read_slk


def ready(g, hero, now=None):
    """Unknown cooldown is never presented as zero; recovery is explicit."""
    if hasattr(g, 'coil_ready'):
        return g.coil_ready(hero, now)
    return g.cooldown(hero, 'AUdc') == 0


def level(g, hero):
    if hasattr(g, 'coil_level'):
        return g.coil_level(hero)
    return next((a['level'] for a in g.abilities(hero) if a['code'] == 'AUdc'), 0)


class CoilTelemetry:
    """Bounded recovery from missing learned skills, owned DK only.

    Keep raw cooldown/abilities unchanged. A remembered level permits an
    attempted order, not a claim of readiness or a confirmed cast.
    """
    def __init__(self):
        self.state = None
        self.log = lambda *a, **k: None

    def observe(self, g, hero, now):
        if (hero is None or hero.type != 'Udea' or hero.owner != g.me()
                or not hero.alive or not hero.has_detail):
            self.state = None
            return None
        s = self.state
        if s is None or s['handle'] != hero.handle or now < s['clock']:
            s = self.state = dict(handle=hero.handle, clock=now, level=0,
                                  next_at=now, failures=0, missing=False, pending=None)
        s['clock'] = now
        abilities = g.abilities(hero)
        ability = next((a for a in abilities if a['code'] == 'AUdc'), None)
        pending = s['pending']
        if pending:
            # Mana consumption is evidence of expenditure, not proof that the
            # intended heal/damage landed; the normal combat review checks HP.
            spent = (pending['accepted'] and 0 <= now-pending['clock'] <= 3
                     and pending['mana']-hero.mana >= 60)
            if spent or now-pending['clock'] >= 3:
                if spent:s['failures'] = 0
                self.log('coil_telemetry_attempt_observed', clock=now, hero=hero.handle,
                         mana_spent=spent, unconfirmed_attempts=s['failures'])
                s['pending'] = None
        if ability is not None:
            s['level'] = ability['level']
            cd = ability.get('cooldown')
            if cd is not None and cd > 0:
                s['next_at'] = max(s['next_at'], now+cd)
                s['failures'] = 0
            if s['missing']:
                self.log('coil_telemetry_restored', clock=now, hero=hero.handle)
                s['failures'] = 0
            s['missing'] = False
            s['reported_slots'] = len(abilities)
        else:
            if not s['missing']:
                # Cover an unobserved cast at the transition. AUdc Cool1..3=6
                # in the shipped 1.27a AbilityData; never reuse an old zero CD.
                s['next_at'] = max(s['next_at'], now+6)
                self.log('coil_telemetry_missing', clock=now, hero=hero.handle,
                         remembered_level=s['level'], slots=len(abilities))
            s['missing'] = True
            s['reported_slots'] = len(abilities)
        return s

    def can_attempt(self, g, hero, now):
        s = self.observe(g, hero, now)
        if s is None:return False
        if not s['missing']:return g.cooldown(hero, 'AUdc') == 0
        from .nc_combo import DISABLED_CASTERS
        # Aura failures can publish just one passive ability. Any nonempty
        # detailed list may omit a previously observed learned Coil; an empty
        # list is insufficient evidence that this snapshot is usable.
        return (s['reported_slots']>0 and s['level'] in (1, 2, 3) and hero.mana>=75
                and not (set(g.buffs(hero)) & DISABLED_CASTERS)
                and s['failures'] < 3 and now >= s['next_at'] and s['pending'] is None)

    def attempted(self, hero, now, accepted):
        s = self.state
        if s is None or s['handle'] != hero.handle:return
        # Count only missing-row recovery, not ordinary rejected spell orders.
        if s['missing']:s['failures'] += 1
        s['pending'] = dict(clock=now, mana=hero.mana, accepted=accepted)
        # Three seconds for order/cast observation, then the full six-second CD.
        s['next_at'] = now+9
        if s['missing']:
            self.log('coil_telemetry_fallback_attempt', clock=now, hero=hero.handle,
                     remembered_level=s['level'], accepted=accepted,
                     attempt=s['failures'], retry_at=s['next_at'], cooldown=None,
                     slots=s['reported_slots'])

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
