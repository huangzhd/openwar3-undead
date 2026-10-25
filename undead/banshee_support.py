"""Precontact shields and engine-owned curse; no combat formation churn."""
from .nc_combo import spell_data, DISABLED_CASTERS
from .targeting import abilities, buffs, in_weapon_range, unit_stats


class BansheeSupport:
    def __init__(self, log):
        self.log=log;self.pending={};self.failures={};self.retry={}
        self.modes={};self.mode_tries={};self.held=set()

    def tick(self,b,army,foes,now,prebattle,blocked=()):
        g=b.g;handled=set()
        live={u.handle for u in army if u.hp>0}
        self.modes={h:m for h,m in self.modes.items() if h in live}
        self.held.intersection_update(live)
        for handle,p in list(self.pending.items()):
            target=next((u for u in army if u.handle==handle),None)
            if target and buffs(g,target)&{'Bams','Bam2'}:
                self.log('banshee_shell_observed',clock=now,target=handle,caster=p['caster'])
                self.failures.pop(handle,None);self.pending.pop(handle,None)
            elif now-p['at']>=3 or target is None:
                self.log('banshee_shell_unconfirmed',clock=now,target=handle,caster=p['caster'])
                self.pending.pop(handle,None)
        if b.teleport or b.action.name=='RETREAT':return handled
        excluded=set(blocked)|set(b.shopping)|set(b.battle_shop.reserved)|set(b.shield_moves)|set(b.micro.pulling)
        for u in army:
            if u.type!='uban' or u.hp<=0 or u.handle in excluded:continue
            if now<b.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS:continue
            known=abilities(g,u)
            mode='curseoff' if prebattle else 'curseon'
            key=(u.handle,mode)
            if ('Acrs' in known and self.modes.get(u.handle)!=mode and
                    self.mode_tries.get(key,0)<3 and now>=self.retry.get(key,0)):
                receipt=g.cast(u,mode)
                self.mode_tries[key]=self.mode_tries.get(key,0)+1;self.retry[key]=now+2
                if receipt:
                    self.modes[u.handle]=mode;self.mode_tries[key]=0
                self.log('banshee_curse_autocast_attempt',clock=now,handle=u.handle,order=mode,accepted=bool(receipt))
            if prebattle:
                self.held.discard(u.handle)
                code=next((c for c in ('Aam2','Aams') if known.get(c,{}).get('level',0)>0),None)
                if code is None:continue
                row=spell_data()[0][code];reach=float(row['Rng1']);cost=float(row['Cost1'])
                if u.mana<cost or g.cooldown(u,code)!=0:continue
                targets=[v for v in army if v.hp>0 and v.alive and v.owner==g.me() and
                         (v.is_hero or v.type=='ucry') and getattr(v,'has_detail',False) and
                         not buffs(g,v)&{'Bams','Bam2'} and v.handle not in self.pending and
                         self.failures.get(v.handle,0)<3 and now>=self.retry.get(v.handle,0)]
                targets.sort(key=lambda v:(not v.is_hero,g.dist(u,v)))
                target=next((v for v in targets if g.dist(u,v)<=reach),None)
                if target:
                    h=target.handle;self.failures[h]=self.failures.get(h,0)+1;self.retry[h]=now+3
                    receipt=g.cast(u,'antimagicshell',target=target)
                    self.log('banshee_shell_attempt',clock=now,handle=u.handle,target=h,
                             accepted=bool(receipt),attempt=self.failures[h],ability=code)
                    if receipt:
                        self.pending[h]=dict(caster=u.handle,at=now)
                        b.cast_until[u.handle]=now+1;handled.add(u.handle)
                elif targets:
                    # Only before contact, close a short safe gap to an ally.
                    target=targets[0];distance=g.dist(u,target)
                    if distance>800:continue
                    step=max(0,distance-reach+40)/max(1,distance)
                    point=(u.x+(target.x-u.x)*step,u.y+(target.y-u.y)*step)
                    if self.safe_move(b,u,point,foes,now):handled.add(u.handle)
            else:
                # Let the engine finish curse and attacks. Follow only after the
                # main force has actually moved away, not for ideal spacing.
                current=g.current_target(u)
                if current and (in_weapon_range(g,u,current) or
                                'Acrs' in known and g.dist(u,current)<=float(spell_data()[0]['Acrs']['Rng1'])):continue
                main=[v for v in army if v.type in {'Ulic','Nbrn','Nngs','ucry'} and v.hp>0 and v.handle not in excluded]
                if main:
                    anchor=min(main,key=lambda v:sum(g.dist(v,w) for w in main))
                    if g.dist(u,anchor)>600:
                        enemy=min(foes,key=lambda e:g.dist(anchor,e),default=None)
                        if enemy:
                            d=max(1,g.dist(anchor,enemy))
                            point=(anchor.x-140*(enemy.x-anchor.x)/d,anchor.y-140*(enemy.y-anchor.y)/d)
                        else:point=(anchor.x,anchor.y)
                        if self.safe_move(b,u,point,foes,now):
                            self.held.discard(u.handle);handled.add(u.handle)
                            continue
                if u.handle not in self.held and g.hold(u):self.held.add(u.handle)
        return handled

    def safe_move(self,b,u,point,foes,now):
        g=b.g;key=('move',u.handle)
        if now<self.retry.get(key,0):return False
        grid=g.map();path=g.walk_path((u.x,u.y),point)
        route=g.path_distance((u.x,u.y),point)
        if not grid or not path or g.dist(path[-1],point)>96 or route is None or route>g.dist(u,point)+128:return False
        threats=[(e,max((w.range for w in s.weapons if 'ground' in w.targets),default=0))
                 for e in foes if (s:=unit_stats(e.type))]
        threats=[(e,max(r,float(spell_data()[0]['AOws']['Area3'])) if e.type=='Otch' else r) for e,r in threats]
        previous=(u.x,u.y)
        for end in path:
            n=max(1,int(g.dist(previous,end)/64)+1)
            for i in range(1,n+1):
                p=(previous[0]+(end[0]-previous[0])*i/n,previous[1]+(end[1]-previous[1])*i/n)
                if not grid.walkable(*p) or any(r and g.dist(p,e)<r+100 for e,r in threats):return False
            previous=end
        self.retry[key]=now+2
        receipt=g.move(u,*point)
        if receipt:b.cast_until[u.handle]=now+.5
        self.log('banshee_support_move',clock=now,handle=u.handle,point=point,accepted=bool(receipt))
        return bool(receipt)
