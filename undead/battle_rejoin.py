"""Safe return to battle support/fire positions after a local pullback."""
from math import cos,sin,pi,ceil
from .scouting import SKELETONS
from .targeting import can_engage,unit_stats,in_weapon_range,buffs,abilities,webbed_air
from .nc_combo import DISABLED_CASTERS,spell_data
from .policy import Action


def rejoin_units(b,army,foes,now,pulls,blocked=()):
    g=b.g
    if b.teleport or b.action==Action.RETREAT or b.army_recovery.active:return
    foes=[e for e in foes if can_engage(e)]
    live={u.handle for u in army if u.hp>0}
    b.battle_rejoin={h:s for h,s in b.battle_rejoin.items() if h in live}
    excluded=set(blocked)|set(b.shield_moves)|set(b.shopping)|set(b.battle_shop.reserved)
    companions=[u for u in army if u.hp>0 and u.type not in SKELETONS and u.handle not in b.shopping]
    excluded.update(b.creep_aggro.protected)
    excluded.update(b.fiend_burrow.pending)
    core=[u for u in companions if u.handle not in excluded and u.type!='ucrm']
    for u in core:
        recovering=(u.handle in b.micro.pulling or u.handle in b.backline_guards or
                    u.type=='Udea' and b.dk_battle_recovering or
                    u.type=='uobs' and u.handle in b.statue_support.retreating or
                    u.handle in pulls and u.hp<=u.hp_max*.5)
        state=b.battle_rejoin.get(u.handle)
        if not recovering and not state:continue
        if not recovering and u.hp>=u.hp_max*.65:
            b.battle_rejoin.pop(u.handle,None);continue
        state=b.battle_rejoin.setdefault(u.handle,dict(quiet=None,point=None,planned=-100))
        if now<b.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS:continue
        allies=[v for v in companions if v.handle!=u.handle]
        main=[v for v in allies if v.type not in {'uobs','ubsp'} and v.handle not in b.micro.pulling] or allies
        if not main:continue
        stats=unit_stats(u.type);air=bool(stats and stats.is_air)
        melee=bool(stats and stats.weapons and max(w.range for w in stats.weapons)<=150 and (not u.is_hero or u.type=='Ucrl'))
        tanked=set()
        dangers=[]
        for e in foes:
            es=unit_stats(e.type)
            reach=max((w.range for w in es.weapons if ('air' if air else 'ground') in w.targets),default=0) if es else 0
            if not air and e.type=='Otch':
                lv=abilities(g,e).get('AOws',{}).get('level',3)
                reach=max(reach,float(spell_data()[0]['AOws']['Area'+str(lv if lv in (1,2,3) else 3)]))
            # Injured melee can exploit a soldier already occupied by a healthy
            # ally. Recheck every tick; heroes/control zones never get this waiver.
            target=g.current_target(e)
            if (melee and u.hp>=u.hp_max*.25 and not e.is_hero and target and
                    any(v.handle==target.handle for v in allies) and target.hp>=target.hp_max*.55 and
                    target.handle not in b.micro.pulling and in_weapon_range(g,e,target)):
                tanked.add(e.handle)
                continue
            if reach:dangers.append((e,reach))
        clearance=lambda p:min((g.dist(p,e)-r for e,r in dangers),default=9999)
        chased=any((t:=g.current_target(e)) is not None and t.handle==u.handle for e in foes)
        fast_support=u.type in {'Udea','uobs'}
        if chased or now-b.micro.hit.get(u.handle,-100)<(2 if fast_support else 3) or clearance(u)<80:
            state.update(quiet=None,point=None)
            continue
        if state['quiet'] is None:state['quiet']=now
        if now-state['quiet']<(1 if fast_support else 3):continue
        anchor=min(main,key=lambda v:sum(g.dist(v,w) for w in main))
        local=[v for v in allies if g.dist(v,anchor)<=900]
        protected=[v for v in local if v.type in {'Ulic','Nbrn','Ucrl','ubsp','uabo','ucry'}]
        recipient=min(protected,key=lambda v:(v.hp>v.hp_max*.5,not v.is_hero,v.hp/v.hp_max),default=anchor)
        aura=float(spell_data()[0]['AUau']['Area1'])
        def useful(p):
            if u.type=='Udea':
                if b.hero_pressure.wyvern_priority:
                    lich=next((v for v in local if v.type=='Ulic'),None)
                    fiends=[v for v in local if v.type=='ucry']
                    if lich and g.dist(p,lich)>700:return False
                    if fiends and sum(g.dist(p,v)<=700 for v in fiends)<ceil(len(fiends)/2):return False
                return g.dist(p,recipient)<=700 and sum(g.dist(p,v)<=aura for v in local)>=max(1,ceil(len(local)/2))
            return g.dist(p,anchor)<=600
        def firing(p):
            if u.type=='uban':
                return any(g.dist(p,e)<=float(spell_data()[0]['Acrs']['Rng1']) for e in foes)
            if u.type in {'Udea','uobs'} or not stats:return False
            return any(not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e) and
                       any(('air' if (es:=unit_stats(e.type)) and es.is_air and not webbed_air(g,e) else 'ground') in w.targets
                           and w.min_range<=g.dist(p,e)<=w.range for w in stats.weapons) for e in foes)
        origin=(u.x,u.y)
        grid=g.map()
        def safe_route(p):
            path=[origin,p] if air else g.walk_path(origin,p)
            if not path or g.dist(path[-1],p)>128:return False
            route=g.dist(origin,p) if air else g.path_distance(origin,p)
            if route is None or route>max(400,g.dist(origin,p)*1.4+128):return False
            previous=origin
            for end in path:
                count=max(1,ceil(g.dist(previous,end)/64))
                samples=[(previous[0]+(end[0]-previous[0])*i/count,previous[1]+(end[1]-previous[1])*i/count) for i in range(1,count+1)]
                if any(clearance(s)<80 or not air and (not grid or not grid.walkable(*s)) for s in samples):return False
                previous=end
            return True
        point=state['point']
        if point is None or now-state['planned']>=2 or not useful(point) or clearance(point)<100 or not safe_route(point):
            points=[origin]+[(anchor.x+r*cos(i*pi/8),anchor.y+r*sin(i*pi/8))
                             for r in (160,300,450,600,700) for i in range(16)]
            if melee:
                points += [(e.x+80*cos(i*pi/8),e.y+80*sin(i*pi/8))
                           for e in foes if e.handle in tanked for i in range(16)]
            points=[p for p in points if useful(p) and clearance(p)>=100]
            points.sort(key=lambda p:(not firing(p),g.dist(u,p)))
            point=None
            for p in points:
                if safe_route(p):point=p;break
            state.update(point=point,planned=now)
        if point is None:continue # No safe return route: preserve the escape owner.
        # Keep recovery ownership: returning to support is not permission to chase.
        if u.type=='Udea':b.micro.dk_support=None
        if g.dist(u,point)>65:
            pulls[u.handle]=point
            b.backline_safe_output.pop(u.handle,None)
            if b.due(('battle_rejoin',u.handle),now,2):
                b.log('battle_safe_rejoin',clock=now,handle=u.handle,type=u.type,point=point,
                      hp=u.hp,clearance=round(clearance(point)),anchor=anchor.handle,
                      role='aura_coil' if u.type=='Udea' else 'supply' if u.type=='uobs' else 'safe_output')
            continue
        if u.type in {'uobs','uban'}:
            pulls.pop(u.handle,None) # Let the supply owner cast from this safe station.
            if u.type=='uban':b.micro.pulling.discard(u.handle)
            continue
        pulls[u.handle]=origin
        b.backline_safe_output[u.handle]=now
        targets=[e for e in foes if in_weapon_range(g,u,e) and not buffs(g,e)&{'Bvul','BHds'} and
                 'Avul' not in abilities(g,e) and b.combat_progress.allowed(e,now)] if u.type!='Udea' else []
        current=g.current_target(u)
        if current and any(e.handle==current.handle for e in targets):continue
        if b.due(('battle_rejoin_fire',u.handle),now,1):
            target=min(targets,key=lambda e:(e.handle!=b.ranged_focus,e.hp),default=None)
            receipt=g.attack(u,target) if target else g.hold(u)
            b.log('battle_rejoin_stationed',clock=now,handle=u.handle,type=u.type,
                  target=target.handle if target else None,accepted=bool(receipt))
