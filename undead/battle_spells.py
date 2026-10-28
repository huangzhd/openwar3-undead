"""Visible battle control: urgent TC silence and clustered ranged Nova."""
from .destroyer import ENEMY_BUFFS
from .hero_spell_telemetry import ready, level
from .nc_combo import spell_data, DISABLED_CASTERS, BLOCKED_BUFFS, BLOCKED_ABILITIES, aoe_threat
from .targeting import buffs, abilities, enemy_player, can_engage, unit_stats, webbed_air


def nova_wyverns(b,army,foes,now,blocked=()):
    g=b.g;lich,row=caster(b,army,'Ulic','AUfn',now,blocked)
    if not lich:return
    targets=[e for e in foes if e.type=='owyv' and spell_target(g,e) and g.dist(lich,e)<=row['range']]
    target=min(targets,key=lambda e:(not webbed_air(g,e),e.handle!=b.hero_pressure.preferred,
               -sum(g.dist(e,v)<=row['area'] for v in targets),e.hp),default=None)
    if not target or not b.due(('wyvern_nova',lich.handle),now,2):return
    key=(lich.handle,target.handle,'AUfn')
    if b.nc_combo.failures.get(key,0)>=3:return
    receipt=g.cast(lich,'frostnova',target=target)
    if not receipt:b.nc_combo.failures[key]=b.nc_combo.failures.get(key,0)+1
    b.log('battle_wyvern_nova_attempt',clock=now,target=target.handle,webbed=webbed_air(g,target),accepted=bool(receipt))
    if receipt:
        b.cast_until[lich.handle]=now+.8;b.hero_pressure.preferred=target.handle
from .structures import is_structure
from .coil import can_damage


def burst_troops(b,army,foes,now,blocked=()):
    """Nova the headhunter cluster; reserve DK mana for healing.

    Healing is performed by the caller first. Casts stay at current range;
    the estimate prevents redundant spells but never claims a confirmed kill.
    """
    if b.nc_combo.pending or b.nc_combo.single_attempt_at==now:return
    g=b.g
    heads=[e for e in foes if e.type in {'ohun','otbk'} and spell_target(g,e)]
    if not heads:return
    lich,row=caster(b,army,'Ulic','AUfn',now,blocked)
    candidates=[e for e in heads if lich and g.dist(lich,e)<=row['range']]
    def attempt(u,code,spell,target,**fields):
        key=(u.handle,target.handle,code)
        if b.nc_combo.failures.get(key,0)>=3 or now<b.nc_combo.retry_at.get(key,0):return False
        b.nc_combo.retry_at[key]=now+2
        accepted=bool(g.cast(u,spell,target=target))
        if not accepted:b.nc_combo.failures[key]=b.nc_combo.failures.get(key,0)+1
        b.log('battle_troop_spell_attempt',clock=now,spell=spell,target=target.handle,
              type=target.type,accepted=accepted,**fields)
        return accepted
    if candidates:
        target=max(candidates,key=lambda e:(sum(g.dist(e,v)<=row['area'] for v in heads),
                   e.handle==b.hero_pressure.preferred,-e.hp))
        if b.due(('troop_nova',lich.handle,target.handle),now,2):
            receipt=attempt(lich,'AUfn','frostnova',target,
                            clustered=sum(g.dist(target,v)<=row['area'] for v in heads))
            if receipt:
                b.cast_until[lich.handle]=now+.8
                b.hero_pressure.preferred=target.handle


def spell_target(g,u):
    return (can_engage(u) and enemy_player(g,u) and getattr(u,'has_detail',False)
            and not is_structure(u)
            and not buffs(g,u)&BLOCKED_BUFFS and not abilities(g,u).keys()&BLOCKED_ABILITIES)


def caster(b,army,kind,code,now,blocked):
    g=b.g
    u=next((u for u in army if u.type==kind and u.hp>0),None)
    if (u is None or u.handle in blocked or now<b.cast_until.get(u.handle,0)
            or buffs(g,u)&(DISABLED_CASTERS|{'BOhx'})):
        return None,None
    if not hasattr(g,'abilities') and not hasattr(g,'hero_spell_level'):return None,None
    learned=level(g,u,code)
    if learned not in (1,2,3):return None,None
    row=spell_data()[0][code];suffix=str(learned)
    if u.mana<float(row['Cost'+suffix]) or not ready(g,u,code,now):return None,None
    number=lambda key:float(row[key]) if row.get(key) not in (None,'','-') else 0
    return u,dict(range=number('Rng'+suffix),area=number('Area'+suffix),
                  hero_duration=number('HeroDur'+suffix))


