"""Local pullback decisions; one damaged unit does not decide the army's retreat."""
from .scouting import SKELETONS
from math import hypot,cos,sin,atan2,pi
from .damage import DamageTrend
from .retreat import statue_rally_rank

COIL_MANA=75
DK_SUPPORT_DISTANCE=750
DK_REJOIN_DISTANCE=550

class Micro:
    def __init__(self,log):
        self.log=log
        self.hp={}
        self.damage=DamageTrend()
        self.hit={}
        self.pulling=set()
        self.previous=set()
        self.losses=[]
        self.dk_recovering=None
        self.dk_support=None

    def plan(self,army,hostiles,now,target_of,ground_distance,walkable,home,attack_range=lambda e:600,creeping=False,coil_ready=True,aggressive_training=False,aggressive_battle=False):
        # The same risk profile now applies to real player battles. Creeping
        # retains its separate health/aggro rules; training keeps its old API.
        aggressive = aggressive_training or aggressive_battle
        core=[u for u in army if u.type not in SKELETONS]
        self.damage.observe([u for u in core if u.is_hero],now)
        current={u.handle for u in core}
        self.losses.extend(now for _ in self.previous-current)
        self.losses=[t for t in self.losses if now-t<20]
        self.previous=current
        self.pulling &= current
        for u in core:
            if u.handle in self.hp and u.hp<self.hp[u.handle]-.5:
                self.hit[u.handle]=now
            self.hp[u.handle]=u.hp
        self.dk_support=None
        if not core or not hostiles:
            self.pulling.clear()
            return self.recover_dk(core,{},ground_distance)
        anchor=min(core,key=lambda u:sum(hypot(u.x-v.x,u.y-v.y) for v in core))
        targets={e.handle:target_of(e) for e in hostiles}
        moves={}
        dk=next((u for u in core if u.type=='Udea'),None)
        dk_has_mana=dk is not None and getattr(dk,'mana',0)>=COIL_MANA
        # Creeping preserves Coil for emergencies; wounded units must not wait for routine healing.
        coil_ready=coil_ready and not creeping
        def backline_urgent(u):
            ratio=u.hp/u.hp_max
            winning_trade=not creeping and ratio>=.35 and any(
                e.is_hero and getattr(e,'hp_max',0)>0 and e.hp/e.hp_max<min(.5,ratio-.1)
                and hypot(u.x-e.x,u.y-e.y)<750 for e in hostiles)
            return self.damage.urgent(u,window=(.75 if winning_trade else 1.25) if aggressive else 8)
        backline_hold=.28 if aggressive and not creeping else .7
        backline_exit=.22 if aggressive and not creeping else .45
        eligible={u.handle for u in core if (u.type=='Udea' and (not creeping or u.hp/u.hp_max<=.5 or u.handle in self.pulling or self.damage.urgent(u))) or
                  (u.type in {'Ulic','Nbrn'} and ((u.handle in self.pulling and u.hp/u.hp_max<backline_hold) or
                   (u.hp/u.hp_max<(.6 if creeping else backline_exit) and not (dk_has_mana and coil_ready and hypot(u.x-dk.x,u.y-dk.y)<750))
                   or backline_urgent(u))) or
                  (u.type=='ucry' and ((u.handle in self.pulling and u.hp/u.hp_max<.7) or
                   (u.hp/u.hp_max<.45 and not (dk_has_mana and coil_ready and hypot(u.x-dk.x,u.y-dk.y)<750)))) or
                  (u.type in {'Ucrl','uabo'} and (u.hp/u.hp_max<=.45 or u.handle in self.pulling or
                   u.is_hero and self.damage.urgent(u,window=3))) or
                  (u.type not in {'Udea','Ulic','Nbrn','ucry','Ucrl','uabo'} and (not dk_has_mana or u.type in {'Nngs','uobs','ubsp','uban'} or u.is_hero and self.damage.urgent(u)) and
                   (u.is_hero or u.hp/u.hp_max<.45 or u.handle in self.pulling))}
        # Player-battle statues have one owner for escape AND return to supply.
        # Generic persistent pullbacks otherwise keep the support controller blocked.
        if aggressive and not creeping:eligible -= {u.handle for u in core if u.type=='uobs'}
        self.pulling &= eligible
        for u in core:
            if u.handle not in eligible:continue
            attackers=[e for e in hostiles if targets[e.handle]==u.handle and
                       hypot(e.x-u.x,e.y-u.y)<(attack_range(e)+100 if creeping and u.type=='Udea'
                       and getattr(e,'owner',None)==12 else max(900,attack_range(e)+100))]
            fired=now-self.hit.get(u.handle,-100)<2 or bool(attackers)
            ratio=u.hp/u.hp_max
            if aggressive and not creeping and u.type=='Udea':
                should_pull=ratio<=.5 or self.damage.urgent(u,window=5)
                fired=fired or (ratio<=.5 and any(attack_range(e)>0 and
                    hypot(e.x-u.x,e.y-u.y)<=attack_range(e)+150 for e in hostiles))
            elif aggressive and not creeping and u.type in {'Ulic','Nbrn'}:
                should_pull=ratio<backline_exit or backline_urgent(u)
            else:
                should_pull=(u.type=='Udea' or ratio<.7 or len(attackers)>=2 or
                             u.is_hero and self.damage.urgent(u,window=8))
            if fired and should_pull:
                if u.handle not in self.pulling:
                    self.log('unit_pullback',clock=now,unit=u.type,handle=u.handle,hp=round(u.hp),attackers=len(attackers))
                self.pulling.add(u.handle)
                if u.type=='Udea':self.dk_recovering=u.handle
            if u.handle not in self.pulling: continue
            near=attackers or [e for e in hostiles if hypot(e.x-u.x,e.y-u.y)<max(900,attack_range(e)+100)]
            battle_dk=aggressive and not creeping and u.type=='Udea'
            if battle_dk:near=[e for e in hostiles if attack_range(e)>0]
            exposed=any(hypot(e.x-u.x,e.y-u.y)<attack_range(e)+100 for e in near)
            if not fired and not exposed and now-self.hit.get(u.handle,-100)>3:
                # Escaping fire is not healing. TH 104134's 244/525 lich
                # reengaged after a brief damage pause and died seconds later.
                # Keep vulnerable damage dealers out until health actually returns.
                # A half-health creeping DK returns to deal damage after aggro
                # is shed, rather than waiting for healing while the camp resets.
                # Critically injured DKs and vulnerable damage dealers still wait.
                supported_reentry=(not creeping and not aggressive and
                                   u.type in {'Ulic','Nbrn'} and ratio>=.45 and
                                   dk_has_mana and hypot(u.x-dk.x,u.y-dk.y)<750 and
                                   not self.damage.urgent(u,window=3))
                if ((u.type in {'ucry','Nngs'} and ratio<.7) or
                        (u.type in {'Ulic','Nbrn'} and ratio<backline_hold and
                         not (aggressive and not creeping) and not supported_reentry) or
                        creeping and u.type=='Udea' and ratio<.35 or
                        battle_dk and ratio<=.6) and any(hypot(e.x-v.x,e.y-v.y)<1200
                            for e in hostiles for v in (core if battle_dk else [anchor])):
                    moves[u.handle]=(u.x,u.y)
                    continue
                self.pulling.remove(u.handle)
                if creeping and u.type=='Udea':
                    self.log('creep_dk_reengage',clock=now,handle=u.handle,hp=round(u.hp),
                             reason='outside_weapon_range_without_recent_damage')
                continue
            if not near: continue
            if battle_dk:
                # Safety outranks the old 750 support leash. Score every enemy
                # weapon, including units not currently targeting the DK.
                clearance=lambda p:min(hypot(p[0]-e.x,p[1]-e.y)-attack_range(e) for e in near)
                supports=[v for v in core if v.type=='uobs' and v.hp>0 and clearance((v.x,v.y))>=120]
                before=clearance((u.x,u.y));choices=[]
                closest=min(near,key=lambda e:hypot(u.x-e.x,u.y-e.y)-attack_range(e))
                away=atan2(u.y-closest.y,u.x-closest.x)
                for step in (160,320,520,760):
                    for i in range(16):
                        angle=away+i*pi/8
                        point=(u.x+step*cos(angle),u.y+step*sin(angle))
                        end=clearance(point)
                        if end<=before+40:continue
                        samples=[(u.x+(point[0]-u.x)*j/12,u.y+(point[1]-u.y)*j/12) for j in range(1,13)]
                        if any(not walkable(*p) or clearance(p)<min(before,140)-8 for p in samples):continue
                        route=ground_distance((u.x,u.y),point)
                        if route is not None and route<=step*1.25+64:
                            choices.append(((end<140,-min(end,140),*statue_rally_rank(point,supports,near),route),point))
                moves[u.handle]=min(choices,key=lambda p:p[0])[1] if choices else (u.x,u.y)
                continue
            ex=sum(e.x for e in near)/len(near);ey=sum(e.y for e in near)/len(near)
            angle=atan2(anchor.y-ey,anchor.x-ex)
            support=[v for v in core if v.handle!=u.handle and v.handle not in self.pulling
                     and hypot(v.x-u.x,v.y-u.y)<700]
            back=min(support,key=lambda v:hypot(v.x-home[0],v.y-home[1])) if support else anchor
            companions=[v for v in core if v.handle!=u.handle and v.handle not in self.pulling]
            main=min(companions,key=lambda v:sum(hypot(v.x-w.x,v.y-w.y) for w in companions)) if companions else None
            gap=ground_distance((u.x,u.y),(main.x,main.y)) if main else None
            candidates=[]
            for offset in (0,pi/4,-pi/4,pi/2,-pi/2):
                candidates.append((back.x+220*cos(angle+offset),back.y+220*sin(angle+offset)))
            # A distant reinforcement or an obstructed support point must not cancel escape.
            away=atan2(u.y-ey,u.x-ex)
            escape_step=min(900,max(320,max(attack_range(e)+120-hypot(e.x-u.x,e.y-u.y) for e in near)))
            for step in (escape_step,320,160):
                for offset in (0,pi/4,-pi/4,pi/2,-pi/2):
                    candidates.append((u.x+step*cos(away+offset),u.y+step*sin(away+offset)))
            # Include lateral/toward-support escapes instead of only fleeing the pursuer.
            if main and u.type=='Udea':
                toward=atan2(main.y-u.y,main.x-u.x)
                candidates += [(u.x+step*cos(toward+offset),u.y+step*sin(toward+offset))
                               for step in (320,160) for offset in (0,pi/4,-pi/4)]
            danger=min(hypot(u.x-e.x,u.y-e.y) for e in near)
            # Prefer a reachable point outside weapon range; partial escape is the fallback.
            supports=[v for v in core if u.is_hero and v.type=='uobs' and v.hp>0 and
                      min(hypot(v.x-e.x,v.y-e.y)-attack_range(e) for e in near)>=120]
            candidates.sort(key=lambda p:(min(hypot(p[0]-e.x,p[1]-e.y)-attack_range(e) for e in near)<100,
                                          *statue_rally_rank(p,supports,near)))
            for point in candidates:
                if min(hypot(point[0]-e.x,point[1]-e.y) for e in near)<=danger+40:continue
                if not walkable(*point): continue
                if supports:
                    before=min(hypot(u.x-e.x,u.y-e.y)-attack_range(e) for e in near)
                    samples=[(u.x+(point[0]-u.x)*j/12,u.y+(point[1]-u.y)*j/12) for j in range(1,13)]
                    if any(not walkable(*p) or min(hypot(p[0]-e.x,p[1]-e.y)-attack_range(e) for e in near)<min(before,100)-8 for p in samples):continue
                if main and u.type=='Udea':
                    support_route=ground_distance(point,(main.x,main.y))
                    if support_route is None:
                        # Coarse path grids can miss the ally's cell. Only allow a
                        # locally reachable escape toward it, and request escort below.
                        if hypot(point[0]-main.x,point[1]-main.y)>=hypot(u.x-main.x,u.y-main.y)-40:continue
                    elif support_route>DK_SUPPORT_DISTANCE and (gap is None or support_route>=gap-40):continue
                route=ground_distance((u.x,u.y),point)
                if route is not None and route<1100:
                    moves[u.handle]=point
                    break
            if u.type=='Udea' and main and u.handle not in moves and gap is not None and gap>DK_SUPPORT_DISTANCE:
                # A pursuer between DK and the army can make every strict "away"
                # step invalid. Close toward support rather than freeze under fire.
                reconnect=[]
                for point in candidates:
                    if not walkable(*point):continue
                    route=ground_distance((u.x,u.y),point)
                    remaining=ground_distance(point,(main.x,main.y))
                    if route is not None and 40<route<600 and remaining is not None and remaining<gap-80:
                        clearance=min(hypot(point[0]-e.x,point[1]-e.y)-attack_range(e) for e in near)
                        reconnect.append((clearance,point))
                if reconnect:moves[u.handle]=max(reconnect,key=lambda pair:pair[0])[1]
        # Keep blocked pullbacks out of strategic attack orders.
        for u in core:
            if u.type!='Udea' and u.handle in self.pulling:moves.setdefault(u.handle,(u.x,u.y))
        return self.recover_dk(core,moves,ground_distance)

    def recover_dk(self,core,moves,ground_distance):
        """Keep a pulling DK in support range and retain rejoin orders after danger ends."""
        dk=next((u for u in core if u.handle==self.dk_recovering),None)
        companions=[u for u in core if u is not dk and u.handle not in self.pulling]
        if dk is None:
            self.dk_recovering=None
            return moves
        if not companions:return moves
        main=min(companions,key=lambda u:sum(hypot(u.x-v.x,u.y-v.y) for v in companions))
        gap=ground_distance((dk.x,dk.y),(main.x,main.y))
        pulling=dk.handle in self.pulling
        if not pulling and gap is not None and gap<=DK_REJOIN_DISTANCE:
            self.dk_recovering=None
            return moves
        blocked=pulling and dk.handle not in moves
        if not pulling:
            # A real ground order keeps following the main body even after hostiles disappear.
            moves[dk.handle]=(main.x,main.y) if gap is not None else (dk.x,dk.y)
        elif blocked:
            # Do not let strategic attack/formation orders overwrite a failed local escape.
            moves[dk.handle]=(dk.x,dk.y)
        if blocked or gap is None or gap>DK_SUPPORT_DISTANCE:
            self.dk_support=dict(handle=dk.handle,point=moves.get(dk.handle,(dk.x,dk.y)),
                                 gap=gap,reason='blocked_escape' if blocked else 'separated')
            if not pulling:self.dk_support['point']=(dk.x,dk.y)
        return moves
