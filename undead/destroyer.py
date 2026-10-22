"""Visible dispel priorities: ally hex, enemy summons, other hero debuffs, enemy buffs."""
from functools import lru_cache
from math import hypot,cos,sin,pi
from types import SimpleNamespace
from .nc_combo import spell_data,DISABLED_CASTERS
from .targeting import enemy_player,buffs,unit_stats

# 1.27a public AbilityData/buffs.json identifiers; no blanket B* classification.
# Auras, stun, poison, Purge slow, invulnerability and transformation buffs are
# deliberately absent: having a buff object does not make it dispellable.
HERO_DEBUFFS=frozenset({'BOhx','Bply','BEer','BUsl','Bcyc','Bcy2','BHbn',
    'Bslo','Bcri','Bcrs','Bfae','BNsi','BNso','BNht','BNdh'})
ENEMY_BUFFS=frozenset({'Bblo','Binf','Brej','Broa','BNbr','BUfa','BUhf','Buhf',
    'Bspl','Binv','Blsh','Bspe','Bdef','BIrg','BIrl','BIrm','Brpb'})


@lru_cache(maxsize=1)
def summon_types():
    rows,_=spell_data()
    # Public summon spell outputs, not zero-cost heuristics or hidden unit flags.
    codes=set()
    for code in ('AHwe','AEfn','AOsf','ANsg','ANsq','ANsw','ANba','AUin','ANdo','ACwe','AIrd','Arai',
                 'ANlm','AHpx','AEsv','AOsw','ANsy'):
        codes.update(v for k,v in rows[code].items() if k.startswith('UnitID') and len(v)==4)
    codes.update(rows['AUcb']['DataC'+str(level)] for level in (1,2,3))
    codes.add('uskm') # Skeletal Mastery replaces one raised warrior with a mage.
    return frozenset(codes)


def dispel_plan(caster,targets,protected,reach,area,protection_radii=None):
    """Choose a reachable ground point; never move the caster into the pack.

    Unit centres, pair midpoints and their cast-range projections cover spread
    buff groups without requiring a unit itself to be within cast range. Keep
    a small coverage margin for movement between the snapshot and spell impact.
    """
    radius=max(0,area-8)
    distance=lambda p,u:hypot(p[0]-u.x,p[1]-u.y)
    local=[t for t in targets if distance((caster.x,caster.y),t['unit'])<=reach+radius]
    points=[((t['unit'].x,t['unit'].y),0) for t in local]
    points += [(((a['unit'].x+b['unit'].x)/2,(a['unit'].y+b['unit'].y)/2),1)
               for i,a in enumerate(local) for b in local[i+1:]
               if hypot(a['unit'].x-b['unit'].x,a['unit'].y-b['unit'].y)<=2*radius]
    # A target may be near a protected hero while a blast on its far edge is
    # safe. Test offsets instead of rejecting the target centre up front.
    if protected:
        points += [((t['unit'].x+radius*cos(i*pi/8),t['unit'].y+radius*sin(i*pi/8)),2)
                   for t in local for i in range(16)]
    best=None
    for point,shifted in points:
        length=distance(point,caster)
        if length>reach:
            scale=max(0,reach-8)/length
            point=(caster.x+(point[0]-caster.x)*scale,caster.y+(point[1]-caster.y)*scale)
            shifted=1
        if any(distance(point,h)<=(protection_radii or {}).get(h.handle,area+8) for h in protected):continue
        hit=[t for t in local if distance(point,t['unit'])<=radius]
        if not hit:continue
        selected=min(hit,key=lambda t:(t['priority'],t['unit'].hp,t['unit'].handle))
        counts=tuple(-sum(t['priority']==rank for t in hit) for rank in range(4))
        score=(selected['priority'],*counts,shifted,selected['unit'].hp,selected['unit'].handle)
        if best is None or score<best[0]:best=(score,point,selected,hit)
    return best[1:] if best else None


