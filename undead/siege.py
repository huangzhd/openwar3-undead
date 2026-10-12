"""Shared local siege focus, using only fair visible units/orders/production."""
from .structures import is_structure
from .targeting import enemy_player,unit_stats,in_weapon_range,buffs,abilities,can_engage
from openwar3.orders import REPAIR,REVIVE,ORDER

TOWERS={'hgtw','hctw','hatw','owtw','uzg1','uzg2','etrp'}
ALTARS={'halt','oalt','eate','uaod'}
HALLS={'htow','hkee','hcas','ogre','ostr','ofrt','unpl','unp1','unp2','etol','etoa','etoe'}
WORKERS={'hpea','opeo','uaco','ewsp'}
REPAIR_ORDERS={REPAIR,ORDER('renew'),ORDER('restoration')}

def building_priority(g,u):
    if u.type in TOWERS:return 0
    if u.type=='otrb':return 1
    if u.type=='emow':return 2
    if u.type in ALTARS and hasattr(g,'production') and hasattr(g,'order_of'):
        p=g.production(u)
        # A hero training queue alone cannot prove revival. Unknown/idle stays ordinary.
        if (g.order_of(u)==REVIVE and p and p.kind=='queue' and not p.blocked and
            p.duration>0 and p.queue and str(p.queue[0])[0].isupper()):return 3
    if u.type in HALLS:return 4
    return 5

def attackable(g,u,target):
    stats=unit_stats(u.type)
    kind='structure' if is_structure(target) else 'ground'
    return bool(stats and any(kind in w.targets for w in stats.weapons))

def reachable(g,u,target):
    return in_weapon_range(g,u,target) or (hasattr(g,'path_distance') and
        g.path_distance((u.x,u.y),(target.x,target.y)) is not None)

class SiegeFocus:
    def __init__(self,log):self.log=log;self.target=None

    def choose(self,g,army,foes,now):
        fighters=[u for u in army if u.type!='uobs' and (s:=unit_stats(u.type)) and s.weapons]
        if not fighters:self.target=None;return None
        core=[u for u in fighters if u.type not in {'uske','uskm','nsce','nsca'}] or fighters
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core))
        visible=[e for e in foes if can_engage(e) and enemy_player(g,e) and
                 (not hasattr(e,'visible_to') or e.visible_to(g.me())) and g.dist(e,anchor)<950]
        buildings=[e for e in visible if is_structure(e)]
        if not buildings:self.target=None;return None
        # Combat troops inside the siege area retain normal battle priorities.
        # Idle/harvesting workers do not block siege; attacking workers do.
        own={u.handle for u in army}
        for e in visible:
            if is_structure(e):continue
            target=g.current_target(e)
            if e.type not in WORKERS or (target and target.handle in own):
                self.target=None;return None
        repairers=[]
        by_handle={e.handle:e for e in buildings}
        for e in visible:
            if e.type not in WORKERS or not hasattr(g,'order_of') or g.order_of(e) not in REPAIR_ORDERS:continue
            target=g.current_target(e)
            building=by_handle.get(target.handle) if target else None
            if building and building.owner==e.owner and building.hp<building.hp_max and g.dist(e,building)<=450:
                repairers.append(e)
        ranked=[]
        for e in [*repairers,*buildings]:
            if buffs(g,e) & {'Bvul','BHds'} or 'Avul' in abilities(g,e):continue
            if not any(attackable(g,u,e) and reachable(g,u,e) for u in fighters if g.dist(u,anchor)<700):continue
            rank=-1 if e in repairers else building_priority(g,e)
            ranked.append((rank,e))
        if not ranked:self.target=None;return None
        best=min(rank for rank,e in ranked)
        peers=[e for rank,e in ranked if rank==best]
        selected=next((e for e in peers if e.handle==self.target),None) or min(peers,key=lambda e:(g.dist(e,anchor),e.hp,e.handle))
        if selected.handle!=self.target:
            self.log('siege_target',clock=now,handle=selected.handle,type=selected.type,priority=best,
                     reason='repair_worker' if best==-1 else 'building_priority')
        self.target=selected.handle
        return selected