def silence_key_hero(b,army,foes,now,blocked=(),tc_only=False):
    g=b.g;dark,row=caster(b,army,'Nbrn','ANsi',now,blocked)
    if dark is None:return
    targets=[e for e in foes if e.is_hero and spell_target(g,e) and g.dist(dark,e)<=row['range']
             and not buffs(g,e)&{'BNsi','BNso'}
             and (not tc_only or e.type=='Otch')
             and any(u.type not in {'uobs','ubsp'} and g.dist(u,e)<=550 for u in army)]
    if not targets:return
    # An approaching TC is silenced immediately, even with Roar/Speed buffs.
    # Other heroes retain the ordinary dispel-before-silence ordering.
    target=min(targets,key=lambda e:({'Otch':0,'Oshd':1}.get(e.type,2),not aoe_threat(g,e),g.dist(dark,e),e.hp))
    if target.type!='Otch' and buffs(g,target)&ENEMY_BUFFS:return
    attempts=getattr(b,'silence_attempt_at',{})
    if now-attempts.get(dark.handle,-100)<1:return
    attempts[dark.handle]=now;b.silence_attempt_at=attempts
    receipt=g.cast(dark,'silence',target=target)
    b.log('battle_silence_attempt',clock=now,target=target.handle,type=target.type,
          accepted=bool(receipt),distance=round(g.dist(dark,target)))
    if receipt:
        b.cast_until[dark.handle]=now+.8
        # Buff lists may lag/omit an effect. Reserve the entire hero duration,
        # not just the cast window, for every visible hero inside Silence.
        pending=getattr(b,'silence_protected_until',{})
        for hero in foes:
            if hero.is_hero and g.dist(hero,target)<=row['area']:
                pending[hero.handle]=max(pending.get(hero.handle,0),now+row['hero_duration']+1.5)
        b.silence_protected_until=pending


def wait_for_opening_nc(b,army,target,now,blocked=()):
    """Briefly keep both spells ready while silenced TC enters Coil range."""
    if b.opening_nc_deadline is None:b.opening_nc_deadline=now+3
    if now>=b.opening_nc_deadline or b.nc_combo.pending:return False
    g=b.g
    dk,_=caster(b,army,'Udea','AUdc',now,blocked)
    lich,_=caster(b,army,'Ulic','AUfn',now,blocked)
    if not dk or not lich or dk.mana<150 or not spell_target(g,target):return False
    if g.dist(dk,target)<=750 and g.dist(lich,target)<=750:return False
    if max(g.dist(dk,target),g.dist(lich,target))>1100:return False
    if not (buffs(g,target)&{'BNsi','BNso'} or getattr(b,'silence_protected_until',{}).get(target.handle,0)>now):return False
    if b.due('opening_nc_wait',now,1):
        b.log('battle_opening_nc_wait',clock=now,target=target.handle,dk_distance=round(g.dist(dk,target)),
              lich_distance=round(g.dist(lich,target)),until=b.opening_nc_deadline)
    return True


def nova_tc(b,army,target,now,blocked=()):
    if b.nc_combo.pending or b.nc_combo.single_attempt_at==now:return
    g=b.g;lich,row=caster(b,army,'Ulic','AUfn',now,blocked)
    if lich is None or not spell_target(g,target) or g.dist(lich,target)>row['range']:return
    key=(lich.handle,target.handle,'AUfn')
    if b.nc_combo.failures.get(key,0)>=3 or now<b.nc_combo.retry_at.get(key,0):return
    b.nc_combo.retry_at[key]=now+2
    receipt=g.cast(lich,'frostnova',target=target)
    if not receipt:b.nc_combo.failures[key]=b.nc_combo.failures.get(key,0)+1
    event={'Otch':'battle_tc_nova_attempt','Ofar':'battle_farseer_nova_attempt',
           'edcm':'battle_bear_nova_attempt'}.get(target.type,'battle_orc_hero_nova_attempt')
    b.log(event,clock=now,target=target.handle,type=target.type,accepted=bool(receipt))
    if receipt:b.cast_until[lich.handle]=now+.8


def nova_cluster(b,army,foes,now,blocked=()):
    # Preserve the finite NC finisher's spell reservation and observation window.
    if b.nc_combo.pending or b.nc_combo.single_attempt_at==now:return
    g=b.g;lich,row=caster(b,army,'Ulic','AUfn',now,blocked)
    if lich is None:return
    targets=[]
    for e in foes:
        stats=unit_stats(e.type)
        if (not e.is_hero and spell_target(g,e) and stats and
                any(w.range>=400 for w in stats.weapons)):
            targets.append(e)
    centers=[e for e in targets if g.dist(lich,e)<=row['range']]
    # A low-health Kodo must not divert the headhunter clear-up phase.
    if b.hero_pressure.orc_seen:
        centers=[e for e in centers if e.type in {'ohun','otbk'}] or centers
    groups=[(sum(g.dist(e,v)<=row['area'] for v in targets),e) for e in centers]
    if not groups:return
    count,target=max(groups,key=lambda pair:(pair[0],-pair[1].hp))
    if count<2:return
    receipt=g.cast(lich,'frostnova',target=target)
    b.log('battle_cluster_nova_attempt',clock=now,target=target.handle,type=target.type,
          clustered=count,accepted=bool(receipt))
    if receipt:b.cast_until[lich.handle]=now+.8
