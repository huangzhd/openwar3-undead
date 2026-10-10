"""Three home ghouls repel small, visible ground raids and then resume lumber."""
from .structures import is_structure

RADIUS=1600
RETURN_RADIUS=800
SIEGE={'ocat','hmtm','ebal','umtw'}

class HomeDefense:
    def __init__(self,log):
        self.log=log;self.active=set();self.returning=set();self.raiders=[]
        self.target=None;self.orders={};self.cooldown={};self.failed={}

    @property
    def reserved(self):return self.active|self.returning

    def order(self,g,u,key,now,send):
        token=(u.handle,key)
        if self.failed.get(token,0)>=3:return False
        if now-self.orders.get(token,-100)<2:return None
        self.orders[token]=now;ok=bool(send())
        self.failed[token]=0 if ok else self.failed.get(token,0)+1
        self.log('home_defense_order',clock=now,unit=u.handle,kind=key[0],target=key[1:],accepted=ok)
        return ok

    def withdraw(self,handles,now,reason):
        handles=set(handles)&self.active
        if handles:
            self.active-=handles;self.returning|=handles
            for h in handles:self.cooldown[h]=now+10
            self.log('home_defense_return',clock=now,units=sorted(handles),reason=reason)
        if not self.active:self.target=None

    def tick(self,g,home,foes,now,is_air):
        ghouls={u.handle:u for u in g.units('me',{'ugho'}) if u.hp>0}
        self.active&=ghouls.keys();self.returning&=ghouls.keys()
        self.raiders=[e for e in foes if e.hp>0 and not is_structure(e) and g.dist(e,home)<=RADIUS and e.visible_to(g.me())]
        local=self.raiders
        suitable=bool(local) and len(local)<=3 and not any(e.is_hero or is_air(e.type) for e in local)
        if self.active:
            if any(ghouls[h].hp/ghouls[h].hp_max<=.35 or g.dist(ghouls[h],home)>RADIUS for h in self.active):
                self.withdraw(self.active,now,'health_or_leash')
            elif not suitable:self.withdraw(self.active,now,'threat_left_or_too_large')
        healthy=[u for u in ghouls.values() if u.hp/u.hp_max>.45 and g.dist(u,home)<=1200 and
                 u.handle not in self.returning and now>=self.cooldown.get(u.handle,0)]
        if suitable and not self.active and len(healthy)>=3:
            team=sorted(healthy,key=lambda u:g.dist(u,home))[:3]
            # Three ghouls should not charge three full-health heavy melee units.
            if sum(e.hp for e in local)<=sum(u.hp for u in team)*1.5:
                self.active={u.handle for u in team}
                self.log('home_defense_started',clock=now,units=sorted(self.active),enemies=[e.type for e in local])
        if self.active and (len(self.active)<3 or sum(e.hp for e in local)>sum(ghouls[h].hp for h in self.active)*1.5):
            self.withdraw(self.active,now,'insufficient_local_strength')
        handled=False
        if self.active:
            target=min(local,key=lambda e:(e.type not in SIEGE,e.handle!=self.target,g.dist(e,home)))
            self.target=target.handle
            reachable=all(0<=g.path_distance(ghouls[h],target)<=2400 for h in self.active)
            if not reachable:self.withdraw(self.active,now,'unreachable_or_long_path')
            else:
                handled=True
                for h in sorted(self.active):
                    u=ghouls[h];current=g.current_target(u)
                    if current and current.handle==target.handle:continue
                    ok=self.order(g,u,('attack',target.handle),now,lambda u=u:g.attack(u,target))
                    if ok is False or (ok is None and self.failed.get((h,('attack',target.handle)),0)):
                        handled=False
                if not handled and any(self.failed.get((h,('attack',target.handle)),0)>=3 for h in self.active):
                    self.withdraw(self.active,now,'attack_rejected')
        for h in list(self.returning):
            u=ghouls[h]
            if g.dist(u,home)>RETURN_RADIUS:
                self.order(g,u,('return',(home.x,home.y)),now,lambda u=u:g.move(u,home.x,home.y))
                continue
            trees=[t for t in g.trees(home.x,home.y) if g.dist(t,home)<=1200]
            tree=min(trees,key=lambda t:g.dist(t,u)) if trees else None
            if tree:
                tree_key=(tree.handle_lo,tree.handle_hi)
                ok=self.order(g,u,('harvest',tree_key),now,lambda u=u:g.gather(u,tree))
                if ok:
                    self.returning.remove(h)
                    self.log('home_defense_harvest_ordered',clock=now,unit=h,tree=tree_key)
            else:
                self.order(g,u,('return',(home.x,home.y)),now,lambda u=u:g.move(u,home.x,home.y))
        # Forget obsolete targets and dead units; rejection limits apply per live order.
        live=self.reserved
        self.orders={k:v for k,v in self.orders.items() if k[0] in live}
        self.failed={k:v for k,v in self.failed.items() if k[0] in live}
        return handled
