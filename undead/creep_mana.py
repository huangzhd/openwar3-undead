"""Preserve the dual-hero opening's mana, with one cast at each full refill."""


class CreepMana:
    def __init__(self, log):
        self.log = log
        self.spent = {}

    @staticmethod
    def dual(b,army):
        raw=getattr(b.g,'raw',b.g)
        heroes=b.g.my_heroes() if hasattr(raw,'my_heroes') else army
        return any(u.type=='Ulic' for u in heroes)

    def allow(self, b, caster, army, foes, now, cost, rescue=False):
        if not self.dual(b,army):
            return True
        if any(0 <= getattr(e, 'owner', 12) < 12 and e.owner != b.g.me() for e in foes):
            return True
        maximum = getattr(caster, 'mana_max', 0)
        state = self.spent.get(caster.handle)
        if state and caster.mana < maximum - 2:
            state['drop_seen'] = True
        if rescue:
            self.log('creep_mana_exception',clock=now,hero=caster.type,
                     reason='core_unit_rescue',mana=caster.mana)
            return True
        full = maximum > 0 and caster.mana >= maximum - 1
        if full and (not state or state['drop_seen']):
            return True
        # Missing a fourth fiend is not evidence of insufficient damage. Only
        # a visibly overwhelming engaged camp with almost no support qualifies.
        local = [u for u in army if u.type == 'ucry' and b.g.dist(u, caster) < 700]
        engaged = [e for e in foes if b.g.current_target(e) is not None
                   and any(b.g.current_target(e).handle == u.handle for u in army)]
        reserve = 150 if caster.type == 'Udea' else 125
        underpowered = (len(local) <= 1 and sum(e.hp for e in engaged) >
                        1.5 * sum(u.hp for u in army if b.g.dist(u, caster) < 700))
        if underpowered and caster.mana >= cost + reserve:
            self.log('creep_mana_exception', clock=now, hero=caster.type,
                     reason='engaged_camp_overwhelms_support', mana=caster.mana)
            return True
        return False

    def used(self, caster, now, spell):
        self.spent[caster.handle] = dict(drop_seen=False)
        self.log('creep_mana_spent', clock=now, hero=caster.type, spell=spell,
                 mana=caster.mana, mana_max=getattr(caster, 'mana_max', None))
