"""Short, observed TC avoidance windows; never a continuous combat formation."""
from math import hypot,cos,sin,pi
from .targeting import abilities,buffs,can_engage,unit_stats,webbed_air
from .nc_combo import DISABLED_CASTERS,spell_data
from .policy import Action


class StompResponse:
    def __init__(self,log):
        self.log=log;self.observed={};self.windows={};self.next_at={}
        self.web_until=0;self.web_after=0;self.web_pending=None;self.moving={}

    def tick(self,b,army,foes,now,pulls,blocked=()):
        g=b.g;self.moving={}
        chiefs=[e for e in foes if e.type=='Otch' and can_engage(e)]
        protected=[u for u in army if u.type in {'ucry','Ulic'} and u.hp>0]
        enabled=(b.hero_pressure.wyvern_priority and not b.hero_pressure.blade_wyvern_plan
                 and not any(u.type in {'uabo','Ucrl'} for u in army))
        excluded=set(pulls)|set(blocked)|b.micro.pulling|b.shopping|set(b.shield_moves)|b.battle_shop.reserved
        if not enabled or b.teleport or b.action==Action.RETREAT or b.army_recovery.active:
            self.windows.clear();self.observed.clear();return
        current={}
        for tc in chiefs:
            row=abilities(g,tc).get('AOws',{});cd=row.get('cooldown')
            if not row.get('level') or cd is None:continue
            radius=float(spell_data()[0]['AOws']['Area'+str(min(3,row['level']))])
            distance=min((g.dist(tc,u) for u in protected),default=9999)
            old=self.observed.get(tc.handle)
            current[tc.handle]=(now,cd,distance)
            cast=bool(old and now-old[0]<=1.5 and cd>old[1]+.5)
            if cast:
                self.windows.pop(tc.handle,None);self.web_until=now+4.5
                self.log('battle_stomp_observed',clock=now,handle=tc.handle,evidence='visible_cooldown_transition',hits_confirmed=False)
            disabled=bool(buffs(g,tc)&(DISABLED_CASTERS|{'BNsi','BNso'}))
            if cd>1 or disabled or getattr(tc,'mana',0)<90:
                self.windows.pop(tc.handle,None);continue
            window=self.windows.get(tc.handle)
            if window and now>=window['until']:
                self.windows.pop(tc.handle,None);window=None
            closing=bool(old and now-old[0]<=1.5 and distance<old[2]-8)
            if window is None and now>=self.next_at.get(tc.handle,0) and distance<radius+180 and (closing or distance<radius+100):
                window=dict(until=now+1.8,points={});self.windows[tc.handle]=window
                self.next_at[tc.handle]=now+5
            if not window:continue
            points=window['points']
            for i,u in enumerate(sorted(protected,key=lambda u:u.handle)):
                if u.handle in excluded or u.hp<=u.hp_max*.45 or now<b.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS:continue
                if g.dist(u,tc)>radius+180 and u.handle not in points:continue
                point=points.get(u.handle)
                if point is None:
                    dx,dy=u.x-tc.x,u.y-tc.y;length=hypot(dx,dy)
                    if length<1:dx,dy,length=-1,0,1
                    candidates=[]
                    for angle in (0,25,-25,50,-50):
                        angle=(angle+(18 if i%2 else -18))*pi/180
                        vx,vy=(dx*cos(angle)-dy*sin(angle))/length,(dx*sin(angle)+dy*cos(angle))/length
                        p=(tc.x+vx*(radius+190),tc.y+vy*(radius+190))
                        travel=g.dist(u,p)
                        if travel>380 or travel<40 or g.dist(p,tc)<g.dist(u,tc):continue
                        if any(g.dist((u.x+(p[0]-u.x)*j/6,u.y+(p[1]-u.y)*j/6),tc)<min(radius+60,g.dist(u,tc))-5 for j in range(1,7)):continue
                        grid=g.map()
                        route=g.path_distance((u.x,u.y),p)
                        if not grid or not grid.walkable(*p) or route is None or route>travel+80:continue
                        # Moving away from TC must not run into a different firing line.
                        safe=True
                        for e in foes:
                            if e.handle==tc.handle:continue
                            s=unit_stats(e.type);reach=max((w.range for w in s.weapons if 'ground' in w.targets),default=0) if s else 0
                            if reach and any(g.dist((u.x+(p[0]-u.x)*j/5,u.y+(p[1]-u.y)*j/5),e)<min(reach+60,g.dist(u,e))-15 for j in range(1,6)):
                                safe=False;break
                        if safe:
                            separation=min((g.dist(p,q) for q in points.values()),default=200)
                            candidates.append((separation<150,travel-min(200,separation)*.5,p))
                    if not candidates:continue
                    point=min(candidates)[2];points[u.handle]=point
                    self.log('battle_stomp_dodge',clock=now,handle=u.handle,type=u.type,tc=tc.handle,point=point,expires=window['until'])
                pulls[u.handle]=point;self.moving[u.handle]=now
        self.observed=current
        self.windows={h:w for h,w in self.windows.items() if h in current and now<w['until']}
        self.web(b,army,foes,now,pulls,blocked)

    def web(self,b,army,foes,now,pulls,blocked):
        g=b.g
        if self.windows or now>self.web_until or now<self.web_after:return
        if self.web_pending:
            target=next((e for e in foes if e.handle==self.web_pending[0]),None)
            if target and webbed_air(g,target):
                self.log('battle_web_observed',clock=now,target=target.handle)
                self.web_pending=None
            elif target and now<self.web_pending[1]:return
            else:self.web_pending=None
        birds=[e for e in foes if e.type=='owyv' and can_engage(e) and not buffs(g,e)&{'Bvul','BHds','Bams'}]
        if not birds or any(webbed_air(g,e) for e in birds):return
        if not hasattr(g,'tech_many') or (g.tech_many(['Ruwb']).get('Ruwb') or 0)<1:return
        excluded=set(pulls)|set(blocked)|b.micro.pulling|b.shopping|set(b.shield_moves)|b.battle_shop.reserved
        candidates=[(g.dist(u,e),u,e) for u in army if u.type=='ucry' and u.hp>u.hp_max*.6
                    and u.handle not in excluded and now>=b.cast_until.get(u.handle,0)
                    and not buffs(g,u)&DISABLED_CASTERS and abilities(g,u).get('Aweb',{}).get('level',0)>0
                    and g.cooldown(u,'Aweb')==0 for e in birds if g.dist(u,e)<=600]
        if not candidates:return
        distance,u,e=min(candidates,key=lambda c:(c[0]>400,c[2].hp,c[0],c[1].handle))
        if distance<=400:
            receipt=g.cast(u,'web',target=e);self.web_after=now+1
            if receipt:
                b.cast_until[u.handle]=now+.8;self.web_pending=(e.handle,now+2)
            self.log('battle_web_attempt',clock=now,handle=u.handle,target=e.handle,accepted=bool(receipt))
        else:
            step=min(180,distance-380);point=(u.x+(e.x-u.x)*step/distance,u.y+(e.y-u.y)*step/distance)
            # Only one healthy netter closes, and only on a safe walkable route.
            route=b.army_recovery.safe_path(b,(u.x,u.y),point,foes,combat=True)
            if route is not None and route<=step+64:
                pulls[u.handle]=point
                self.log('battle_web_approach',clock=now,handle=u.handle,target=e.handle,point=point)


