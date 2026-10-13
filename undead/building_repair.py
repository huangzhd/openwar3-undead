"""Acolyte restoration of previously completed critical owned buildings."""


class BuildingRepair:
    def __init__(self,log):
        self.log=log;self.tasks={};self.retry={}

    @property
    def reserved(self):return set(self.tasks)

    def tick(self,g,e,home,now):
        if not hasattr(g,'cast'):return False
        from .targeting import in_weapon_range, enemy_player
        from openwar3.orders import ORDER
        workers={u.handle:u for u in g.units('me',{'uaco'})}
        buildings={u.handle:u for u in g.my_buildings({'ugol','unpl','unp1','unp2'})}
        enemies=[u for u in g.enemies() if enemy_player(g,u) and u.hp>0] if hasattr(g,'enemies') else []
        unsafe=lambda w:any(in_weapon_range(g,u,w) for u in enemies)
        res=g.resources() or {}
        funded=res.get('gold',0)>0 and res.get('lumber',0)>0
        for handle,t in list(self.tasks.items()):
            w=workers.get(handle);b=buildings.get(t['building'])
            reason=('worker_missing' if not w else 'building_missing' if not b else
                    'complete' if b.hp>=b.hp_max*.98 else 'unfunded' if not funded else
                    'worker_threatened' if unsafe(w) or w.hp<w.hp_max*.5 else None)
            if reason:
                self.tasks.pop(handle)
                if w and hasattr(g,'stop'):g.stop(w)
                self.log('building_repair_end',clock=now,worker=handle,reason=reason)
                continue
            restoring=g.order_of(w)==ORDER('restoration')
            if restoring and b.hp>t['hp']+5:
                self.log('building_repair_progress',clock=now,worker=handle,building=b.handle,
                         hp_gain=b.hp-t['hp'],basis='hp_increase_while_restoration_order')
                t['hp']=b.hp;t['progress']=now
            if now-t['progress']>15:
                self.tasks.pop(handle);self.retry[b.handle]=now+60
                if hasattr(g,'stop'):g.stop(w)
                self.log('building_repair_end',clock=now,worker=handle,reason='no_progress')
            elif not restoring and now-t['attempt_at']>=3:
                if t['attempts']>=3:
                    self.tasks.pop(handle);self.retry[b.handle]=now+60
                    self.log('building_repair_end',clock=now,worker=handle,reason='order_unconfirmed')
                else:self.order(g,w,b,now,t)
        candidates=[b for b in buildings.values() if b.handle in e.complete and b.hp<b.hp_max*.85
                    and now>=self.retry.get(b.handle,0) and g.dist(b,home)<1600
                    and not ((p:=g.production(b)) and p.kind=='construction')]
        if funded and candidates:
            target=min(candidates,key=lambda b:(b.type!='ugol',b.hp/b.hp_max))
            available=[w for w in workers.values() if w.handle not in self.tasks and
                       w.handle!=e.scout and w.handle not in e.expansion.reserved and
                       not g.is_constructing(w) and w.hp>=w.hp_max*.8 and not unsafe(w)
                       and g.dist(w,target)<600 and (d:=g.path_distance((w.x,w.y),(target.x,target.y))) is not None and d<900]
            for w in sorted(available,key=lambda w:g.dist(w,target))[:max(0,2-len(self.tasks))]:
                t=dict(building=target.handle,hp=target.hp,progress=now,attempts=0,attempt_at=-100)
                self.tasks[w.handle]=t;self.order(g,w,target,now,t)
        # Preserve funds only for a critical building with an actual repair job.
        return any((b:=buildings.get(t['building'])) and b.hp<b.hp_max*.4 for t in self.tasks.values())

    def order(self,g,w,b,now,t):
        # UnitAbilities.slk: uaco has Arst; SDK repair() sends the human Arep
        # order. Acolytes need the public restoration order instead.
        receipt=g.cast(w,'restoration',target=b)
        t['attempt_at']=now;t['attempts']+=1
        self.log('building_repair_attempt',clock=now,worker=w.handle,building=b.handle,
                 code=b.type,accepted=bool(receipt),attempt=t['attempts'])
