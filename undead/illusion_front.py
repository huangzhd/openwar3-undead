"""Observed DK illusions screen the first attack without becoming real heroes."""
from math import hypot


class RealArmyView:
    """Keep confirmed copies out of economy, hero rescue, mana and formation counts."""
    def __init__(self,game,excluded):
        self.raw=game;self.excluded=excluded

    def __getattr__(self,name):return getattr(self.raw,name)
    def keep(self,units):return [u for u in units if u.handle not in self.excluded]
    def my_heroes(self):return self.keep(self.raw.my_heroes())
    def my_units(self):return self.keep(self.raw.my_units())
    def my_army(self):return self.keep(self.raw.my_army())
    def units(self,*args,**kwargs):return self.keep(self.raw.units(*args,**kwargs))


class IllusionFront:
    def __init__(self,log):
        self.log=log;self.handles=set();self.pending=None;self.created=0;self.attempts=0;self.next_at=0;self.moved={}
        self.health={};self.observed_at=-100

    def observe(self,g,now):
        if self.handles and now-self.observed_at>=1:
            self.observed_at=now
            enemies=g.enemies()
            for u in g.units('me',{'Udea'}):
                if u.handle not in self.handles:continue
                old=self.health.get(u.handle,u.hp);self.health[u.handle]=u.hp
                attackers=[e.handle for e in enemies if (t:=g.current_target(e)) is not None and t.handle==u.handle]
                if attackers or u.hp<old:
                    self.log('dk_illusion_pressure_observed',clock=now,handle=u.handle,
                             hp=u.hp,hp_delta=u.hp-old,visible_targeters=attackers)
        p=self.pending
        if not p:return
        real=g.unit(p['target'])
        copies=[u for u in g.units('me',{'Udea'}) if u.handle not in p['before']
                and u.handle!=p['target'] and g.dist(u,p['point'])<=600]
        # The real DK remains alive while a targeted wand order creates a new
        # own DK handle nearby. Never identify the real one by list order.
        if real and real.hp>0 and copies:
            for u in copies:
                self.handles.add(u.handle);self.created+=1
                self.health[u.handle]=u.hp
                self.log('dk_illusion_observed',clock=now,handle=u.handle,real_dk=real.handle,
                         buff_confirmed='BIil' in g.buffs(u),basis='new_own_dk_after_targeted_wand_cast',total=self.created)
            self.pending=None
        elif now-p['started']>=4:
            self.log('dk_illusion_unconfirmed',clock=now,target=p['target'])
            self.pending=None

    def tick(self,b,army,foes,now):
        g=b.g.raw if isinstance(b.g,RealArmyView) else b.g
        if b.action.name not in {'ATTACK','HARASS'}:return
        dk=next((u for u in army if u.type=='Udea' and u.handle not in self.handles),None)
        if not dk:return
        targets=[e for e in foes if 0<=getattr(e,'owner',12)<12 and e.owner!=g.me() and e.hp>0]
        target=min(targets,key=lambda e:g.dist(e,dk),default=None)
        if target is None or g.dist(dk,target)>1600:return # Preserve the public 60-second duration for contact.
        if self.created<3 and self.attempts<3 and not self.pending and now>=self.next_at:
            holder=next((h for h in b.g.my_heroes() if 'will' in (g.inventory(h) or [])
                         and h.handle not in b.micro.pulling and now>=b.cast_until.get(h.handle,0)
                         and g.dist(h,dk)<=500),None)
            if holder and g.cooldown(holder,'AIil')==0:
                before={u.handle for u in g.units('me',{'Udea'})}
                receipt=g.use_item(holder,g.inventory(holder).index('will'),target=dk)
                self.attempts+=1;self.next_at=now+2
                b.cast_until[holder.handle]=now+1.2
                if receipt:self.pending=dict(before=before,target=dk.handle,point=(dk.x,dk.y),started=now)
                self.log('dk_illusion_attempt',clock=now,holder=holder.handle,target=dk.handle,
                         accepted=bool(receipt),attempt=self.attempts)
        if not self.handles:return
        copies=[u for u in g.units('me',{'Udea'}) if u.handle in self.handles]
        firing_line=[u for u in army if u.type=='ucry' and g.dist(u,dk)<1600]
        anchor=min(firing_line,key=lambda u:sum(g.dist(u,v) for v in firing_line)) if firing_line else dk
        dx,dy=target.x-anchor.x,target.y-anchor.y;length=hypot(dx,dy) or 1;dx/=length;dy/=length
        for i,u in enumerate(sorted(copies,key=lambda u:u.handle)):
            if now-self.moved.get(u.handle,-100)<2:continue
            side=(i-1)*150;front=min(350,max(120,length-120))
            point=(anchor.x+dx*front-dy*side,anchor.y+dy*front+dx*side)
            if g.path_distance((u.x,u.y),point) is None:continue
            receipt=g.attack_move(u,*point)
            if receipt:self.moved[u.handle]=now
            self.log('dk_illusion_screen_order',clock=now,handle=u.handle,point=point,accepted=bool(receipt))
