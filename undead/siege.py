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


def weapon_range(attacker, target):
    """Public weapon compatibility/range; no hidden enemy upgrades."""
    a=unit_stats(attacker.type);t=unit_stats(target.type)
    if not a or not t:return 0
    kind='air' if t.is_air else 'ground'
    return max((w.range for w in a.weapons if kind in w.targets),default=0)


def fire_clearance(g, unit, point, buildings):
    return min((g.dist(point,b)-weapon_range(b,unit)-64
                for b in buildings if weapon_range(b,unit)>0),default=9999)


def safe_route(g, unit, point, buildings, max_buildings=0):
    """Never approach through a tower's envelope to reach a safe endpoint."""
    from math import ceil
    grid=g.map() if hasattr(g,'map') else None
    if not grid or not grid.walkable(*point) or not hasattr(g,'walk_path'):return False
    start=(unit.x,unit.y);length=g.path_distance(start,point)
    if length is None or length>max(96,g.dist(start,point)*1.5):return False
    path=g.walk_path(start,point)
    if not path or g.dist(path[-1],point)>96:return False
    floor=min(0,fire_clearance(g,unit,start,buildings))
    exposed=set()
    for end in path:
        count=max(1,ceil(g.dist(start,end)/64))
        for j in range(1,count+1):
            p=(start[0]+(end[0]-start[0])*j/count,start[1]+(end[1]-start[1])*j/count)
            if max_buildings:
                exposed.update(b.handle for b in buildings if weapon_range(b,unit)>0 and fire_clearance(g,unit,p,[b])<0)
                if len(exposed)>max_buildings:return False
            elif fire_clearance(g,unit,p,buildings)<floor-8:return False
        start=end
    return True


def firing_point(g, unit, target, buildings, max_buildings=0):
    from math import atan2,cos,sin,pi
    stats=unit_stats(unit.type)
    if not stats:return None
    kind='structure' if is_structure(target) else 'ground'
    radius=max((w.range for w in stats.weapons if kind in w.targets),default=0)-32
    if radius<=0:return None
    angle=atan2(unit.y-target.y,unit.x-target.x)
    candidates=[(target.x+radius*cos(angle+offset),target.y+radius*sin(angle+offset))
                for offset in (0,pi/4,-pi/4,pi/2,-pi/2)]
    candidates=[p for p in candidates if g.dist(unit,p)<=900 and (max_buildings or fire_clearance(g,unit,p,buildings)>=0)]
    for point in sorted(candidates,key=lambda p:g.dist(unit,p))[:3]:
        if safe_route(g,unit,point,buildings,max_buildings=max_buildings):return point
    return None


def repairing(g, worker, buildings):
    if worker.type not in WORKERS or not hasattr(g,'order_of') or g.order_of(worker) not in REPAIR_ORDERS:return False
    target=g.current_target(worker)
    return bool(target and any(b.handle==target.handle and b.owner==worker.owner and b.hp<b.hp_max
                              and g.dist(worker,b)<=450 for b in buildings))

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

    def standoff(self,g,army,visible):
        """Only contest occupied firing zones; healthy units may finish an isolated tower."""
        fighters=[u for u in army if u.type!='uobs' and unit_stats(u.type) and unit_stats(u.type).weapons]
        if not fighters:return None
        anchor=min(fighters,key=lambda u:sum(g.dist(u,v) for v in fighters))
        local=[e for e in visible if can_engage(e) and enemy_player(g,e)
               and (not hasattr(e,'visible_to') or e.visible_to(g.me())) and g.dist(e,anchor)<1800]
        buildings=[e for e in local if is_structure(e)]
        armed=[e for e in buildings if any(weapon_range(e,u)>0 for u in fighters)]
        if not armed:return None
        own={u.handle for u in army}
        defenders=[e for e in local if not is_structure(e) and
                   (e.type not in WORKERS or ((t:=g.current_target(e)) is not None and t.handle in own))]
        core=[u for u in fighters if u.type not in {'uske','uskm','nsce','nsca'}] or fighters
        healthy=all(u.hp/u.hp_max>=.65 for u in core) and sum(u.hp for u in core)>=.8*sum(u.hp_max for u in core)
        if not defenders and healthy:return None
        return armed,buildings,defenders,local

    def safe_target(self,g,unit,armed,buildings,defenders,local,preferred):
        if fire_clearance(g,unit,(unit.x,unit.y),armed)<0:return None
        repairers=[e for e in local if repairing(g,e,buildings)]
        targets=[*repairers,*defenders,*buildings]
        targets=[e for e in targets if in_weapon_range(g,unit,e)
                 and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)
                 and (not e.is_hero or preferred is not None and e.handle==preferred.handle)]
        def rank(e):
            if e in repairers:return (0,0,e.hp)
            if not is_structure(e):return (1 if preferred is not None and e.handle==preferred.handle else 2,
                                             0 if e.type in {'ocat','hmtm','ebal','umtw'} else 1,e.hp)
            return (3,building_priority(g,e),e.hp)
        return min(targets,key=rank,default=None)
