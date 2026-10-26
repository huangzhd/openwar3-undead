"""Ground tanks and stationary, multi-target Impale shared by both controllers."""
from functools import lru_cache
from math import hypot

import w3paths
from w3slk import read_slk
from .battle_spells import caster, spell_target
from .hero_spell_telemetry import level
from .nc_combo import spell_data, DISABLED_CASTERS
from .policy import Action
from .targeting import buffs, can_engage, enemy_player, in_weapon_range, unit_stats
from .structures import is_structure

TANKS={'Ucrl','uabo'}


@lru_cache(maxsize=1)
def organic_types():
    return frozenset(row['unitBalanceID'] for row in read_slk(w3paths.game_data('UnitBalance.slk'))
                     if row.get('unitBalanceID') and row.get('isbldg')=='0'
                     and not set(row.get('type','').lower().split(','))&{'mechanical','ward'})


def exclusions(b,blocked=()):
    return (set(blocked)|set(b.micro.pulling)|set(b.shield_moves)|set(b.shopping)|
            set(b.battle_shop.reserved)|set(b.creep_aggro.protected))


def impale(b,army,foes,now,blocked=()):
    if b.teleport or b.action==Action.RETREAT or b.army_recovery.active:return
    g=b.g;hero,row=caster(b,army,'Ucrl','AUim',now,exclusions(b,blocked))
    if not hero or hero.hp<=hero.hp_max*.45:return
    if now<b.impale_after.get(hero.handle,-100):return
    suffix=str(level(g,hero,'AUim'));data=spell_data()[0]['AUim']
    length=min(row['range'],float(data['DataA'+suffix]))
    # Conservative half-width of the local spell's area; count a forward strip,
    # never a circle around a target or units behind the caster.
    width=row['area']/2
    targets=[e for e in foes if e.visible_to(g.me()) and spell_target(g,e) and e.type in organic_types()
             and (s:=unit_stats(e.type)) and not s.is_air and 'BUim' not in buffs(g,e)
             and 1<g.dist(hero,e)<=hypot(length,width)]
    if not targets:return
    directions=[((e.x-hero.x)/g.dist(hero,e),(e.y-hero.y)/g.dist(hero,e)) for e in targets]
    candidates=list(directions)
    for i,a in enumerate(directions):
        for v in directions[i+1:]:
            x,y=a[0]+v[0],a[1]+v[1];d=hypot(x,y)
            if d>1e-6:candidates.append((x/d,y/d))
    best=None
    for x,y in candidates:
        hit=[e for e in targets if 0<=(e.x-hero.x)*x+(e.y-hero.y)*y<=length
             and abs((e.x-hero.x)*y-(e.y-hero.y)*x)<=width]
        score=(len(hit),sum(e.is_hero for e in hit),-sum(e.hp for e in hit))
        if hit and (best is None or score>best[0]):best=(score,(hero.x+length*x,hero.y+length*y),hit)
    if best is None:return
    _,point,hit=best
    receipt=g.cast(hero,'impale',x=point[0],y=point[1])
    b.impale_after[hero.handle]=now+(float(data['Cool'+suffix]) if receipt else 2)
    b.log('battle_impale_attempt',clock=now,handle=hero.handle,point=point,
          predicted_targets=[e.handle for e in hit],predicted_count=len(hit),accepted=bool(receipt))
    if receipt:b.cast_until[hero.handle]=now+1


def attack_frontline(b,army,foes,now):
    g=b.g
    if not any(enemy_player(g,e) for e in foes):return set()
    tanks=[u for u in army if u.type in TANKS]
    handled={u.handle for u in tanks}
    if b.teleport or b.action==Action.RETREAT or b.army_recovery.active:return handled
    blocked=exclusions(b)
    targets=[e for e in foes if enemy_player(g,e) and can_engage(e) and not is_structure(e)
             and (s:=unit_stats(e.type)) and not s.is_air and b.combat_progress.allowed(e,now)]
    for u in tanks:
        if (u.hp<=u.hp_max*.45 or u.handle in blocked or now<b.cast_until.get(u.handle,0)
                or buffs(g,u)&DISABLED_CASTERS or b.backline_safe_output.get(u.handle,-100)>=now):continue
        current=g.current_target(u)
        if current and any(e.handle==current.handle and in_weapon_range(g,u,e) for e in targets):continue
        nearby=[e for e in targets if g.dist(u,e)<=900]
        target=min(nearby,key=lambda e:(e.is_hero,g.dist(u,e)),default=None)
        if target is None:continue
        point=(target.x,target.y);path=g.path_distance((u.x,u.y),point)
        if path is None or path>g.dist(u,point)*1.5+128:continue
        previous=b.frontline_orders.get(u.handle)
        if previous and now-previous['at']<5 and g.dist(previous['point'],point)<160:continue
        if not b.due(('frontline_attack_move',u.handle),now,1):continue
        receipt=g.attack_move(u,*point)
        if receipt:b.frontline_orders[u.handle]=dict(at=now,point=point)
        b.log('battle_frontline_attack_move',clock=now,handle=u.handle,type=u.type,
              point=point,accepted=bool(receipt))
    return handled
