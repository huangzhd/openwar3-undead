"""Shared battle placement, rear dispellers and coordinated ranged fire.

Training and melee controllers both inherit this implementation. Arena lifecycle
and search waypoints belong to the training adapter, not this module.
"""
from math import hypot, cos, sin, pi
from .structures import is_structure
from .scouting import SKELETONS
from .targeting import can_engage, in_weapon_range, unit_stats, webbed_air, abilities, tc_pressure_target
from .nc_combo import spell_data
from .policy import Action
from .battle_spells import silence_key_hero


class BattleTacticsMixin:
    def init_battle_tactics(self):
        self.prep_points = {}
        self.prep_sent = {}
        self.ranged_focus = None
        self.battle_focus_handles = set()
        self.prebattle_since = None
        self.battle_dk_support = set()
        self.opening_nc_deadline=None
        self.opening_nc_waiting=False

    def prepare_battle(self, now, army=None, target=None, blocked=(), limit=None, foes=()):
        """The same role layout for a countdown or a visible approaching fight."""
        g = self.g
        if army is None:army = [u for u in g.my_units() if u.alive and not is_structure(u)]
        if not army:
            return set()
        target = target or self.enemy_main
        if target is None:return set()
        if not self.prep_points:
            center = (sum(u.x for u in army)/len(army), sum(u.y for u in army)/len(army))
            dx, dy = target[0]-center[0], target[1]-center[1]
            length = max(1, hypot(dx, dy))
            forward, side = (dx/length, dy/length), (-dy/length, dx/length)
            def point(front, flank):
                return (center[0]+front*forward[0]+flank*side[0],
                        center[1]+front*forward[1]+flank*side[1])
            roles = {'ugho': [(210, i*115) for i in range(-3, 4)],
                     'Udea': [(-280, 540)], 'Ulic': [(-140, -180)],
                     'Nbrn': [(-110, 180)], 'Nngs': [(-110, 180)],
                     'ubsp': [(-400, -100), (-400, 100)],
                     'uobs': [(-140, -120), (-140, 120)]}
            fiends = [u for u in army if u.type == 'ucry']
            roles['ucry'] = [(90-140*(i//6), (i%6-(min(6, len(fiends)-6*(i//6))-1)/2)*160)
                             for i in range(len(fiends))]
            for kind, slots in roles.items():
                units = sorted((u for u in army if u.type == kind), key=lambda u: u.handle)
                for u, (front, flank) in zip(units, slots):
                    self.prep_points[u.handle] = point(front, flank)
            self.log('battle_prebattle_layout', clock=now,
                     points=[dict(handle=h, point=p) for h,p in self.prep_points.items()])
        grid = g.map()
        moving=set()
        for u in army:
            point = self.prep_points.get(u.handle)
            if (point is None or u.handle in blocked or now<self.cast_until.get(u.handle,0)
                    or g.dist(u, point) <= 75):
                continue
            if limit is not None and len(moving)>=limit:break
            if now-self.prep_sent.get(u.handle,-100)<3:
                moving.add(u.handle);continue
            if u.type not in {'ubsp'} and grid and not grid.walkable(*point):
                self.log('battle_prebattle_point_blocked', clock=now, handle=u.handle, point=point)
                continue
            if u.type!='ubsp':
                route=g.path_distance((u.x,u.y),point)
                if route is None or route>g.dist(u,point)+128:continue
            kind='air' if u.type=='ubsp' else 'ground'
            threats=[(e,max((w.range for w in stats.weapons if kind in w.targets),default=0))
                     for e in foes if (stats:=unit_stats(e.type))]
            if any(reach and any(g.dist((u.x+(point[0]-u.x)*i/8,u.y+(point[1]-u.y)*i/8),e)<reach+100
                                 for i in range(1,9)) for e,reach in threats):continue
            receipt = g.move(u, *point)
            if receipt and u.type=='Udea':g.hold(u,queue='after')
            self.prep_sent[u.handle] = now
            if receipt:moving.add(u.handle)
            self.log('battle_prebattle_move_attempt', clock=now, handle=u.handle,
                     type=u.type, point=point, accepted=bool(receipt))
        return moving

    def battle_actions(self, army, foes, now, pulls, blocked=(), search_point=None):
        """Shared precontact layout, rear safety, dispel and offensive spells."""
        g=self.g
        if not army:return
        if foes:
            firing=any(in_weapon_range(g,u,e) for u in army if u.type not in {'uobs','ubsp'} for e in foes)
            own={u.handle for u in army}
            firing=firing or any((t:=g.current_target(e)) is not None and t.handle in own for e in foes)
            if firing:
                self.prebattle_since=now-5
            elif self.prebattle_since is None:
                self.prebattle_since=now;self.prep_points.clear();self.prep_sent.clear()
            if not firing and now-self.prebattle_since<=4 and any(g.dist(u,e)<1100 for u in army for e in foes):
                target=min(foes,key=lambda e:min(g.dist(u,e) for u in army))
                moving=self.prepare_battle(now,army,(target.x,target.y),set(pulls)|set(blocked),limit=2,foes=foes)
                for handle in moving:pulls[handle]=self.prep_points[handle]
        else:
            self.prebattle_since=None
            self.opening_nc_deadline=None;self.opening_nc_waiting=False
        self.rear_dk(army,foes,now,pulls,blocked)
        self.rear_destroyers([u for u in army if u.handle not in blocked],foes,now,pulls,search_point)
        reserved=set(pulls)|set(blocked)
        if not self.teleport:
            silence_key_hero(self,army,foes,now,reserved,tc_only=True)
        # Dispel from current range before executing the retained retreat goal.
        dispel_blocked=(set(pulls)-{u.handle for u in army if u.type=='ubsp'})|set(blocked)|set(self.shield_moves)
        self.destroyer.tick(self,army,foes,now,dispel_blocked)
        self.combat_spells(army,foes,now,(set(pulls)-self.battle_dk_support)|set(blocked))

    def rear_dk(self,army,foes,now,pulls,blocked=()):
        """Keep the battle DK behind the ranged body, in healing distance."""
        g=self.g
        self.battle_dk_support=set()
        dk=next((u for u in army if u.type=='Udea'),None)
        main=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
        if not dk or not main or not foes or self.teleport:return
        if not all(hasattr(g,name) for name in ('move','walk_path','map')):return
        self.battle_dk_support.add(dk.handle)
        if dk.handle in pulls or dk.handle in blocked or now<self.cast_until.get(dk.handle,0):return
        anchor=min(main,key=lambda u:sum(g.dist(u,v) for v in main))
        enemy=min(foes,key=lambda e:g.dist(anchor,e))
        dx,dy=anchor.x-enemy.x,anchor.y-enemy.y;length=hypot(dx,dy) or 1
        dx,dy=dx/length,dy/length
        threats=[(e,max((w.range for w in stats.weapons if 'ground' in w.targets),default=0))
                 for e in foes if (stats:=unit_stats(e.type))]
        clearance=lambda p:min((g.dist(p,e)-r for e,r in threats if r>0),default=9999)
        if self.opening_nc_waiting and now<(self.opening_nc_deadline or 0) and clearance(dk)>=100:
            if self.due('opening_nc_dk_hold',now,.5):g.hold(dk)
            return # Do not move farther away while TC is entering paired cast range.
        lich=next((u for u in main if u.type=='Ulic'),None)
        chiefs=[e for e in foes if e.type=='Otch']
        spacing=0
        if lich and chiefs:
            # One stomp can cover two heroes separated by twice its radius.
            # Unknown enemy spell level uses the largest public radius; no
            # hidden enemy state is queried. Remain inside Coil's 750 range.
            row=spell_data()[0]['AOws']
            levels=[abilities(g,e).get('AOws',{}).get('level') for e in chiefs]
            spacing=32+2*max(float(row['Area'+str(l if l in (1,2,3) else 3)]) for l in levels)
        behind=(dk.x-anchor.x)*dx+(dk.y-anchor.y)*dy
        if (behind>=140 and g.dist(dk,anchor)<=(850 if spacing else 600) and clearance(dk)>=100
                and (not spacing or spacing<=g.dist(dk,lich)<740)):
            if self.due(('battle_dk_hold',dk.handle),now,2):g.hold(dk)
            return
        candidates=[(anchor.x+dx*back-dy*side,anchor.y+dy*back+dx*side)
                    for back in (200,280,400,520) for side in (0,-160,160)]
        if spacing:
            goal_gap=min(736,spacing+100) # Allow for stopping short of the requested point.
            candidates += [(lich.x+goal_gap*cos(i*pi/12),lich.y+goal_gap*sin(i*pi/12)) for i in range(24)]
            candidates=[p for p in candidates if spacing<=g.dist(p,lich)<740
                        and (p[0]-anchor.x)*dx+(p[1]-anchor.y)*dy>=140 and g.dist(p,anchor)<=850]
        candidates.sort(key=lambda p:(clearance(p)<100,-min(clearance(p),100),g.dist(p,anchor),g.dist(p,dk)))
        before=clearance(dk)
        for point in candidates:
            if clearance(point)<min(100,before)-8:continue
            route=self.army_recovery.safe_path(self,(dk.x,dk.y),point,foes,combat=True)
            if route is None or route>1100:continue
            pulls[dk.handle]=point
            if self.due(('battle_dk_rear',dk.handle),now,2):
                self.log('battle_dk_rear',clock=now,handle=dk.handle,point=point,clearance=round(clearance(point)),
                         lich_distance=round(g.dist(point,lich)) if lich else None,minimum_spacing=spacing)
            return
        # A blocked reposition must not fall through into melee attacks.
        pulls[dk.handle]=(dk.x,dk.y)

    def rear_destroyers(self, army, foes, now, pulls, search_point):
        """Keep dispellers behind the ground force and outside AA fire."""
        g = self.g
        ground = [u for u in army if u.type not in {'ubsp', 'uobs'}]
        if not ground:
            ground = [u for u in army if u.type == 'uobs']
        threats = []
        for e in foes:
            stats = unit_stats(e.type)
            reach = max((w.range for w in stats.weapons if 'air' in w.targets), default=0) if stats else 0
            if reach:
                threats.append((e, reach))
        blocked = set()
        for u in (u for u in army if u.type == 'ubsp'):
            anchor = min(ground, key=lambda a: sum(g.dist(a,b) for b in ground)) if ground else self.home
            enemy = min(foes, key=lambda e: g.dist(anchor,e)) if foes else None
            front = (enemy.x, enemy.y) if enemy else search_point or self.enemy_main
            if front is None:continue
            dx, dy = front[0]-anchor.x, front[1]-anchor.y
            length = max(1, hypot(dx,dy));dx,dy = dx/length,dy/length
            def clearance(p):
                return min((g.dist(p,e)-reach for e,reach in threats), default=9999)
            candidates = [(anchor.x-back*dx-side*dy, anchor.y-back*dy+side*dx)
                          for back in (260,420,620,850) for side in (0,-220,220,-440,440)]
            # Never cross a more dangerous firing lane to reach a safe endpoint.
            before = clearance((u.x,u.y))
            candidates = [p for p in candidates if all(
                clearance((u.x+(p[0]-u.x)*i/12,u.y+(p[1]-u.y)*i/12)) >= min(140,before)-8
                for i in range(1,13))]
            safe = [p for p in candidates if clearance(p)>=140]
            goal = min(safe, key=lambda p:g.dist(p,(anchor.x-260*dx,anchor.y-260*dy))+.15*g.dist(u,p)) if safe else (
                max(candidates, key=clearance) if candidates else None)
            unsafe = before < 140
            if goal is not None and (g.dist(u,goal)>120 or unsafe):
                blocked.add(u.handle)
                # This air-specific retreat replaces ground-path micro for this unit.
                pulls[u.handle] = goal
                if self.due(('battle_destroyer_rear',u.handle),now,2):
                    self.log('battle_destroyer_rear',clock=now,handle=u.handle,point=goal,
                             air_clearance=round(before),safe_goal=bool(safe))
            elif unsafe or u.handle in pulls:
                blocked.add(u.handle)
            elif now >= self.cast_until.get(u.handle,0) and self.due(('battle_destroyer_hold',u.handle),now,2):
                # Hold prevents automatic acquisition from starting a forward chase.
                g.hold(u)
        return blocked

    def focus_ranged(self, army, foes, now):
        """Fiends, Lich and Dark Ranger share one persistent, reachable target."""
        if sum(u.type=='ucry' for u in army)<2:
            return set()
        g = self.g
        squad = [u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'}]
        ready = [u for u in squad if now>=self.cast_until.get(u.handle,0)]
        candidates = [e for e in foes if can_engage(e) and self.combat_progress.allowed(e,now) and
                      any(in_weapon_range(g,u,e) for u in ready) and
                      self.hero_pressure.estimate(g,ready,e)<float('inf')]
        if not candidates:
            self.ranged_focus = None
            return set()
        coverage = lambda e: sum(in_weapon_range(g,u,e) for u in ready)
        combo = self.nc_combo.focus(candidates,now)
        heroes = [e for e in candidates if e.is_hero and coverage(e)>=2
                  and self.hero_pressure.estimate(g,ready,e)<=2.5
                  and not self.hero_pressure.support(g,e,foes,now,2.5)]
        troops = [e for e in candidates if not e.is_hero]
        trapped = [e for e in troops if webbed_air(g,e)]
        own={u.handle for u in army}
        dangerous=[e for e in troops if (stats:=unit_stats(e.type)) and
                   any(w.range>=400 for w in stats.weapons) and
                   (victim:=g.current_target(e)) is not None and victim.handle in own and coverage(e)>=2]
        previous = next((e for e in troops if e.handle==self.ranged_focus),None)
        pool = trapped or dangerous or troops or candidates
        # Prefer an accessible common target over a lone unit's distant victim.
        enough = max(1, (len(ready)+1)//2)
        shared = [e for e in pool if coverage(e)>=enough] or pool
        chief=self.hero_pressure.orc_focus(g,ready,foes,now)
        if chief not in candidates:chief=None
        target=chief
        target = target or combo or (min(heroes,key=lambda e:self.hero_pressure.estimate(g,ready,e)) if heroes else None)
        target = target or (previous if previous in shared else min(shared,key=lambda e:self.hero_pressure.rank(g,ready,e)))
        if target.handle != self.ranged_focus:
            self.log('battle_ranged_focus_selected',clock=now,target=target.handle,type=target.type,
                     reason='tc_pressure' if target.type=='Otch' else 'farseer_after_tc' if chief and target.type=='Ofar' else 'hero_finish' if target.is_hero else 'unit_focus',shooters=coverage(target))
        self.ranged_focus = target.handle
        for u in ready:
            current = g.current_target(u)
            if in_weapon_range(g,u,target):
                if (not current or current.handle!=target.handle) and self.due(('battle_ranged_attack',u.handle),now,1.2):
                    receipt = g.attack(u,target)
                    self.combat_progress.attack_result(u,target,now,bool(receipt),
                                                       enabled=self.action in (Action.ATTACK,Action.HARASS))
                    if receipt:
                        if target.is_hero:self.hero_attack_targets[u.handle]=target.handle
                        else:self.hero_attack_targets.pop(u.handle,None)
                    self.log('battle_ranged_focus_attack',clock=now,handle=u.handle,type=u.type,
                             target=target.handle,accepted=bool(receipt))
            elif self.due(('battle_ranged_regroup',u.handle),now,2):
                # Close the gap to a firing ally, without chasing the target
                # through the opposing army or firing at a different victim.
                anchor = min((v for v in ready if in_weapon_range(g,v,target)),key=lambda v:g.dist(u,v))
                if g.dist(u,anchor)>180:
                    dx,dy = target.x-anchor.x,target.y-anchor.y
                    length=max(1,hypot(dx,dy));dx,dy=dx/length,dy/length
                    flank=(squad.index(u)%3-1)*130
                    point=(anchor.x-100*dx-flank*dy,anchor.y-100*dy+flank*dx)
                    grid=g.map() if hasattr(g,'map') else None
                    route=g.path_distance((u.x,u.y),point)
                    if grid and grid.walkable(*point) and route is not None and route<=g.dist(u,point)+128:
                        self.go_raw([u],point,now)
                    else:
                        g.hold(u)
                else:
                    g.hold(u)
        return {u.handle for u in squad}

    def focus_ghouls(self, ghouls, foes, now):
        g = self.g
        for ghoul in ghouls:
            if ghoul.handle in self.shield_moves or now < self.cast_until.get(ghoul.handle, 0):
                continue
            heads = [e for e in foes if not e.is_hero and not is_structure(e) and can_engage(e)
                     and (stats:=unit_stats(e.type)) and any(w.range>=400 for w in stats.weapons)
                     and g.dist(ghoul,e)<750]
            troops = [e for e in foes if not e.is_hero and not is_structure(e)
                      and g.dist(ghoul, e) < 550]
            targets = heads or troops
            if not targets:
                continue
            target = min(targets, key=lambda e: (e.hp, g.dist(ghoul, e)))
            current = g.current_target(ghoul)
            if current and current.handle == target.handle:
                continue
            if self.due(('battle_ghoul_focus', ghoul.handle), now, 1.5):
                receipt = g.attack(ghoul, target)
                self.log('battle_ghoul_focus', clock=now, handle=ghoul.handle,
                         target=target.type, target_handle=target.handle,
                         accepted=bool(receipt), distance=round(g.dist(ghoul, target)))

    def attack_skeletons(self,army,foes,now):
        g=self.g;handled=set()
        # Melee skeletons may still need to close into weapon range.
        from .targeting import buffs, abilities
        targets=[e for e in foes if can_engage(e) and self.combat_progress.allowed(e,now)
                 and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)
                 and (not unit_stats(e.type) or not unit_stats(e.type).is_air or webbed_air(g,e))]
        for u in army:
            if u.type not in SKELETONS or u.hp<=0 or now<self.cast_until.get(u.handle,0):continue
            if u.handle in self.shopping or u.handle in self.battle_shop.reserved:continue
            current=g.current_target(u)
            choices=[e for e in targets if g.dist(u,e)<=1000 and
                     (in_weapon_range(g,u,e) or (not e.is_hero and
                      (route:=g.path_distance((u.x,u.y),(e.x,e.y))) is not None and route<=g.dist(u,e)+256))]
            if not choices:continue
            handled.add(u.handle)
            # Preserve an existing attack, including its approach and swing.
            if current and any(e.handle==current.handle for e in choices):continue
            target=min(choices,key=lambda e:(not in_weapon_range(g,u,e),g.dist(u,e),e.hp))
            if self.due(('skeleton_attack',u.handle),now,1.2):
                receipt=g.attack(u,target)
                self.log('battle_skeleton_attack',clock=now,handle=u.handle,type=u.type,
                         target=target.handle,accepted=bool(receipt))
        return handled

    def engage_battle(self, army, foes, now):
        """Shared contact advance and attack dispatch; no map-specific search."""
        from .controller import ground_attack_range
        # Support positioning owns both statues and destroyers; generic
        # reinforcement movement must not overwrite their supply/escape orders.
        army=[u for u in army if u.type not in {'ubsp','uobs'} and not (foes and u.handle in self.battle_dk_support)]
        if not army:return
        if not foes:
            self.stop_hero_chases(army,now)
            self.battle_focus_handles=set()
            return
        handled=self.attack_skeletons(army,foes,now)
        army=[u for u in army if u.handle not in handled]
        if not army:return
        fighters=[u for u in army if u.type!='uobs']
        ranged=[u for u in fighters if u.type in {'ucry','Ulic','Nbrn','Nngs'}] or fighters
        engaged=[u for u in ranged if any(in_weapon_range(self.g,u,e) for e in foes)]
        if ranged:
            front=min(engaged,key=lambda u:sum(self.g.dist(u,v) for v in engaged)) if engaged else min(ranged,key=lambda u:min(self.g.dist(u,e) for e in foes))
            point=(front.x,front.y)
            if not engaged:
                # Close on ordinary enemy units, while retaining the no-hero-chase rule.
                targets=[e for e in foes if not e.is_hero]
                if targets:
                    target=min(targets,key=lambda e:self.g.dist(front,e))
                    distance=self.g.dist(front,target)
                    step=min(300,max(0,distance-max(100,ground_attack_range(front.type)-50)))
                    if distance>0:point=(front.x+(target.x-front.x)*step/distance,front.y+(target.y-front.y)*step/distance)
            reinforcements=[]
            for u in army:
                if u.handle in self.battle_formation.pending:continue
                if now<self.cast_until.get(u.handle,0) or any(in_weapon_range(self.g,u,e) for e in foes):continue
                # DK and statues support the firing line without charging through it.
                margin=400 if u.type in {'Udea','uobs'} else 100 if engaged else 40
                if self.g.dist(u,point)>margin:reinforcements.append(u)
            if reinforcements:
                self.go(reinforcements,point,now,attack=False)
                if self.due('combat_reinforce',now,2):
                    self.log('combat_reinforce',clock=now,point=point,units=[dict(type=u.type,handle=u.handle) for u in reinforcements])
        self.fight(army,foes,now)
