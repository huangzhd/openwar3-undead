"""Spare summoned skeletons scout public expansion sites using fair vision only."""
from .structures import is_structure

SKELETONS={'uske','uskm','ndr1','ndr2','ndr3'}


class SkeletonScouts:
    def __init__(self,log):
        self.log=log;self.assignments={};self.checked=set();self.attempts={};self.seen=set()

    def plan(self,g,center,home,main,sites,enemies,now,active,reserved=()):
        live={u.handle:u for u in g.units('me',SKELETONS) if u.handle not in reserved}
        for handle,job in list(self.assignments.items()):
            u=live.get(handle);point=job['point']
            if u is None:
                self.log('skeleton_scout_ended',clock=now,handle=handle,point=point,reason='unit_missing')
                del self.assignments[handle];continue
            for enemy in enemies:
                if (enemy.handle not in self.seen and is_structure(enemy) and
                    g.dist(enemy,point)<1200 and g.dist(u,enemy)<1800):
                    self.seen.add(enemy.handle)
                    self.log('skeleton_scout_structure_seen',clock=now,scout=handle,code=enemy.type,
                             handle=enemy.handle,point=(enemy.x,enemy.y),site=point)
            if g.dist(u,point)<500 and g.visible(*point):
                self.checked.add(point)
                self.log('skeleton_scout_checked',clock=now,handle=handle,point=point,evidence='visible_point')
                del self.assignments[handle]
            elif now-job['started']>45:
                self.log('skeleton_scout_ended',clock=now,handle=handle,point=point,reason='time_limit')
                del self.assignments[handle]
        if active:
            # Keep the two nearest skeletons with the army; at most two scouts.
            available=sorted((u for h,u in live.items() if h not in self.assignments),key=lambda u:g.dist(u,center))[2:]
            busy={job['point'] for job in self.assignments.values()}
            points={tuple(p) for p in sites if g.dist(p,home)>1400 and g.dist(p,main)>1800}
            for u in available:
                if len(self.assignments)>=2:break
                candidates=[p for p in points if p not in self.checked and p not in busy and self.attempts.get(p,0)<2]
                if not candidates:break
                point=min(candidates,key=lambda p:(g.dist(u,p),p))
                self.attempts[point]=self.attempts.get(point,0)+1
                if g.path_distance((u.x,u.y),point) is None:
                    self.log('skeleton_scout_ended',clock=now,handle=u.handle,point=point,reason='unreachable')
                    continue
                self.assignments[u.handle]=dict(point=point,started=now)
                busy.add(point)
                self.log('skeleton_scout_assigned',clock=now,handle=u.handle,unit=u.type,point=point,
                         attempt=self.attempts[point],retained_with_army=2)
        return [(live[h],job['point']) for h,job in self.assignments.items()]


from functools import lru_cache
from math import cos,sin,pi
import bootstrap
import hashlib,json
from pathlib import Path
import w3paths
from w3slk import read_slk
from openwar3 import combat

@lru_cache(maxsize=1)
def ground_critters():
    # Public type definitions only, never map placements or hidden unit positions.
    return frozenset(r['unitID'] for r in read_slk(w3paths.game_data('UnitData.slk'))
                     if r.get('race')=='critters' and (s:=combat.stats(r['unitID'])) and not s.is_air)

