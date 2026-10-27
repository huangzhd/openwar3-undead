"""Owned hero inventory access and bounded missing-spell recovery."""
from openwar3 import Game as SDKGame
from .coil import CoilTelemetry
from .hero_spell_telemetry import HeroSpellTelemetry,HERO_CODES,ORDERS,TOGGLES


class Game(SDKGame):
    def learn(self,hero,ability):
        # KK comparison mode: never issue W3P learn; local/training keeps the SDK path.
        if getattr(self,'manual_skill_learning',False) is True:return False
        return super().learn(hero,ability)

    def _coil(self):
        if not hasattr(self, '_coil_telemetry'):
            self._coil_telemetry = CoilTelemetry()
        return self._coil_telemetry

    def observe_coil(self, heroes, now, log):
        # SDK queries can advance beyond the caller's tick snapshot.
        # Do not misclassify that stale timestamp as a new game.
        now = max(now, self.clock())
        telemetry = self._coil()
        telemetry.log = log
        telemetry.observe(self, next((h for h in heroes if h.type == 'Udea'), None), now)
        spells=self._hero_spells();spells.log=log;spells.prune(heroes,now)
        for h in heroes:
            for code in HERO_CODES.get(h.type,()):spells.observe(self,h,code,now)

    def _hero_spells(self):
        if not hasattr(self,'_hero_spell_telemetry'):
            self._hero_spell_telemetry=HeroSpellTelemetry()
        return self._hero_spell_telemetry

    def hero_spell_ready(self,hero,code,now=None):
        if code=='AUdc':return self.coil_ready(hero,now)
        return self._hero_spells().can_attempt(self,self._fresh(hero),code,
                                               self.clock() if now is None else max(now,self.clock()))

    def hero_spell_level(self,hero,code):
        if code=='AUdc':return self.coil_level(hero)
        s=self._hero_spells().observe(self,self._fresh(hero),code,self.clock())
        return s['level'] if s else 0

    def coil_ready(self, hero, now=None):
        return self._coil().can_attempt(self, self._fresh(hero), self.clock() if now is None else now)

    def coil_level(self, hero):
        s = self._coil().observe(self, self._fresh(hero), self.clock())
        return s['level'] if s else 0

    def cast(self, u, spell, target=None, x=None, y=None):
        if spell != 'deathcoil':
            toggle=spell in TOGGLES and target is None and x is None and y is None
            code=(TOGGLES if toggle else ORDERS).get(spell)
            if code is None:return super().cast(u, spell, target=target, x=x, y=y)
            current=self._fresh(u);now=self.clock();telemetry=self._hero_spells()
            if not telemetry.can_attempt(self,current,code,now,toggle):return False
            result=super().cast(current,spell,target=target,x=x,y=y)
            telemetry.attempted(current,code,now,bool(result),toggle)
            if not result:
                telemetry.log('hero_spell_order_rejected',clock=now,hero=current.handle,
                              ability=code,spell=spell,target=getattr(target,'type',None),
                              reason=getattr(result,'reason',None))
            return result
        current = self._fresh(u)
        now = self.clock()
        if not self._coil().can_attempt(self, current, now):return False
        result = super().cast(current, spell, target=target, x=x, y=y)
        self._coil().attempted(current, now, bool(result))
        if not result:
            self._coil().log('hero_spell_order_rejected',clock=now,hero=current.handle,
                             ability='AUdc',spell=spell,target=getattr(target,'type',None),
                             reason=getattr(result,'reason',None))
        return result

    def inventory(self, hero):
        bag = super().inventory(hero)
        if bag is not None or hero is None:
            return bag
        # LR 20261012-144835: after 681.98s Lich abilities omitted AInv,
        # although the same fair detailed snapshot still contained the orb.
        # Read current own slots, never infer possession from an older bag.
        current = self.unit(hero.handle)
        if (current is None or current.owner != self.me() or not current.alive
                or not current.is_hero or not current.has_detail):
            return None
        items = current.items
        return list(items) if items is not None and len(items) == 6 else None


class TrainingGame(Game):
    """Own N001 is Nbrn in the SHA-pinned UD V61 map only.

    Its object overrides change costs/requirements, never skills or combat
    stats. Normalize the fair view so every shared combat component and
    fresh-handle lookup sees the same identity; retain the raw type for logs.
    Ordinary games and the full-map audit keep their original identities.
    """
    def _view(self, snapshot):
        from dataclasses import replace
        view = super()._view(snapshot)
        units = []
        for unit in view.units:
            if unit.owner == view.me and unit.type == 'N001' and unit.is_hero:
                unit = replace(unit, type='Nbrn')
                unit.raw_type = 'N001'
            units.append(unit)
        return replace(view, units=units, by_handle={u.handle: u for u in units})