def improve_scroll_position(b,hero,army,foes,now,radius,heal):
    """One short carrier step, never gather the fighting army or delay a rescue."""
    from .consumables import ORGANIC
    g=b.g;c=b.consumables
    if (b.teleport or b.action==Action.RETREAT or b.army_recovery.active or hero.hp<=hero.hp_max*.5
            or hero.handle in b.micro.pulling|b.shopping|set(b.shield_moves)|b.battle_shop.reserved):return False
    if now<c.coverage_after.get(hero.handle,0):return False
    if not all(hasattr(g,k) for k in ('map','path_distance','move')):return False
    units=[u for u in army if u.type in ORGANIC and u.hp>0 and g.dist(hero,u)<950]
    if not units:return False
    value=lambda p:sum(min(heal,u.hp_max-u.hp) for u in units if g.dist(p,u)<=radius-25)
    coverage=lambda p:sum(g.dist(p,u)<=radius-25 for u in units)
    center=(sum(u.x for u in units)/len(units),sum(u.y for u in units)/len(units))
    choices=[center]+[(u.x,u.y) for u in units if u.hp<u.hp_max*.75]
    options=[]
    for point in choices:
        distance=g.dist(hero,point)
        if distance<35:continue
        step=min(150,distance);p=(hero.x+(point[0]-hero.x)*step/distance,hero.y+(point[1]-hero.y)*step/distance)
        if value(p)<value(hero)+heal*.85 or coverage(p)<=coverage(hero):continue
        # Scroll coverage must not lead the carrier into TC's spell radius.
        if any(g.dist((hero.x+(p[0]-hero.x)*j/5,hero.y+(p[1]-hero.y)*j/5),e)<min(450,g.dist(hero,e))-8
               for e in foes if e.type=='Otch' for j in range(1,6)):continue
        route=b.army_recovery.safe_path(b,(hero.x,hero.y),p,foes,combat=True)
        if route is None or route>step+64:continue
        options.append((-coverage(p),-value(p),step,p))
    if not options:return False
    point=min(options)[3];c.coverage_after[hero.handle]=now+3
    receipt=g.move(hero,*point)
    if receipt:b.cast_until[hero.handle]=max(b.cast_until.get(hero.handle,0),now+.55)
    b.log('battle_scroll_coverage_step',clock=now,handle=hero.handle,point=point,covered_before=coverage(hero),covered_goal=coverage(point),accepted=bool(receipt),max_delay=.55)
    return bool(receipt)
