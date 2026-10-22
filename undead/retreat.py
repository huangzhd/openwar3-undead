"""Local escape from an occupied home, using visible enemies and real terrain only."""
from math import cos,sin,pi,hypot,ceil,atan2


def clearance(point,enemies,attack_range):
    return min((hypot(point[0]-e.x,point[1]-e.y)-attack_range(e.type) for e in enemies),default=9999)


def statue_rally_rank(point,statues,enemies):
    """Prefer the healing overlap behind the pair, not a flight to one flank.

    Callers must check weapon clearance and route safety before this ranking.
    """
    if not statues:return (0,0,0)
    center=(sum(s.x for s in statues)/len(statues),sum(s.y for s in statues)/len(statues))
    enemy=min(enemies,key=lambda e:hypot(center[0]-e.x,center[1]-e.y),default=None)
    dx,dy=(center[0]-enemy.x,center[1]-enemy.y) if enemy else (0,0)
    length=hypot(dx,dy) or 1;dx,dy=dx/length,dy/length
    rear=(center[0]+140*dx,center[1]+140*dy)
    covered=sum(hypot(point[0]-s.x,point[1]-s.y)<=220 for s in statues)
    front=(point[0]-center[0])*dx+(point[1]-center[1])*dy<0
    return (-covered,front,hypot(point[0]-rear[0],point[1]-rear[1]))


def escape_point(g,unit,enemies,attack_range,preferred=None,home=None):
    start=(unit.x,unit.y)
    nearby=enemies # Include visible threats near the destination, not just near the origin.
    before=clearance(start,nearby,attack_range)
    if before>=200:return start # Reinforcements must not walk into the besieged rally point.
    grid=g.map()
    if not grid:return None
    candidates=[preferred] if preferred is not None else []
    candidates += [(unit.x+radius*cos(i*pi/4),unit.y+radius*sin(i*pi/4))
                   for radius in (320,640,960) for i in range(8)]
    if home is not None:
        angle=atan2(home[1]-unit.y,home[0]-unit.x)
        candidates += [(unit.x+r*cos(angle+o),unit.y+r*sin(angle+o))
                       for r in (320,640,960) for o in (0,pi/4,-pi/4)]
    candidates=[p for p in candidates if grid.walkable(*p) and clearance(p,nearby,attack_range)>before+80]
    # Safe, short escapes first; only eight real routes per unit per planning interval.
    candidates.sort(key=lambda p:(clearance(p,nearby,attack_range)<200,g.dist(p,home) if home is not None else 0,g.dist(start,p),-clearance(p,nearby,attack_range)))
    for point in candidates[:8]:
        length=g.path_distance(start,point)
        if length is None or length>max(480,g.dist(start,point)*1.75):continue
        path=g.walk_path(start,point)
        if not path or g.dist(path[-1],point)>128:continue
        safe=True;a=start
        for b in path:
            count=max(1,ceil(g.dist(a,b)/96))
            if any(clearance((a[0]+(b[0]-a[0])*j/count,a[1]+(b[1]-a[1])*j/count),nearby,attack_range)<before-32
                   for j in range(1,count+1)):
                safe=False;break
            a=b
        if safe:return point
    return None
