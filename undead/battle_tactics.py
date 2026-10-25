"""Shared battle placement, rear dispellers and coordinated ranged fire.

Training and melee controllers both inherit this implementation. Arena lifecycle
and search waypoints belong to the training adapter, not this module.
"""
from math import hypot, cos, sin, pi
from .structures import is_structure
from .scouting import SKELETONS
from .targeting import can_engage, in_weapon_range, unit_stats, webbed_air, abilities, buffs, tc_pressure_target
from .nc_combo import spell_data, DISABLED_CASTERS
from .policy import Action
from .battle_spells import silence_key_hero
from .retreat import statue_rally_rank
from .battle_rejoin import rejoin_units
from .banshee_support import BansheeSupport
from .battle_detection import BattleDetection


class BattleTacticsMixin:
    wait_for_enemy_opening = False

    def init_battle_tactics(self):
        self.prep_points = {}
        self.prep_sent = {}
        self.ranged_focus = None
        self.battle_focus_handles = set()
        self.prebattle_since = None
        self.battle_dk_support = set()
        self.dk_battle_recovering=False
        self.dk_attack_target=None
        self.dk_enemy_peak_count=0
        self.dk_enemy_peak_hp=0
        self.skeleton_assaults={}
        self.battle_rejoin={}
        self.opening_nc_deadline=None
        self.opening_nc_waiting=False
        self.blight_waiting=False;self.blight_opened=False;self.blight_item=None
        self.backline_guards=set()
        self.backline_safe_output={}
        self.banshee_support=BansheeSupport(self.log)
        self.battle_detection=BattleDetection(self.log)
        self.battle_started=False
        self.battle_last_enemy=-100

    def battle_contact(self,army,foes,now):
        g=self.g;own={u.handle for u in army}
        contact=any(in_weapon_range(g,u,e) for u in army if u.type not in {'uobs','uban','ubsp'} for e in foes)
        contact=contact or any((t:=g.current_target(e)) is not None and t.handle in own and in_weapon_range(g,e,t) for e in foes)
        if contact:self.battle_started=True
        if foes:self.battle_last_enemy=now
        elif not self.wait_for_enemy_opening and now-self.battle_last_enemy>20:
            self.battle_started=False;self.prep_points.clear();self.prep_sent.clear()
            self.dk_enemy_peak_count=0;self.dk_enemy_peak_hp=0
        return self.battle_started

    def prepare_blight(self,army,foes,now,blocked=()):
        """Use an owned skull at the feet only for the training opening."""
        if not self.wait_for_enemy_opening:return
        g=self.g
        if self.teleport or self.action==Action.RETREAT:return
        state=self.blight_item
        if state and state.get('pending'):
            hero=g.unit(state['handle']);bag=g.inventory(hero) if hero else None
            if bag is not None and bag.count('skul')<state['count']:
                state['pending']=False;state['consumed']=True
                self.log('battle_skull_consumption_observed',clock=now,handle=state['handle'],
                         point=state['point'],terrain_confirmed=False)
            elif now-state['sent']>=3:state['pending']=False
        contact=any(in_weapon_range(g,u,e) for u in army if u.type not in {'uobs'} for e in foes)
        contact=contact or any((t:=g.current_target(e)) is not None and
                              any(t.handle==u.handle for u in army) and in_weapon_range(g,e,t) for e in foes)
        if contact:
            self.blight_opened=True;self.blight_waiting=False
            return
        if self.blight_opened or not hasattr(g,'inventory') or not hasattr(g,'use_item'):return
        if state is None:
            for hero in army:
                if not hero.is_hero or hero.hp<=0:continue
                bag=g.inventory(hero)
                if bag and 'skul' in bag:
                    state=self.blight_item=dict(handle=hero.handle,point=(hero.x,hero.y),count=bag.count('skul'),
                                               attempts=0,next_at=now,pending=False,consumed=False)
                    self.blight_waiting=self.wait_for_enemy_opening
                    break
        if not state or state['consumed'] or state['pending'] or state['attempts']>=3 or now<state['next_at']:return
        hero=g.unit(state['handle'])
        if (hero is None or hero.hp<=0 or hero.handle in blocked or hero.handle in self.shopping or
                hero.handle in self.battle_shop.reserved or now<self.cast_until.get(hero.handle,0) or
                buffs(g,hero)&DISABLED_CASTERS or g.cooldown(hero,'Ablp')!=0):return
        bag=g.inventory(hero)
        if not bag or 'skul' not in bag:return
        state.update(point=(hero.x,hero.y),count=bag.count('skul'),sent=now,next_at=now+3)
        state['attempts']+=1
        receipt=g.use_item(hero,bag.index('skul'),x=hero.x,y=hero.y)
        state['pending']=bool(receipt)
        if receipt:self.cast_until[hero.handle]=now+1.2
        self.log('battle_skull_attempt',clock=now,handle=hero.handle,point=state['point'],
                 attempt=state['attempts'],accepted=bool(receipt))

    def hold_blight_opening(self,army,now,blocked=()):
        if not self.wait_for_enemy_opening or not self.blight_waiting or self.teleport or self.action in (Action.RETREAT,Action.DEFEND):return False
        for u in army:
            if (u.handle in blocked or u.handle in self.shopping or u.handle in self.shield_moves or
                    u.handle in self.micro.pulling or now<self.cast_until.get(u.handle,0)):continue
            point=self.prep_points.get(u.handle)
            if point is not None and self.g.dist(u,point)>75 and now-self.prep_sent.get(u.handle,-100)<3:continue
            if self.due(('battle_opening_hold',u.handle),now,2):self.g.hold(u)
        return True

    def prepare_battle(self, now, army=None, target=None, blocked=(), limit=None, foes=()):
        """The same role layout for a countdown or a visible approaching fight."""
        g = self.g
        if army is None:army = [u for u in g.my_units() if u.alive and not is_structure(u)]
        if not army:
            return set()
        if self.battle_contact(army,foes,now):return set()
        support=self.banshee_support.tick(self,army,foes,now,True,blocked)
        blocked=set(blocked)|support|self.equipment.reserved
        self.prepare_blight(army,foes,now,blocked)
        if self.wait_for_enemy_opening and not self.blight_opened:self.blight_waiting=True
        target = target or self.enemy_main
        if target is None:return set()
        if not self.prep_points:
            center = (sum(u.x for u in army)/len(army), sum(u.y for u in army)/len(army))
            dx, dy = target[0]-center[0], target[1]-center[1]
            length = max(1, hypot(dx, dy))
            forward, side = (dx/length, dy/length), (-dy/length, dx/length)
            def point(front, flank):
                if self.blight_waiting:front=min(0,front)
                return (center[0]+front*forward[0]+flank*side[0],
                        center[1]+front*forward[1]+flank*side[1])
            roles = {'ugho': [(210, i*115) for i in range(-3, 4)],
                     'Udea': [(-280, 540)], 'Ulic': [(-140, -180)],
                     'Nbrn': [(-110, 180)], 'Nngs': [(-110, 180)],
                     'ubsp': [(-400, -100), (-400, 100)],
                     'uobs': [(-260, -100), (-260, 100)]}
            banshees=sorted((u for u in army if u.type=='uban'),key=lambda u:u.handle)
            roles['uban']=[(-260-100*(i//6),(i%6-(min(6,len(banshees)-6*(i//6))-1)/2)*130)
                           for i in range(len(banshees))]
            for u in army:
                if u.is_hero and u.type not in roles:roles[u.type]=[(-110,180)]
            fiends = [u for u in army if u.type == 'ucry']
            roles['ucry'] = [(90-260*(i//6), (i%6-(min(6, len(fiends)-6*(i//6))-1)/2)*240+120*((i//6)%2))
                             for i in range(len(fiends))]
            for kind, slots in roles.items():
                units = sorted((u for u in army if u.type == kind), key=lambda u: u.handle)
                for u, (front, flank) in zip(units, slots):
                    self.prep_points[u.handle] = point(front, flank)
            self.log('battle_prebattle_layout', clock=now,
                     points=[dict(handle=h, point=p) for h,p in self.prep_points.items()])
        grid = g.map()
        moving=set(support)
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
            if receipt and (u.type=='Udea' or self.blight_waiting):g.hold(u,queue='after')
            self.prep_sent[u.handle] = now
            if receipt:moving.add(u.handle)
            self.log('battle_prebattle_move_attempt', clock=now, handle=u.handle,
                     type=u.type, point=point, accepted=bool(receipt))
        if self.blight_waiting:self.hold_blight_opening(army,now,set(blocked)|moving)
        return moving

    def battle_actions(self, army, foes, now, pulls, blocked=(), search_point=None):
        """Shared precontact layout, rear safety, dispel and offensive spells."""
        g=self.g
        if not army:return
        started=self.battle_contact(army,foes,now)
        self.banshee_support.tick(self,army,foes,now,not started,set(pulls)|set(blocked))
        self.hero_pressure.select_strategy(g,army,foes,now)
        self.prepare_blight(army,foes,now,set(pulls)|set(blocked))
        if self.wait_for_enemy_opening and self.blight_waiting:
            self.prepare_battle(now,army,blocked=set(pulls)|set(blocked),foes=foes)
            if self.hold_blight_opening(army,now,set(pulls)|set(blocked)):return
        if foes:
            firing=any(in_weapon_range(g,u,e) for u in army if u.type not in {'uobs','ubsp'} for e in foes)
            own={u.handle for u in army}
            firing=firing or any((t:=g.current_target(e)) is not None and t.handle in own for e in foes)
            if firing:
                self.prebattle_since=now-5
            elif self.prebattle_since is None:
                self.prebattle_since=now;self.prep_points.clear();self.prep_sent.clear()
            if not started and not firing and now-self.prebattle_since<=4 and any(g.dist(u,e)<1100 for u in army for e in foes):
                target=min(foes,key=lambda e:min(g.dist(u,e) for u in army))
                moving=self.prepare_battle(now,army,(target.x,target.y),set(pulls)|set(blocked),limit=2,foes=foes)
                for handle in moving:pulls[handle]=self.prep_points[handle]
                if self.blight_waiting:return
        else:
            self.prebattle_since=None
            self.opening_nc_deadline=None;self.opening_nc_waiting=False
        self.rear_dk(army,foes,now,pulls,blocked)
        self.rear_backline(army,foes,now,pulls,blocked)
        self.rear_destroyers([u for u in army if u.handle not in blocked],foes,now,pulls,search_point)
        reserved=set(pulls)|set(blocked)
        if not self.teleport:
            silence_key_hero(self,army,foes,now,reserved,tc_only=True)
        # Dispel from current range before executing the retained retreat goal.
        dispel_blocked=(set(pulls)-{u.handle for u in army if u.type=='ubsp'})|set(blocked)|set(self.shield_moves)
        self.destroyer.tick(self,army,foes,now,dispel_blocked)
        if self.destroyer.escape_after:
            self.rear_destroyers([u for u in army if u.handle not in blocked],foes,now,pulls,search_point)
        if not self.teleport and self.action!=Action.RETREAT and self.hero_pressure.melee_orc(g,foes):
            self.heal_allies(army,now)
            self.frost_armor([u for u in army if u.handle not in blocked],foes,now)
        self.combat_spells(army,foes,now,(set(pulls)-self.battle_dk_support)|set(blocked))
        self.battle_detection.tick(self,army,g.enemies(),now,set(pulls)|set(blocked))
        self.battle_rod(army,now,(set(pulls)-self.battle_dk_support)|set(blocked)|set(self.shield_moves))
        self.rejoin_battle_units(army,foes,now,pulls,blocked)
        self.attack_dk(army,foes,now,set(pulls)|set(blocked))
        self.attack_destroyers(army,foes,now,set(pulls)|set(blocked)|set(self.shield_moves))

    def rejoin_battle_units(self,army,foes,now,pulls,blocked=()):
        return rejoin_units(self,army,foes,now,pulls,blocked)

    def battle_rod(self,army,now,blocked=()):
        """Use the DK's rod opportunistically after urgent spells, in both modes."""
        dk=next((u for u in army if u.type=='Udea' and u.hp>0),None)
        if not dk or dk.handle in blocked or not hasattr(self.g,'inventory'):return False
        bag=self.g.inventory(dk) or []
        return self.maintain_skeletons(dk,bag.index('rnec'),now) if 'rnec' in bag else False

    def rear_backline(self,army,foes,now,pulls,blocked=()):
        """Lich and Dark Ranger share early escape and stationary safe fire."""
        heroes=[u for u in army if u.type in {'Ulic','Nbrn'} and u.hp>0]
        self.backline_guards.intersection_update(u.handle for u in heroes)
        for hero in heroes:self._rear_backline_hero(hero,army,foes,now,pulls,blocked)

    def _rear_backline_hero(self,hero,army,foes,now,pulls,blocked=()):
        """Escape before protection expires, then fire without chasing."""
        from .controller import ground_attack_range
        g=self.g
        threats=[e for e in foes if can_engage(e) and ground_attack_range(e.type)>0]
        if not hero or not threats:
            self.backline_guards.discard(hero.handle)
            return
        if (self.teleport or self.action==Action.RETREAT or hero.handle in blocked or
                hero.handle in self.shopping or hero.handle in self.battle_shop.reserved):return
        dk=next((u for u in army if u.type=='Udea' and u.hp>0),None)
        no_mana=dk is None or dk.mana<75
        ratio=hero.hp/max(1,hero.hp_max)
        protected='Bvul' in buffs(g,hero)
        # Unknown buff age is not a fresh seven-second safety window.
        remaining=self.consumables.invulnerable_until.get(hero.handle,now)-now if protected else 0
        if not protected and not (no_mana and ratio<=.5) and hero.handle not in self.backline_guards:return
        clearance=lambda p:min(g.dist(p,e)-ground_attack_range(e.type) for e in threats)
        supports=[u for u in army if u.type=='uobs' and u.hp>0 and clearance((u.x,u.y))>=120]
        origin=(hero.x,hero.y);before=clearance(origin)
        grid=g.map() if hasattr(g,'map') else None
        choices=[]
        if before<140 and grid:
            for step in (160,320,520,760,1000):
                for i in range(24):
                    point=(hero.x+step*cos(i*pi/12),hero.y+step*sin(i*pi/12))
                    end=clearance(point)
                    if end<before+40:continue
                    samples=[(hero.x+(point[0]-hero.x)*j/12,hero.y+(point[1]-hero.y)*j/12) for j in range(1,13)]
                    if any(not grid.walkable(*p) or clearance(p)<min(before,140)-8 for p in samples):continue
                    route=g.path_distance(origin,point)
                    if route is None or route>step*1.25+64:continue
                    firing=any(g.dist(point,e)<=ground_attack_range(hero.type) for e in threats)
                    overlap,front,gap=statue_rally_rank(point,supports,threats)
                    choices.append(((end<140,-min(end,140),overlap,front,not firing,gap,route),point,route))
        best=min(choices,key=lambda row:row[0]) if choices else None
        # Include travel and command/tick latency; a slowed Lich leaves earlier.
        speed=getattr(hero,'move_speed',0) or 240
        if buffs(g,hero)&{'Bslo','BOsl','Bfro'}:speed=min(speed,120)
        lead=max(3.,(best[2] if best else 760)/max(1,speed)+1.)
        expiring=protected and remaining<=lead
        urgent=(no_mana and ratio<=.5) or expiring
        if hero.handle in self.backline_guards and not protected and ratio>=.65:
            self.backline_guards.discard(hero.handle)
        if hero.handle in self.backline_guards and not protected and dk and dk.mana>=75 and self.rescue_coil_ready(dk,now) and g.dist(dk,hero)<750:
            self.backline_guards.discard(hero.handle)
        if urgent and before<180:self.backline_guards.add(hero.handle)
        if hero.handle not in self.backline_guards:return
        # Keep all generic attack/advance paths from claiming the guarded hero.
        pulls[hero.handle]=best[1] if before<140 and best else origin
        self.micro.pulling.discard(hero.handle)
        if self.due(('hero_safety',hero.handle),now,2):
            self.log('battle_hero_safety',clock=now,handle=hero.handle,type=hero.type,dk_mana=dk.mana if dk else None,
                     hp_ratio=round(ratio,3),invulnerable=protected,remaining=round(remaining,2),
                     lead=round(lead,2),clearance=round(before),point=pulls[hero.handle])
        if before<140:return
        self.backline_safe_output[hero.handle]=now
        if now<self.cast_until.get(hero.handle,0):return
        targets=[e for e in threats if in_weapon_range(g,hero,e) and not buffs(g,e)&{'Bvul','BHds'}
                 and 'Avul' not in abilities(g,e) and self.combat_progress.allowed(e,now)]
        current=g.current_target(hero)
        if current and any(e.handle==current.handle for e in targets):return
        if self.due(('hero_safe_attack',hero.handle),now,.5):
            if targets:
                target=min(targets,key=lambda e:(e.handle!=self.ranged_focus,e.hp))
                receipt=g.attack(hero,target)
                self.combat_progress.attack_result(hero,target,now,bool(receipt),enabled=True)
                self.log('battle_hero_safe_attack',clock=now,handle=hero.handle,type=hero.type,target=target.handle,accepted=bool(receipt))
            else:g.hold(hero)

    def dk_cleanup_allowed(self,army,foes):
        """Only fair, local attrition opens melee; a fresh small encounter does not."""
        local=[e for e in foes if can_engage(e) and not is_structure(e) and
               any(self.g.dist(e,u)<=1400 for u in army if u.hp>0)]
        hp=sum(e.hp for e in local)
        self.dk_enemy_peak_count=max(self.dk_enemy_peak_count,len(local))
        self.dk_enemy_peak_hp=max(self.dk_enemy_peak_hp,hp)
        return (self.dk_enemy_peak_count>=4 and 0<len(local)<=2 and
                hp<=self.dk_enemy_peak_hp*.35 and
                not any(u.type in {'Ulic','Nbrn','ucry','ubsp'} and u.hp<=u.hp_max*.5 for u in army))

    def rear_dk(self,army,foes,now,pulls,blocked=()):
        """Stay within support range during the main fight; melee only in cleanup."""
        g=self.g
        self.battle_dk_support=set()
        dk=next((u for u in army if u.type=='Udea'),None)
        main=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
        if not dk or not foes or self.teleport:return
        if not main:main=[dk]
        if not all(hasattr(g,name) for name in ('move','walk_path','map')):return
        self.battle_dk_support.add(dk.handle)
        if dk.hp<=dk.hp_max*.5:self.dk_battle_recovering=True
        elif dk.hp>dk.hp_max*.6:self.dk_battle_recovering=False
        cleanup=self.dk_cleanup_allowed(army,foes)
        if not self.dk_battle_recovering and cleanup:
            if self.opening_nc_waiting and now<(self.opening_nc_deadline or 0) and dk.handle not in pulls and dk.handle not in blocked and now>=self.cast_until.get(dk.handle,0):
                if self.due('opening_nc_dk_hold',now,.5):g.hold(dk)
            return
        self.dk_attack_target=None
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
        if (behind>=140 and g.dist(dk,anchor)<=(740 if spacing else 600) and clearance(dk)>=100
                and (not spacing or spacing<=g.dist(dk,lich)<740)):
            pulls[dk.handle]=(dk.x,dk.y)
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
        candidates=[p for p in candidates if (not lich or g.dist(p,lich)<740)
                    and sum(g.dist(p,u)<740 for u in main)>=max(1,(len(main)+1)//2)]
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

    def attack_dk(self,army,foes,now,blocked=()):
        """Bounded melee focus after healing/spells, never overwrite escape."""
        g=self.g
        dk=next((u for u in army if u.type=='Udea' and can_engage(u)),None)
        if not dk:return
        self.battle_dk_support.add(dk.handle)
        if (dk.hp<=dk.hp_max*.5 or self.dk_battle_recovering or self.teleport or
                self.action==Action.RETREAT or self.army_recovery.active or self.opening_nc_waiting or
                dk.handle in set(blocked)|set(self.micro.pulling)|set(self.shield_moves)|set(self.shopping)|set(self.battle_shop.reserved) or
                now<self.cast_until.get(dk.handle,0) or buffs(g,dk)&DISABLED_CASTERS):return
        if not self.dk_cleanup_allowed(army,foes):
            self.dk_attack_target=None
            if g.current_target(dk) and self.due(('dk_stop_chase',dk.handle),now,1):g.hold(dk)
            return
        targets=[e for e in foes if can_engage(e) and getattr(e,'has_detail',False) and
                 not is_structure(e) and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e) and
                 (stats:=unit_stats(e.type)) and (not stats.is_air or webbed_air(g,e)) and
                 g.dist(dk,e)<=650 and (route:=g.path_distance((dk.x,dk.y),(e.x,e.y))) is not None and
                 route<=g.dist(dk,e)+150 and self.combat_progress.allowed(e,now)]
        # Do not abandon ranged heroes to finish a straggler, or walk into
        # another unit's firing lane merely because the army count is low.
        targets=[e for e in targets if all(g.dist(e,u)<=700 for u in army if u.type in {'Ulic','Nbrn'})
                 and not any(v.handle!=e.handle and in_weapon_range(g,v,e) for v in foes if can_engage(v))]
        focus=self.hero_pressure.orc_focus(g,army,foes,now)
        target=next((e for e in targets if focus and e.handle==focus.handle),None)
        target=target or min((e for e in targets if not e.is_hero),key=lambda e:self.hero_pressure.rank(g,army,e),default=None)
        self.dk_attack_target=target.handle if target else None
        current=g.current_target(dk)
        if target is None:
            if current and self.due(('dk_stop_chase',dk.handle),now,1):g.hold(dk)
            return
        if current and current.handle==target.handle:return
        if self.due(('battle_dk_attack',dk.handle),now,1.2):
            receipt=g.attack(dk,target)
            if receipt and target.is_hero:self.hero_attack_targets[dk.handle]=target.handle
            self.combat_progress.attack_result(dk,target,now,bool(receipt),enabled=True)
            self.log('battle_dk_attack',clock=now,target=target.handle,type=target.type,
                     hp=dk.hp,hp_max=dk.hp_max,distance=round(g.dist(dk,target)),accepted=bool(receipt))

    def rear_destroyers(self, army, foes, now, pulls, search_point):
        """Keep dispellers behind the ground force and outside AA fire."""
        g = self.g
        ground = [u for u in army if u.type not in {'ubsp', 'uobs','uban'}]
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
            if (foes and u.hp>u.hp_max*.45 and u.handle not in self.shield_moves
                    and not any(g.dist(u,e)<reach+140 for e,reach in threats)):
                self.destroyer.escape_after.discard(u.handle)
                # Healthy destroyers supply damage; normal backline spacing must not recall them.
                pulls.pop(u.handle,None);self.micro.pulling.discard(u.handle)
                continue
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
                current=g.current_target(u)
                if not current or not in_weapon_range(g,u,current):g.hold(u)
        return blocked

    def attack_destroyers(self,army,foes,now,blocked=()):
        """Dispel first, then support the shared melee focus until wounded."""
        self.hero_pressure.select_strategy(self.g,army,foes,now)
        if self.teleport or self.action==Action.RETREAT:return
        g=self.g
        focus=self.hero_pressure.orc_focus(g,army,foes,now)
        for u in army:
            if (u.type!='ubsp' or u.hp<=u.hp_max*.45 or u.handle in blocked or
                    u.handle in self.shopping or u.handle in self.battle_shop.reserved or
                    now<self.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS):continue
            targets=[e for e in foes if in_weapon_range(g,u,e) and can_engage(e)
                     and getattr(e,'has_detail',False) and not buffs(g,e)&{'Bvul','BHds'}
                     and 'Avul' not in abilities(g,e) and g.dist(u,e)<=900
                     and self.combat_progress.allowed(e,now)]
            threats=[(e,max((w.range for w in s.weapons if 'air' in w.targets),default=0))
                     for e in foes if (s:=unit_stats(e.type))]
            if any(reach and g.dist(u,e)<reach+140 for e,reach in threats):continue
            if not targets:continue
            target=next((e for e in targets if focus and e.handle==focus.handle),None)
            target=target or min(targets,key=lambda e:({'owyv':0,'ogru':1,'orai':2}.get(e.type,3),g.dist(u,e),e.hp))
            current=g.current_target(u)
            if current and current.handle==target.handle:continue
            if self.due(('battle_destroyer_attack',u.handle),now,1.2):
                receipt=g.attack(u,target)
                self.combat_progress.attack_result(u,target,now,bool(receipt),enabled=True)
                self.log('battle_destroyer_attack',clock=now,handle=u.handle,target=target.handle,
                         type=target.type,accepted=bool(receipt))

    def focus_ranged(self, army, foes, now):
        """Fiends, Lich and Dark Ranger share one persistent, reachable target."""
        army_first=self.hero_pressure.select_strategy(self.g,army,foes,now)=='army_first'
        if sum(u.type=='ucry' for u in army)<2 and not army_first and not self.hero_pressure.tc_sequence:
            return set()
        g = self.g
        squad = [u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'}]
        ready = [u for u in squad if now>=self.cast_until.get(u.handle,0)]
        candidates = [e for e in foes if can_engage(e) and self.combat_progress.allowed(e,now) and
                      (not self.hero_pressure.wyvern_priority or e.type=='owyv') and
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
                     reason='orc_melee_priority' if chief and target.type in {'ogru','orai'} else 'orc_hero_priority' if chief and target.is_hero else 'hero_finish' if target.is_hero else 'unit_focus',shooters=coverage(target))
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
                # Keep an available shot instead of moving a firing unit to
                # another shooter's preferred focus/formation slot.
                local=[e for e in candidates if in_weapon_range(g,u,e)]
                if current and any(e.handle==current.handle for e in local):continue
                if local:
                    alternate=min(local,key=lambda e:self.hero_pressure.rank(g,ready,e))
                    receipt=g.attack(u,alternate)
                    self.combat_progress.attack_result(u,alternate,now,bool(receipt),enabled=True)
                    continue
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
        g = self.g;handled=set()
        for ghoul in ghouls:
            if (ghoul.handle in self.shield_moves or ghoul.handle in self.micro.pulling or
                    ghoul.handle in self.shopping or ghoul.handle in self.battle_shop.reserved or
                    buffs(g,ghoul)&DISABLED_CASTERS or now < self.cast_until.get(ghoul.handle, 0)):
                continue
            heads = [e for e in foes if not e.is_hero and not is_structure(e) and can_engage(e)
                     and (stats:=unit_stats(e.type)) and any(w.range>=400 for w in stats.weapons)
                     and g.dist(ghoul,e)<750]
            troops = [e for e in foes if not e.is_hero and not is_structure(e)
                      and g.dist(ghoul, e) < 550]
            heads=[e for e in heads if e.type in {'ohun','otbk'}] or heads
            targets = heads or troops
            targets=[e for e in targets if can_engage(e) and not buffs(g,e)&{'Bvul','BHds'}
                     and 'Avul' not in abilities(g,e) and self.combat_progress.allowed(e,now) and
                     (in_weapon_range(g,ghoul,e) or
                      (route:=g.path_distance((ghoul.x,ghoul.y),(e.x,e.y))) is not None and route<=g.dist(ghoul,e)+200)]
            sequence=[e for e in foes if e.handle==self.hero_pressure.sequence_target and
                      can_engage(e) and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e) and
                      g.dist(ghoul,e)<=750 and (in_weapon_range(g,ghoul,e) or
                      (route:=g.path_distance((ghoul.x,ghoul.y),(e.x,e.y))) is not None and route<=g.dist(ghoul,e)+200)] if self.hero_pressure.tc_sequence else []
            opportunity=[e for e in foes if e.is_hero and e.handle==self.hero_pressure.target and
                         in_weapon_range(g,ghoul,e) and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)]
            targets=sequence or ([] if self.hero_pressure.tc_sequence and self.hero_pressure.tc_phase in {'tauren','key_heroes'} else opportunity or targets)
            if not targets:
                continue
            target = min(targets, key=lambda e: (e.handle!=self.hero_pressure.preferred,e.hp,g.dist(ghoul,e)))
            handled.add(ghoul.handle)
            current = g.current_target(ghoul)
            if current and current.handle == target.handle:
                continue
            if self.due(('battle_ghoul_focus', ghoul.handle), now, 1.5):
                receipt = g.attack(ghoul, target)
                if receipt and target.is_hero:self.hero_attack_targets[ghoul.handle]=target.handle
                self.log('battle_ghoul_focus', clock=now, handle=ghoul.handle,
                         target=target.type, target_handle=target.handle,
                         accepted=bool(receipt), distance=round(g.dist(ghoul, target)))
                self.combat_progress.attack_result(ghoul,target,now,bool(receipt),enabled=True)
        return handled

    def attack_skeletons(self,army,foes,now):
        g=self.g;handled=set()
        # One attack-ground order lets summons acquire targets and finish swings.
        # Keep it through transient target loss and regroup/retreat commands.
        targets=[e for e in foes if can_engage(e)
                 and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)
                 and (not unit_stats(e.type) or not unit_stats(e.type).is_air or webbed_air(g,e))]
        for u in army:
            if u.type not in SKELETONS or u.hp<=0:continue
            if u.handle in self.shopping or u.handle in self.battle_shop.reserved or u.handle in self.skeleton_scouts.assignments:continue
            state=self.skeleton_assaults.get(u.handle)
            if not targets and not state:continue
            current=g.current_target(u)
            if state and state['accepted']:
                if (current and can_engage(current) or g.dist(u,state['point'])>160 or now-state['at']<6):
                    handled.add(u.handle);continue
            choices=[e for e in targets if g.dist(u,e)<=1600 and
                     (route:=g.path_distance((u.x,u.y),(e.x,e.y))) is not None and route<=g.dist(u,e)+256]
            if not choices:
                if state and state['accepted']:self.skeleton_assaults.pop(u.handle,None)
                continue
            handled.add(u.handle)
            if now<self.cast_until.get(u.handle,0) or buffs(g,u)&DISABLED_CASTERS:continue
            target=min(choices,key=lambda e:g.dist(u,e));point=(target.x,target.y)
            if state and state['accepted'] and g.dist(point,state['point'])<350:continue
            if state and not state['accepted'] and (state['tries']>=3 or now-state['at']<2):continue
            receipt=g.attack_move(u,*point)
            tries=state['tries']+1 if state and not state['accepted'] else 1
            self.skeleton_assaults[u.handle]=dict(point=point,at=now,accepted=bool(receipt),tries=tries)
            self.log('battle_skeleton_attack_move',clock=now,handle=u.handle,type=u.type,
                     point=point,accepted=bool(receipt),attempt=tries)
        return handled

    def engage_battle(self, army, foes, now):
        """Shared contact advance and attack dispatch; no map-specific search."""
        from .controller import ground_attack_range
        if self.hold_blight_opening(army,now):return
        # Support positioning owns both statues and destroyers; generic
        # reinforcement movement must not overwrite their supply/escape orders.
        army=[u for u in army if u.type not in {'ubsp','uobs','uban'} and not (foes and u.handle in self.battle_dk_support)]
        if not army:return
        handled=self.attack_skeletons(army,foes,now)
        army=[u for u in army if u.handle not in handled]
        if not army:return
        if not foes:
            self.stop_hero_chases(army,now)
            self.battle_focus_handles=set()
            return
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