class Destroyer:
    def __init__(self,log):
        self.log=log;self.morph=None;self.morph_attempts={};self.next_morph=0
        self.dispel={};self.attempts={};self.next_cast={};self.deferred={}
        self.reposition_attempts={};self.reposition_at={}

    def reposition(self,b,u,army,enemies,targets,protected,reach,area,radii,now):
        """A bounded safe shift behind the fighting line can expose a dispel point."""
        if (not getattr(getattr(b,'hero_pressure',None),'orc_melee_active',False) or
                getattr(b,'blight_waiting',False) or u.hp<=u.hp_max*.45 or
                u.handle in b.micro.pulling or now<self.reposition_at.get(u.handle,0)):
            return False
        g=b.g
        if not hasattr(g,'move'):return False
        main=[v for v in army if v.type in {'ucry','Ulic','Nbrn','Nngs'} and v.hp>0]
        if not main or not targets:return False
        signature=tuple(sorted(t['unit'].handle for t in targets))
        key=(u.handle,signature)
        if self.reposition_attempts.get(key,0)>=3:return False
        anchor=min(main,key=lambda v:sum(g.dist(v,w) for w in main))
        enemy=min(targets,key=lambda t:g.dist(anchor,t['unit']))['unit']
        dx,dy=enemy.x-anchor.x,enemy.y-anchor.y;length=max(1,hypot(dx,dy));dx,dy=dx/length,dy/length
        front=max((v.x-anchor.x)*dx+(v.y-anchor.y)*dy for v in main)
        threats=[(e,max((w.range for w in stats.weapons if 'air' in w.targets),default=0))
                 for e in enemies if (stats:=unit_stats(e.type))]
        clearance=lambda p:min((hypot(p[0]-e.x,p[1]-e.y)-r for e,r in threats if r),default=9999)
        before=clearance((u.x,u.y));choices=[]
        for step in (160,280):
            for i in range(16):
                point=(u.x+step*cos(i*pi/8),u.y+step*sin(i*pi/8))
                if (point[0]-anchor.x)*dx+(point[1]-anchor.y)*dy>front:continue
                if g.dist(point,anchor)>700:continue
                if any(clearance((u.x+(point[0]-u.x)*j/8,u.y+(point[1]-u.y)*j/8))<min(100,before)-8
                       for j in range(1,9)):continue
                plan=dispel_plan(SimpleNamespace(x=point[0],y=point[1]),targets,protected,reach,area,radii)
                if plan:choices.append((plan[1]['priority'],-len(plan[2]),step,point))
        if not choices:return False
        point=min(choices)[-1]
        self.reposition_attempts[key]=self.reposition_attempts.get(key,0)+1;self.reposition_at[u.handle]=now+2
        receipt=g.move(u,*point)
        if receipt:b.cast_until[u.handle]=now+.4
        b.log('destroyer_dispel_reposition',clock=now,handle=u.handle,point=point,
              accepted=bool(receipt),attempt=self.reposition_attempts[key])
        return bool(receipt)

    def targets(self,b,army,enemies):
        g=b.g;targets=[]
        heroes=g.my_heroes() if hasattr(g,'my_heroes') else [u for u in army if u.is_hero]
        allies={u.handle:u for u in [*army,*heroes]}
        for u in allies.values():
            effects=buffs(g,u)&HERO_DEBUFFS
            hexed='BOhx' in effects
            if effects and (hexed or u.is_hero) and u.hp>0 and u.alive and u.owner==g.me():
                targets.append(dict(unit=u,priority=0 if hexed else 2,
                                    reason='ally_hex' if hexed else 'hero_debuff',effects=sorted(effects)))
        for u in enemies:
            effects=buffs(g,u)&ENEMY_BUFFS
            summon=u.type in summon_types() and u.type!='ninf'
            if not (effects or summon):continue
            if not (u.alive and u.hp>0 and enemy_player(g,u) and u.visible_to(g.me())):continue
            # Infernals are summoned but spell immune, so not dispel fodder.
            if summon:
                targets.append(dict(unit=u,priority=1,reason='enemy_summon',effects=sorted(effects)))
            elif effects:
                targets.append(dict(unit=u,priority=3,reason='enemy_buff',effects=sorted(effects)))
        return targets

    def observe(self,b,now):
        g=b.g
        if self.morph:
            p=self.morph;unit=g.unit(p['handle'])
            if unit and unit.type=='ubsp':
                self.log('destroyer_morph_confirmed',clock=now,handle=unit.handle,mana=unit.mana)
                self.morph=None
            elif now-p['started']>=8 or unit is None:
                self.log('destroyer_morph_unconfirmed',clock=now,handle=p['handle'])
                self.morph=None
            else:b.cast_until[p['handle']]=max(b.cast_until.get(p['handle'],0),now+1)
        for handle,p in list(self.dispel.items()):
            unit=g.unit(handle)
            cd=g.cooldown(unit,'Advm') if unit else None
            if cd is not None and cd>0 or now-p['started']>=3 or unit is None:
                changes=[]
                for h,hp in p['targets']:
                    target=g.unit(h)
                    if target and target.visible_to(g.me()):
                        changes.append(dict(handle=h,hp_before=hp,hp_after=target.hp,alive=target.alive))
                effects=[]
                for h,before in p.get('effects',[]):
                    target=g.unit(h)
                    if target and getattr(target,'has_detail',False) and target.visible_to(g.me()):
                        after=buffs(g,target)
                        effects.append(dict(handle=h,before=before,remaining=sorted(set(before)&after),
                                            absent=sorted(set(before)-after)))
                confirmed=cd is not None and cd>0
                self.log('destroyer_dispel_cast_observed' if confirmed else 'destroyer_dispel_unconfirmed',
                         clock=now,handle=handle,cooldown=cd,targets=changes,effects=effects,
                         reason=p.get('reason','enemy_summon'),
                         basis='cooldown confirms cast; buff absence may include expiry/other dispels; hidden targets unknown')
                if confirmed:self.attempts.pop(p['key'],None)
                self.dispel.pop(handle,None)

    def defer(self,unit,now,reason,**details):
        previous=self.deferred.get(unit.handle)
        if previous and previous[0]==reason and now-previous[1]<5:return
        self.deferred[unit.handle]=(reason,now)
        self.log('destroyer_dispel_deferred',clock=now,handle=unit.handle,reason=reason,**details)

    def tick(self,b,army,enemies,now,blocked=()):
        g=b.g;self.observe(b,now)
        if b.teleport:return
        targets=self.targets(b,army,enemies)
        if not targets:return
        row=spell_data()[0]['Advm'];reach=float(row['Rng1']);area=float(row['Area1'])
        heroes=g.my_heroes() if hasattr(g,'my_heroes') else [u for u in army if u.is_hero]
        # Devour Magic affects an area, including units other than the chosen
        # target. Preserve friendly hero buffs and hostile hero debuffs (most
        # notably Dark Ranger silence) wherever the blast would reach them.
        protected=[u for u in heroes if getattr(u,'alive',True) and u.hp>0 and u.owner==g.me()
                   and buffs(g,u)&ENEMY_BUFFS and 'BOhx' not in buffs(g,u)]
        pending=getattr(b,'silence_protected_until',{})
        b.silence_protected_until={h:t for h,t in pending.items() if t>now}
        protected.extend(u for u in enemies if getattr(u,'alive',True) and u.hp>0 and u.is_hero
                         and enemy_player(g,u) and u.visible_to(g.me())
                         and (buffs(g,u)&HERO_DEBUFFS or pending.get(u.handle,0)>now))
        # A moving TC can enter the blast between snapshot and cast impact.
        # Keep a movement/collision margin, even when the spell is aimed at DK.
        radii={u.handle:area+32+.75*(522 if 'Bspe' in buffs(g,u) else
                    (stats.speed if (stats:=unit_stats(u.type)) else 320)) for u in protected}
        # Retreat never morphs a statue; an existing destroyer may dispel first.
        retreat=b.action.name=='RETREAT'
        if not targets:return
        available=[u for u in army if u.handle not in blocked and now>=b.cast_until.get(u.handle,0)
                   and not buffs(g,u)&(DISABLED_CASTERS|{'BOhx'})]
        destroyers=g.units('me',{'ubsp'})
        for u in army:
            if u.type=='ubsp' and u not in available:
                self.defer(u,now,'caster_blocked' if u.handle in blocked else 'caster_busy_or_controlled')
        if not retreat and not destroyers and not self.morph and now>=self.next_morph:
            level=g.tech_many(['Rusp']).get('Rusp');res=g.resources()
            hero_food=5 if b.economy.third_hero not in b.economy.ever_heroes else 0
            cap=res['food_cap'] if b.economy.upkeep_released or res['food_used']>50 else min(50,res['food_cap'])
            if (level is not None and level>=1 and res['gold']>=100 and res['lumber']>=50
                    and res['food_used']+2+hero_food<=cap):
                statues=[u for u in available if u.type=='uobs' and g.cooldown(u,'Aave')==0
                         and self.morph_attempts.get(u.handle,0)<3
                         and any(g.dist(u,t['unit'])<=900 for t in targets)]
                if statues:
                    priority=lambda u:min(t['priority'] for t in targets if g.dist(u,t['unit'])<=900)
                    u=min(statues,key=lambda u:(priority(u),u.mana,u.handle));n=self.morph_attempts.get(u.handle,0)+1
                    self.morph_attempts[u.handle]=n;self.next_morph=now+4
                    receipt=g.cast(u,'avengerform')
                    self.log('destroyer_morph_attempt',clock=now,handle=u.handle,mana=u.mana,
                             accepted=bool(receipt),attempt=n,trigger_priority=priority(u))
                    if receipt:
                        self.morph=dict(handle=u.handle,started=now);b.cast_until[u.handle]=now+2.5
        # A damaged Destroyer gains life from a useful dispel; give it the
        # first cast, but never issue a duplicate cast into the same area.
        available.sort(key=lambda u:(u.type!='ubsp',u.hp/max(1,u.hp_max)))
        for u in available:
            if u.type!='ubsp' or u.handle in self.dispel or now<self.next_cast.get(u.handle,0):continue
            if g.cooldown(u,'Advm')!=0:
                self.defer(u,now,'cooldown_not_ready',cooldown=g.cooldown(u,'Advm'))
                continue
            covered={handle for pending in self.dispel.values() for handle,_ in pending['targets']}
            reachable=[t for t in targets if t['unit'].handle not in covered
                       and self.attempts.get((u.handle,t['unit'].handle),0)<3]
            plan=dispel_plan(u,reachable,protected,reach,area,radii)
            if plan is None:
                if not retreat and self.reposition(b,u,army,enemies,reachable,protected,reach,area,radii,now):continue
                self.defer(u,now,'no_safe_reachable_point' if reachable else 'pending_or_attempt_limit',
                           targets=[t['unit'].handle for t in reachable],protected=[h.handle for h in protected])
                continue
            self.deferred.pop(u.handle,None)
            point,selected,hit=plan;target=selected['unit']
            key=(u.handle,target.handle)
            self.attempts[key]=self.attempts.get(key,0)+1;self.next_cast[u.handle]=now+2
            receipt=g.cast(u,'devourmagic',x=point[0],y=point[1])
            if receipt:
                self.reposition_attempts={k:v for k,v in self.reposition_attempts.items() if k[0]!=u.handle}
            self.log('destroyer_dispel_attempt',clock=now,handle=u.handle,target=target.handle,
                     point=point,accepted=bool(receipt),attempt=self.attempts[key],
                     reason=selected['reason'],priority=selected['priority'],effects=selected['effects'],
                     covered_count=len(hit),covered_handles=[t['unit'].handle for t in hit],
                     protected_heroes=[dict(handle=h.handle,distance=round(g.dist(point,h)),
                                            radius=radii[h.handle]) for h in protected])
            if receipt:
                b.cast_until[u.handle]=now+1.2
                self.dispel[u.handle]=dict(started=now,key=key,
                    reason=selected['reason'],
                    targets=[(t['unit'].handle,t['unit'].hp) for t in hit],
                    effects=[(t['unit'].handle,t['effects']) for t in hit if t['effects']])
