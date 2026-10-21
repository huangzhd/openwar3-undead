"""AL mercenary entry: Lich tags a visible guard, then pulls towards the approach."""
from math import hypot
from .policy import Action


class ALMercenaryPull:
    def __init__(self,log):
        self.log=log;self.active=None;self.attempted=set()

    def finish(self,now,reason):
        self.log('al_merc_pull_end',clock=now,camp=self.active['camp'],reason=reason)
        self.active=None

    def tick(self,b,army,now,blocked=()):
        g=b.g;c=b.creeping;camp=c.active
        lich=next((u for u in army if u.type=='Ulic' and u.hp/u.hp_max>=.7),None)
        allowed=(c.map_alias=='AL' and camp and camp['kind']=='mercenary' and b.action==Action.CREEP
                 and not b.attack_committed and not b.player_contact and not b.teleport
                 and not b.situation.threatened and lich and lich.handle not in blocked)
        if not allowed:
            if self.active:self.finish(now,'safety_or_objective_changed')
            return False
        guards=c.camp_units(g,g.creeps());point=(camp['x'],camp['y'])
        if self.active is None:
            if camp['id'] in self.attempted or not guards:return False
            center=min(army,key=lambda u:sum(g.dist(u,v) for v in army))
            if g.dist(center,point)>1500:return False
            own={u.handle for u in army}
            if any((t:=g.current_target(e)) is not None and t.handle in own for e in guards):
                self.attempted.add(camp['id']);return False # Do not reset a fight already in progress.
            origin=(center.x,center.y) if g.dist(center,point)>400 else (b.home.x,b.home.y)
            dx,dy=origin[0]-point[0],origin[1]-point[1];length=max(1,hypot(dx,dy))
            rear=(point[0]+850*dx/length,point[1]+850*dy/length)
            if (not g.map().walkable(*rear) or any(g.path_distance((u.x,u.y),rear) is None
                    or not c.safe_route(g,(u.x,u.y),rear) for u in army if u.handle not in blocked)):
                return False
            target=min(guards,key=lambda e:g.dist(e,rear))
            self.attempted.add(camp['id'])
            self.active=dict(camp=camp['id'],target=target.handle,origin=(target.x,target.y),hp=target.hp,
                             origins={u.handle:(u.x,u.y) for u in guards},
                             rear=rear,started=now,phase='tag',attempts=0,last=-100)
            self.log('al_merc_pull_started',clock=now,camp=camp['id'],lich=lich.handle,target=target.handle,rear=rear)
        job=self.active
        if job['camp']!=camp['id']:
            self.finish(now,'objective_changed');return False
        target=next((u for u in guards if u.handle==job['target']),None)
        if target is None or now-job['started']>=20:
            self.finish(now,'target_unavailable' if target is None else 'unconfirmed_timeout');return False
        attacker=g.current_target(target)
        if job['phase']=='tag' and (target.hp<job['hp']-1 or attacker and attacker.handle==lich.handle):
            job['phase']='pull'
            self.log('al_merc_aggro_observed',clock=now,camp=camp['id'],target=target.handle)
        pulled=next((u for u in guards if u.handle in job['origins'] and
                     g.dist(u,job['origins'][u.handle])>=220 and g.dist(u,job['rear'])<550),None)
        if job['phase']=='pull' and pulled is not None:
            self.log('al_merc_guard_arrived',clock=now,camp=camp['id'],handle=pulled.handle,code=pulled.type)
            self.finish(now,'guard_pulled_observed');return False
        c.pause(now,'mercenary_pull');b.set_intent('雇佣兵营 · 巫妖引怪，守卫到位即开打')
        others=[u for u in army if u.handle!=lich.handle and u.handle not in blocked]
        b.go_raw(others,job['rear'],now)
        if job['phase']=='pull':b.go_raw([lich],job['rear'],now)
        elif job['attempts']<2 and now-job['last']>=4:
            receipt=g.attack(lich,target,force=True);job['attempts']+=1;job['last']=now
            self.log('al_merc_tag_attempt',clock=now,target=target.handle,accepted=bool(receipt),attempt=job['attempts'])
        return True
