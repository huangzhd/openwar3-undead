"""Manual alternating statue supply; only travel to catch the army or escape danger."""
from math import hypot,cos,sin,atan2,pi
from .retreat import escape_point,clearance
from .targeting import enemy_player,buffs
from .nc_combo import DISABLED_CASTERS


class StatueSupport:
    def __init__(self,log):
        self.log=log;self.moves={};self.held=set();self.last_plan={}
        self.supply_at={};self.supply_checks={};self.last_supply_mode={};self.mana_at={}
        self.rescuing=set();self.rescue_handled=set()

    def supply(self,b,u,recipient,needy,mode,now):
        g=b.g;ability='Arpl' if mode=='life' else 'Arpm'
        if (not recipient or getattr(u,'mana',0)<2 or g.cooldown(u,ability)!=0 or
                now-self.supply_at.get(u.handle,-100)<2 or u.handle in self.supply_checks):return False
        self.supply_at[u.handle]=now
        receipt=g.cast(u,'replenishlife' if mode=='life' else 'replenishmana')
        self.log('statue_supply_attempt',clock=now,handle=u.handle,mode=mode,
                 recipient=recipient.handle,distance=round(g.dist(u,recipient)),accepted=bool(receipt))
        if not receipt:return False
        self.last_supply_mode[u.handle]=mode
        self.mana_at.setdefault(u.handle,now)
        if mode=='mana':self.mana_at[u.handle]=now
        b.cast_until[u.handle]=now+1.2
        self.held.add(u.handle)
        self.supply_checks[u.handle]=dict(started=now,mode=mode,buff='Brpl' if mode=='life' else 'Brpm',
            before={v.handle:(v.hp,getattr(v,'mana',0)) for v in needy if g.dist(u,v)<=700})
        return True

    def rescue(self,b,u,heroes,army,hostiles,now,threatened,assigned):
        """Meet retreating heroes outside the main army, without crossing fire."""
        g=b.g
        if getattr(u,'mana',0)<2 or g.cooldown(u,'Arpl') is None:return False
        targets=sorted((h for h in heroes if g.dist(u,h)<=1800),key=lambda h:(h.hp/h.hp_max,g.dist(u,h)))
        if not targets:return False
        pending=self.moves.get(u.handle)
        if (pending and not pending.get('observed') and g.dist(u,pending['origin'])>64 and
                g.dist(u,pending['point'])<g.dist(pending['origin'],pending['point'])-64):
            pending['observed']=True
            self.log('statue_support_movement_observed',clock=now,handle=u.handle,
                     reason=pending['reason'],point=(u.x,u.y),hero=pending.get('hero'))
        for hero in targets:
            if g.dist(u,hero)<=220 and not threatened:
                needy=[v for v in army if v.type in {'ucry','Udea','Ulic','Nbrn','Nngs'} and v.hp<v.hp_max-15]
                if not self.supply(b,u,hero,needy,'life',now) and u.handle not in self.held:
                    if g.hold(u):self.held.add(u.handle);b.last.pop(('go',u.handle),None)
                self.moves.pop(u.handle,None)
                return True
        if now-self.last_plan.get(u.handle,-100)<1:
            return bool(pending and pending.get('hero') in {h.handle for h in targets} and not threatened)
        self.last_plan[u.handle]=now
        for hero in targets:
            points=[(hero.x+r*cos(i*pi/8),hero.y+r*sin(i*pi/8)) for r in (160,200) for i in range(16)]
            points=[p for p in points if g.dist(u,p)>=80 and clearance(p,hostiles,b.army_recovery.threat_range)>=120]
            points.sort(key=lambda p:(sum(g.dist(p,a)<120 for a in assigned),g.dist(u,p)))
            for point in points:
                length=b.army_recovery.safe_path(b,(u.x,u.y),point,hostiles,
                    combat=b.action.name in {'ATTACK','HARASS','RETREAT'} or any(enemy_player(g,e) for e in hostiles))
                if length is None or length>max(400,g.dist(u,point)*1.5):continue
                self.held.discard(u.handle)
                if not g.move(u,*point):return False
                self.moves[u.handle]=dict(origin=(u.x,u.y),point=point,reason='retreating_hero',hero=hero.handle)
                assigned.append(point)
                self.log('statue_hero_rescue_move',clock=now,handle=u.handle,hero=hero.handle,type=hero.type,
                         hp=hero.hp,point=point,distance=round(g.dist(u,hero)),accepted=True)
                return True
        # No safe route: leave ordinary escape/supply in charge this tick.
        self.last_plan.pop(u.handle,None)
        return False

    def observe_supply(self,g,now):
        for handle,p in list(self.supply_checks.items()):
            reached=[]
            for h,(hp,mana) in p['before'].items():
                u=g.unit(h)
                if u and p['buff'] in g.buffs(u):
                    reached.append(dict(handle=h,type=u.type,hp_delta=round(u.hp-hp,2),
                                        mana_delta=round(getattr(u,'mana',0)-mana,2)))
            if reached or now-p['started']>=3:
                self.log('statue_supply_recipients_observed' if reached else 'statue_supply_unconfirmed',
                         clock=now,handle=handle,mode=p['mode'],recipients=reached,
                         basis='recipient_buff; net resource change may include other effects')
                self.supply_checks.pop(handle,None)

    def tick(self,b,army,hostiles,now,protected=()):
        g=b.g
        self.observe_supply(g,now)
        self.rescue_handled=set()
        # Wounded units remain supply recipients. Excluding every pulling unit
        # can strand replacements at home or anchor them on an unsafe front.
        # The medoid and local majority keep one distant straggler from leading.
        core=[u for u in army if u.type in {'ucry','Udea','Ulic','Nbrn','Nngs'}
              and u.handle not in b.shopping]
        if not core:return
        retreating=set(protected)|set(b.micro.pulling)|set(getattr(b,'backline_guards',()))|set(getattr(b,'portal_pulls',()))
        heroes=[h for h in core if h.type!='ucry' and h.hp>0 and h.handle not in b.battle_shop.reserved]
        self.rescuing.intersection_update(h.handle for h in heroes if h.hp<.65*h.hp_max)
        self.rescuing.update(h.handle for h in heroes if h.hp<=.5*h.hp_max and
                            (h.handle in retreating or b.action.name=='RETREAT'))
        rescue_heroes=[h for h in heroes if h.handle in self.rescuing] if not b.teleport else []
        assigned=[]
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core))
        local=[u for u in core if g.dist(u,anchor)<800]
        combat=b.action.name in {'ATTACK','HARASS'} or any(enemy_player(g,e) for e in hostiles)
        battle=any(enemy_player(g,e) for e in hostiles)
        if battle:local=[v for v in local if g.dist(v,anchor)<=500]
        statues=sorted((u for u in army if u.type=='uobs'),key=lambda u:u.handle)
        live={u.handle for u in statues};self.held &= live
        for i,u in enumerate(statues):
            if (u.handle in protected or u.handle in b.shopping or u.handle in b.battle_shop.reserved or
                    now<b.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS):
                self.held.discard(u.handle);continue
            threats=[e for e in hostiles if b.army_recovery.threat_range(e.type)>0 and
                     g.dist(e,u)<b.army_recovery.threat_range(e.type)+100]
            threatened=bool(threats) or (now-b.micro.hit.get(u.handle,-100)<3 and
                clearance((u.x,u.y),hostiles,b.army_recovery.threat_range)<120)
            if self.rescue(b,u,rescue_heroes,core,hostiles,now,threatened,assigned):
                self.rescue_handled.add(u.handle)
                continue
            preferred=b.army_recovery.statue_modes.get(u.handle,{}).get('mode','life' if i%2==0 else 'mana')
            needs={'life':[v for v in local if v.hp<v.hp_max-15],
                   'mana':[v for v in local if v.type in {'Udea','Ulic','Nbrn','Nngs'} and getattr(v,'mana_max',0)-getattr(v,'mana',0)>=5]}
            # One nearby car must cover both resources, including after its partner morphs.
            # Start with life; alternate when both are needed, with short urgent-life priority.
            last=self.last_supply_mode.get(u.handle)
            mode=('mana' if last=='life' else 'life') if last else preferred
            nearby_cars=sum(g.dist(v,anchor)<900 for v in statues)
            # With two local cars, keep complementary jobs even after both
            # temporarily served the same resource. Only a lone car alternates.
            if nearby_cars>=2:mode=preferred
            if nearby_cars<=1 and (last is None or any(v.hp<.45*v.hp_max for v in needs['life'])
                                  and now-self.mana_at.get(u.handle,now)<6):mode='life'
            other='mana' if mode=='life' else 'life'
            if not needs[mode] or g.cooldown(u,'Arpl' if mode=='life' else 'Arpm')!=0:
                if needs[other] and g.cooldown(u,'Arpl' if other=='life' else 'Arpm')==0:mode=other
            # Do not chase a distant recipient while another needed supply is in range.
            if nearby_cars<=1 and not any(g.dist(u,v)<=220 for v in needs[mode]) and any(g.dist(u,v)<=220 for v in needs[other]):
                mode=other
            needy=needs[mode]
            recipient=min(needy,key=lambda v:(g.dist(u,v)>220,-sum(g.dist(v,w)<=500 for w in needy),v.hp/v.hp_max if mode=='life' else
                          v.mana/max(1,v.mana_max),g.dist(u,v)),default=None)
            support_anchor=recipient or anchor
            covered=(g.dist(u,support_anchor)<=220 if recipient else
                     g.dist(u,anchor)<=520 and sum(g.dist(u,v)<=600 for v in local)>=max(1,(len(local)+1)//2))
            if battle:covered=covered and g.dist(u,anchor)<=350
            pending=self.moves.get(u.handle)
            if pending and not pending.get('observed') and g.dist(u,pending['origin'])>64 and g.dist(u,pending['point'])<g.dist(pending['origin'],pending['point'])-64:
                self.log('statue_support_movement_observed',clock=now,handle=u.handle,reason=pending['reason'],point=(u.x,u.y))
                self.moves.pop(u.handle,None)
            if covered and not threatened:
                if self.supply(b,u,recipient,needy,mode,now):continue
                if u.handle not in self.held and g.hold(u):
                    self.held.add(u.handle);self.moves.pop(u.handle,None)
                    b.last.pop(('go',u.handle),None)
                    self.log('statue_support_stationed',clock=now,handle=u.handle,point=(u.x,u.y),covered=sum(g.dist(u,v)<=600 for v in local))
                continue
            self.held.discard(u.handle)
            if now-self.last_plan.get(u.handle,-100)<2:continue
            self.last_plan[u.handle]=now
            close=[]
            if battle:
                enemy=min(hostiles,key=lambda e:g.dist(anchor,e))
                dx,dy=anchor.x-enemy.x,anchor.y-enemy.y;length=hypot(dx,dy) or 1
                dx,dy=dx/length,dy/length;side=1 if i%2==0 else -1
                close=[(anchor.x+dx*back-dy*side*flank,anchor.y+dy*back+dx*side*flank)
                       for back in (100,160,220,280) for flank in (80,140)]
                # Search both rear flanks before falling back to a long escape.
                angle=atan2(dy,dx)
                close += [(anchor.x+radius*cos(angle+offset),anchor.y+radius*sin(angle+offset))
                          for radius in (160,220,280,340)
                          for offset in (0,pi/6,-pi/6,pi/3,-pi/3,pi/2,-pi/2)]
                close=[p for p in close if clearance(p,hostiles,b.army_recovery.threat_range)>=120]
                close.sort(key=lambda p:(-sum(g.dist(p,v)<=220 for v in needy),
                                         -sum(g.dist(p,v)<=500 for v in local),g.dist(p,anchor),g.dist(u,p)))
            if threatened:
                point=escape_point(g,u,hostiles,b.army_recovery.threat_range,home=(anchor.x,anchor.y))
                candidates=close+[point]
                reason='threat_pullback'
            else:
                # Two rear flank points, not the DK's central approach lane.
                enemy=min(hostiles,key=lambda e:g.dist(e,support_anchor),default=None)
                dx,dy=(support_anchor.x-enemy.x,support_anchor.y-enemy.y) if enemy else (b.home.x-support_anchor.x,b.home.y-support_anchor.y)
                length=hypot(dx,dy) or 1;dx,dy=dx/length,dy/length
                side=1 if i%2==0 else -1
                flank=80 if recipient else 160
                candidates=[(support_anchor.x+dx*rear-dy*side*flank,support_anchor.y+dy*rear+dx*side*flank)
                            for rear in ((160,100,0) if recipient else (220,380,540))]
                reason='recipient_out_of_cast_range' if recipient else 'army_out_of_supply_range'
                if recipient:
                    recipients=[v for v in core if g.dist(v,anchor)<=1600 and
                                (v.hp<v.hp_max-15 if mode=='life' else
                                 v.type in {'Udea','Ulic','Nbrn','Nngs'} and getattr(v,'mana_max',0)-getattr(v,'mana',0)>=5)]
                    candidates += [(anchor.x+dx*rear-dy*side*160,anchor.y+dy*rear+dx*side*160) for rear in (220,380,540)]
                    candidates += [(v.x+dx*160-dy*side*80,v.y+dy*160+dx*side*80) for v in recipients]
                    candidates.sort(key=lambda p:(-sum(g.dist(p,v)<=700 and (v.handle in b.micro.pulling or v.hp<.45*v.hp_max) for v in recipients) if mode=='life' else 0,
                                                  -sum(g.dist(p,v)<=700 for v in recipients),
                                                  -sum(g.dist(p,v)<=220 for v in recipients),g.dist(u,p)))
                if battle:
                    candidates=close+[p for p in candidates if g.dist(p,anchor)<=350]
            point=next((p for p in candidates if p is not None and g.dist(u,p)>=80 and
                        b.army_recovery.safe_path(b,(u.x,u.y),p,hostiles,combat=combat) is not None),None)
            if point is None:continue
            if g.move(u,*point):
                self.moves[u.handle]=dict(origin=(u.x,u.y),point=point,reason=reason)
                self.log('statue_support_move_attempt',clock=now,handle=u.handle,point=point,reason=reason,accepted=True)
