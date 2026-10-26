"""Explicit bounded attempts when owned heroes' learned spell rows disappear.

Raw ability lists and cooldowns remain unchanged. Mana expenditure is not
proof of a hit, buff application, or successful autocast configuration.
"""
HERO_CODES={'Ulic':('AUfn','AUfu'), 'Nngs':('ANfl','ANfa'), 'Nbrn':('ANsi','ANba'), 'Ucrl':('AUim',)}
ORDERS={'frostnova':'AUfn','frostarmor':'AUfu','forkedlightning':'ANfl',
        'silence':'ANsi','coldarrows':'ANfa','blackarrow':'ANba',
        'coldarrowstarg':'ANfa','impale':'AUim'}
TOGGLES={'frostarmoroff':'AUfu','frostarmoron':'AUfu',
         'coldarrows':'ANfa','coldarrowson':'ANfa','coldarrowsoff':'ANfa',
         'blackarrowon':'ANba','blackarrowoff':'ANba'}


def ready(g,hero,code,now=None):
    if code=='AUdc':
        from .coil import ready as coil_ready
        return coil_ready(g,hero,now)
    return g.hero_spell_ready(hero,code,now) if hasattr(g,'hero_spell_ready') else g.cooldown(hero,code)==0


def level(g,hero,code):
    if code=='AUdc':
        from .coil import level as coil_level
        return coil_level(g,hero)
    return (g.hero_spell_level(hero,code) if hasattr(g,'hero_spell_level') else
            next((a['level'] for a in g.abilities(hero) if a['code']==code),0))


class HeroSpellTelemetry:
    def __init__(self):
        self.states={};self.log=lambda *a,**kw:None

    def prune(self,heroes,now):
        handles={h.handle for h in heroes if h.alive and h.has_detail}
        self.states={k:s for k,s in self.states.items() if k[0] in handles and now>=s['clock']}

    @staticmethod
    def limits(code,level):
        from .nc_combo import spell_data
        row=spell_data()[0][code];suffix=str(level if level in (1,2,3) else 1)
        def number(key):
            value=row.get(key+suffix)
            return float(row.get(key+'1',0) if value in (None,'','-') else value)
        return number('Cool'),number('Cost')

    def observe(self,g,hero,code,now):
        if hero is None:return None
        key=(hero.handle,code)
        if (code not in HERO_CODES.get(hero.type,()) or hero.owner!=g.me()
                or not hero.alive or not hero.has_detail):
            self.states.pop(key,None);return None
        s=self.states.get(key)
        if s is None or now<s['clock']:
            s=self.states[key]=dict(clock=now,level=0,missing=False,next_at=now,
                                   failures=0,pending=None,toggle_attempts=0,toggle_at=now)
        s['clock']=now
        abilities=g.abilities(hero);s['slots']=len(abilities)
        row=next((a for a in abilities if a['code']==code),None)
        p=s['pending']
        if p:
            spent=bool(p['accepted'] and 0<=now-p['clock']<=3 and
                       p['mana']-hero.mana>=max(1,.8*p['cost']))
            if spent or now-p['clock']>=3:
                if spent:s['failures']=0
                self.log('hero_spell_attempt_observed',clock=now,hero=hero.handle,ability=code,
                         mana_spent=spent,unconfirmed_attempts=s['failures'])
                s['pending']=None
        if row is not None:
            s['level']=row['level']
            cd=row.get('cooldown')
            if cd is not None and cd>0:s['next_at']=max(s['next_at'],now+cd)
            if s['missing']:
                self.log('hero_spell_telemetry_restored',clock=now,hero=hero.handle,ability=code)
                s['failures']=0;s['toggle_attempts']=0
            s['missing']=False
        else:
            if not s['missing']:
                cooldown,_=self.limits(code,s['level'])
                s['next_at']=max(s['next_at'],now+max(1,cooldown))
                self.log('hero_spell_telemetry_missing',clock=now,hero=hero.handle,
                         ability=code,remembered_level=s['level'],slots=s['slots'])
            s['missing']=True
        return s

    def can_attempt(self,g,hero,code,now,toggle=False):
        from .nc_combo import DISABLED_CASTERS
        s=self.observe(g,hero,code,now)
        if s is None or s['level'] not in (1,2,3):return False
        if set(g.buffs(hero)) & DISABLED_CASTERS:return False
        if not s['missing']:
            return True if toggle else g.cooldown(hero,code)==0
        if s['slots']==0:return False
        if toggle:return s['toggle_attempts']<3 and now>=s['toggle_at']
        _,cost=self.limits(code,s['level'])
        pending=any(k[0]==hero.handle and state['pending'] is not None for k,state in self.states.items())
        return (hero.mana>=cost and s['failures']<3 and now>=s['next_at'] and not pending)

    def attempted(self,hero,code,now,accepted,toggle=False):
        s=self.states.get((hero.handle,code))
        if s is None:return
        if toggle:
            if s['missing']:
                s['toggle_attempts']+=1;s['toggle_at']=now+20
                self.log('hero_spell_toggle_fallback_attempt',clock=now,hero=hero.handle,ability=code,
                         accepted=accepted,attempt=s['toggle_attempts'],effect_confirmed=False)
            return
        # A second known spell must not donate its mana consumption to the first.
        for key,state in self.states.items():
            if key[0]==hero.handle:state['pending']=None
        cooldown,cost=self.limits(code,s['level'])
        # Normal orders (including rejected targets) must not consume the
        # separate missing-row recovery budget before an aura hides the spell.
        if s['missing']:s['failures']+=1
        s['pending']=dict(clock=now,mana=hero.mana,cost=cost,accepted=accepted)
        s['next_at']=now+cooldown+3
        if s['missing']:
            self.log('hero_spell_fallback_attempt',clock=now,hero=hero.handle,ability=code,
                     accepted=accepted,attempt=s['failures'],retry_at=s['next_at'],
                     remembered_level=s['level'],cooldown=None,slots=s['slots'])