def public_critter_spawns(map_path=None):
    """Use fixed map placements only when the installed map matches the catalog."""
    try:
        catalog=json.loads((bootstrap.ROOT/'data/echo_isles_critters.json').read_text(encoding='utf-8'))
        if map_path is None:
            config=json.loads((bootstrap.UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
            map_path=Path(config['game_dir'])/'Maps'/config['default_map']
        if hashlib.sha256(Path(map_path).read_bytes()).hexdigest()!=catalog['map_sha256']:return []
        return catalog['spawns']
    except (OSError,ValueError,KeyError,TypeError):
        return [] # Unknown/changed map: retain the fair general search.

class CritterSearch:
    """Bounded local exploration, driven by fair vision and ground-route progress."""
    DEADLINE=150
    def __init__(self,log,spawns=None):
        self.spawns=public_critter_spawns() if spawns is None else spawns
        self.point_priority={};self.spawn_center=None
        self.log=log;self.checked=set();self.failed=set();self.points=None;self.job=None
        self.route_attempts={};self.retry_at={};self.last_eval=-100;self.reported=False
        self.hunt=None;self.hunt_failed=set()

    def cancel(self):
        # Combat/lost-target recovery must not inherit a stale waypoint timer.
        self.job=None

    def target(self,g,scout,home,now,safe_route=None):
        if now>=self.DEADLINE:return None
        visible=[u for u in g.units('all') if 12<=u.owner<=15 and u.type in ground_critters()
                 and u.hp>0 and g.dist(u,home)<=3000 and u.handle not in self.hunt_failed]
        current=next((u for u in visible if self.hunt and u.handle==self.hunt['handle']),None)
        if current:
            distance=g.path_distance(scout,current)
            job=self.hunt
            if distance is not None and (distance<job['distance']-60 or current.hp<job['hp']-.5):
                job.update(distance=distance,hp=current.hp,progress=now)
            safe=safe_route is None or safe_route((scout.x,scout.y),(current.x,current.y))
            if distance is None or not safe or now-job['progress']>=8 or now-job['started']>=20:
                self.hunt_failed.add(current.handle);self.hunt=None
                self.log('scout_critter_abandoned',clock=now,handle=current.handle,reason='unreachable_or_no_progress')
                visible.remove(current);current=None
            else:return current
        if not visible:return None
        reachable=[]
        for u in sorted(visible,key=lambda u:g.dist(scout,u))[:8]:
            if safe_route is not None and not safe_route((scout.x,scout.y),(u.x,u.y)):continue
            route=g.path_distance(scout,u)
            if route is not None and route<=min(3200,max(0,self.DEADLINE-now-3)*180):reachable.append((route,u))
        if not reachable:return None
        distance,target=min(reachable,key=lambda row:(row[0],row[1].hp,row[1].handle))
        self.hunt=dict(handle=target.handle,started=now,progress=now,distance=distance,hp=target.hp)
        self.cancel()
        return target

    def choose(self,g,scout,home,now,safe_route=None):
        if now>=self.DEADLINE:
            self.job=None;return None
        if now-self.last_eval<1:return self.job['point'] if self.job else None
        self.last_eval=now
        if self.points is None:
            mp=g.map() if hasattr(g,'map') else None
            self.points=[]
            def add(point,priority):
                if point in self.point_priority:return
                if hasattr(mp,'walkable') and not mp.walkable(*point):return
                self.points.append(point);self.point_priority[point]=priority
            local=[spawn for spawn in self.spawns if g.dist(home,(spawn['x'],spawn['y']))<=3000]
            if local:
                spawn=min(local,key=lambda s:g.dist(home,(s['x'],s['y'])))
                center=(spawn['x'],spawn['y']);self.spawn_center=center
                add(center,0)
                # Wander makes this a search area, not a guaranteed current position.
                for i in range(8):
                    add((round(center[0]+450*cos(i*pi/4)),round(center[1]+450*sin(i*pi/4))),1)
                self.log('scout_spawn_region',clock=now,code=spawn['code'],center=center,radius=450,
                         source='fingerprint_verified_static_map',evidence='initial_placement_only')
            for radius,count in ((900,8),(1700,12),(2500,16)):
                for i in range(count):
                    add((round(home.x+radius*cos(2*pi*i/count)),round(home.y+radius*sin(2*pi*i/count))),2)
            self.log('scout_search_plan',clock=now,candidates=len(self.points),radii=[900,1700,2500],
                     spawn_region=center if local else None,deadline=self.DEADLINE)
        # At most 12 engine visibility queries per second. None is not evidence.
        pending=[p for p in self.points if p not in self.checked and p not in self.failed]
        nearby=sorted(pending,key=lambda p:(self.point_priority[p],g.dist(scout,p)))[:12]
        if self.job and self.job['point'] not in nearby:nearby=[self.job['point']]+nearby[:11]
        seen={p for p in nearby if g.visible(*p) is True}
        self.checked.update(seen)
        for point in sorted(seen):
            self.log('scout_search_checked',clock=now,point=point,evidence='visible_point')
        if self.job:
            job=self.job;point=job['point'];route=g.path_distance(scout,point)
            reason=None
            if point in seen:reason='arrived' if g.dist(scout,point)<220 else 'visible_point'
            elif route is not None and route<job['distance']-80:job.update(distance=route,progress=now)
            if reason is None and (route is None or now-job['progress']>=8 or now-job['started']>=24):
                reason='no_progress_or_budget';self.failed.add(point)
            if reason:
                self.job=None
                self.log('scout_search_finished',clock=now,point=point,reason=reason,
                         scout=(scout.x,scout.y),ground_distance=route)
            else:return point
        # Only a local batch is path-tested; distant points remain eligible later.
        pending=[p for p in self.points if p not in self.checked and p not in self.failed and now>=self.retry_at.get(p,0)]
        reachable=[]
        for point in sorted(pending,key=lambda p:(self.point_priority[p],g.dist(scout,p)))[:8]:
            route=g.path_distance(scout,point)
            if route is None:
                self.route_attempts[point]=self.route_attempts.get(point,0)+1
                self.retry_at[point]=now+5
                if self.route_attempts[point]>=2:self.failed.add(point)
                self.log('scout_search_deferred',clock=now,point=point,reason='route_unknown_or_blocked',attempt=self.route_attempts[point])
                continue
            if route>max(0,self.DEADLINE-now-3)*180:
                self.retry_at[point]=now+5;continue
            if safe_route is not None and not safe_route((scout.x,scout.y),point):
                self.failed.add(point);continue
            reachable.append((self.point_priority[point],route,point))
        if not reachable:
            if len(self.checked|self.failed)==len(self.points) and not self.reported:
                self.reported=True
                self.log('scout_search_exhausted',clock=now,visible_points=len(self.checked),failed_points=len(self.failed))
            return None
        _,distance,point=min(reachable)
        self.job=dict(point=point,started=now,progress=now,distance=distance)
        self.log('scout_search_started',clock=now,point=point,ground_distance=distance,
                 radius=round(g.dist(home,point)),search_kind='spawn_region' if self.point_priority[point]<2 else 'general')
        return point
