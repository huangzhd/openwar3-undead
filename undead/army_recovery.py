"""Group health recovery, safe scroll shopping and observed production refunds."""
from math import ceil,hypot
from .equipment import can_receive
from .consumables import SCROLLS
from .retreat import clearance,escape_point
from .nc_combo import spell_data,DISABLED_CASTERS
from .targeting import enemy_player,in_weapon_range,buffs
from .structures import is_structure
from openwar3 import combat

class ArmyRecovery:
    def __init__(self,log):
        self.log=log;self.active=False;self.started=0;self.shop=None;self.reserve=False
        self.cancel_pending=None;self.cancel_attempts=0;self.shop_attempts={};self.retry={}
        self.buy_pending=None;self.statue_modes={};self.travel=None;self.heal_priority=False;self.held={};self.danger_ranges={};self.members=set()

    @staticmethod
    def injured(fiends):
        return (len(fiends)>=2 and sum(u.hp/u.hp_max<.45 for u in fiends)>=2
                and sum(u.hp for u in fiends)<.65*sum(u.hp_max for u in fiends))

    def next_volley(self,b,fiends,hostiles,now):
        """Visible threats over the next 3s, one normal attack plus a local AOE.

        This is a risk estimate, not an assertion that the enemy will cast.
        Flame Strike uses its first second of full damage, not its entire duration.
        """
        g=b.g;hits={u.handle:0 for u in fiends};details=[]
        # AZ 20261013-003657: the economy caches (attack, armor). Passing
        # that tuple to the SDK crashed the first real injured-army check.
        levels=b.economy.upgrade_levels
        tech=dict(zip(('Rura','Rucr'),levels)) if levels is not None else {}
        defense=combat.stats('ucry',tech=tech)
        players=[e for e in hostiles if enemy_player(g,e) and getattr(e,'has_detail',False)]
        for e in players:
            target=g.current_target(e)
            if target is None or target.handle not in hits or not in_weapon_range(g,e,target):continue
            stats=combat.stats(e.type,hero_level=getattr(e,'level',1))
            weapon=stats.weapon_vs(defense) if stats else None
            if weapon:hits[target.handle]+=weapon.dmg_avg*combat.damage_multiplier(weapon.attack_type,defense.armor_type)*combat.armor_factor(defense.armor)
        dying=[u.handle for u in fiends if u.hp<=hits[u.handle]]
        if len(dying)>=2:details.append(dict(spell='current_attacks',victims=dying,cooldown_unknown=False))
        rows,_=spell_data()
        for e in players:
            if not e.is_hero:continue
            for ability in g.abilities(e):
                code=ability['code'];level=ability.get('level',0)
                if code not in {'AOsh','AOws','AHfs'} or level not in (1,2,3):continue
                row=rows[code];suffix=str(level);cool=g.cooldown(e,code)
                casts=[ev for ev in b.hero_pressure.events if ev.handle==e.handle and ev.spell==code and 0<=now-ev.clock<=10]
                age=now-max(ev.clock for ev in casts) if casts else None
                in_flight=age is not None and age<1.5
                if cool is None and age is not None:cool=max(0,float(row['Cool'+suffix])-age)
                if not in_flight and (e.mana<float(row['Cost'+suffix]) or (cool is not None and cool>3)
                                     or buffs(g,e)&DISABLED_CASTERS):continue
                amount=float(row['DataA'+suffix])*combat.damage_multiplier('spells',defense.armor_type)
                if code=='AHfs':amount*=ceil(1/float(row['DataB'+suffix]))
                radius=float(row['Area'+suffix]);groups=[]
                if code=='AOws':groups=[[u for u in fiends if g.dist(e,u)<=radius]]
                else:
                    points=[(u.x,u.y) for u in fiends]
                    points += [((u.x+v.x)/2,(u.y+v.y)/2) for i,u in enumerate(fiends) for v in fiends[i+1:]]
                    for point in points:
                        if code=='AHfs':
                            if g.dist(e,point)<=float(row['Rng'+suffix]):groups.append([u for u in fiends if g.dist(u,point)<=radius])
                        else:
                            dx,dy=point[0]-e.x,point[1]-e.y;length=hypot(dx,dy)
                            if not length:continue
                            reach=float(row['DataC'+suffix]);group=[]
                            for u in fiends:
                                x,y=u.x-e.x,u.y-e.y;along=(x*dx+y*dy)/length;across=abs(x*dy-y*dx)/length
                                if 0<=along<=reach and across<=radius:group.append(u)
                            groups.append(group)
                best=max(([u.handle for u in group if u.hp<=amount+hits[u.handle]] for group in groups),key=len,default=[])
                if len(best)>=2:details.append(dict(caster=e.handle,spell=code,level=level,damage=amount,
                        victims=best,cooldown_unknown=cool is None,in_flight=in_flight))
        return details

    def threat_range(self,code):
        from .controller import ground_attack_range
        return max(ground_attack_range(code),self.danger_ranges.get(code,0))

    def safe_path(self,b,start,end,hostiles,combat=False):
        g=b.g
        if not combat and not b.creeping.safe_route(g,start,end):return None
        grid=g.map()
        if not grid or not grid.walkable(*end):return None
        length=g.path_distance(start,end)
        if length is None:return None
        path=g.walk_path(start,end)
        if not path or g.dist(path[-1],end)>128:return None
        before=clearance(start,hostiles,self.threat_range);a=start
        towers=[e for e in hostiles if is_structure(e) and self.threat_range(e.type)>0] if combat else []
        for z in path:
            count=max(1,ceil(g.dist(a,z)/96))
            if any(g.dist((a[0]+(z[0]-a[0])*i/count,a[1]+(z[1]-a[1])*i/count),e)
                   <min(self.threat_range(e.type)+100,g.dist(start,e))-8
                   for e in towers for i in range(1,count+1)):return None
            if any(clearance((a[0]+(z[0]-a[0])*i/count,a[1]+(z[1]-a[1])*i/count),hostiles,self.threat_range)
                   <min(150,before)-32 for i in range(1,count+1)):return None
            a=z
        return length

    def observe(self,b,army,hostiles,now,raid=False):
        g=b.g
        core=[u for u in army if u.type in {'Udea','Ulic','Nbrn','Nngs','ucry','uobs','ubsp'} and u.hp>0]
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core)) if core else None
        fiends=[u for u in core if u.type=='ucry' and g.dist(u,anchor)<=1200]
        heroes=[u for u in army if u.is_hero and u.hp>0]
        if self.active:
            fiends=[u for u in army if u.type=='ucry' and u.hp>0 and u.handle in self.members]
        self.heal_priority=self.injured(fiends)
        risk=self.next_volley(b,fiends,hostiles,now) if self.heal_priority else []
        # In a live fight, percentages alone never force this group retreat.
        # After disengagement, badly hurt survivors regroup rather than charging back.
        quiet=not any(enemy_player(g,e) and any(g.dist(e,u)<1200 for u in fiends) for e in hostiles)
        spent=bool(fiends) and sum(u.hp for u in fiends)<.35*sum(u.hp_max for u in fiends)
        if not self.active and b.attack_committed and self.heal_priority and (risk or quiet and spent):
            self.active=True;self.started=now;self.cancel_attempts=0;self.travel=None;self.held.clear();self.members={u.handle for u in fiends}
            self.log('army_recovery_started',clock=now,fiends=len(fiends),risk=risk,
                     reason='next_volley_losses' if risk else 'post_combat_low_health',
                     hp=sum(u.hp for u in fiends),hp_max=sum(u.hp_max for u in fiends))
        self.reserve=False;self.shop=None
        self.observe_refund(g,now)
        if not self.active:return
        rows,_=spell_data()
        for danger in risk:
            caster=g.unit(danger.get('caster')) if danger.get('caster') else None
            if caster:
                code=danger['spell'];suffix=str(danger['level']);row=rows[code]
                reach=float(row['Area'+suffix])
                if code=='AOsh':reach+=float(row['DataC'+suffix])
                elif code=='AHfs':reach+=float(row['Rng'+suffix])
                self.danger_ranges[caster.type]=max(reach,self.danger_ranges.get(caster.type,0))
        if not fiends or (sum(u.hp for u in fiends)>=.8*sum(u.hp_max for u in fiends)
                and all(u.hp>=.65*u.hp_max for u in fiends) and all(h.hp>=.6*h.hp_max for h in heroes)):
            self.active=False;self.danger_ranges.clear()
            self.log('army_recovery_ended',clock=now,reason='health_ready' if fiends else 'fiends_lost',
                     fiends=len(fiends),hp=sum(u.hp for u in fiends))
            b.formation.reset();b.formation_at=-100
            return
        if self.buy_pending:
            p=self.buy_pending
            if any(c in SCROLLS for h in heroes for c in g.inventory(h) or []):
                self.log('recovery_scroll_observed',clock=now,shop=p['shop']);self.buy_pending=None
            elif now-p['started']>=3:
                self.retry[p['shop']]=now+120;self.buy_pending=None
                self.log('recovery_scroll_unconfirmed',clock=now,shop=p['shop'])
        if raid or b.teleport or now<440 or not heroes:return
        bags=[g.inventory(h) for h in heroes]
        if any(bag is None for bag in bags) or any(c in SCROLLS for bag in bags for c in bag):return
        buyers=[h for h,bag in zip(heroes,bags) if h.type=='Ulic' and can_receive(h,bag,'shea') and h.hp>=.6*h.hp_max]
        if not buyers or b.economy.revival_pending(g):return
        shops=[u for u in g.units('all',{'ngme'}) if u.alive and u.visible_to(g.me())]
        if b.situation.tier==3:shops+=b.economy.ready(g,'utom')
        anchor=min(fiends,key=lambda u:sum(g.dist(u,v) for v in fiends));choices=[]
        for shop in shops:
            if now<self.retry.get(shop.handle,0) or self.shop_attempts.get((shop.handle,int(now//120)),0)>=3:continue
            point=(shop.x,shop.y)
            if clearance(point,hostiles,self.threat_range)<200:continue
            length=self.safe_path(b,(anchor.x,anchor.y),point,hostiles)
            if length is not None:choices.append((length,shop.handle,shop))
        if choices:
            length,_,self.shop=min(choices,key=lambda v:v[:2])
            if self.travel is None or self.travel['shop']!=self.shop.handle:
                self.travel=dict(shop=self.shop.handle,best=length,progress=now,started=now)
            elif length<self.travel['best']-80:self.travel.update(best=length,progress=now)
            if length>350 and (now-self.travel['progress']>25 or now-self.travel['started']>120):
                self.retry[self.shop.handle]=now+120;self.shop=None;self.travel=None
            # Do not freeze production forever if shopping cannot finish.
            self.reserve=bool(self.shop and now-self.started<90)
        self.reserve=self.reserve or bool(self.buy_pending or self.cancel_pending)

    def observe_refund(self,g,now):
        p=self.cancel_pending
        if not p:return
        building=g.unit(p['building']);prod=g.production(building) if building else None
        queue=tuple(prod.queue) if prod and prod.kind=='queue' else ()
        res=g.resources();refund=res['gold']-p['gold']-(res.get('gold_gathered',0)-p['gathered'])
        confirmed=building is not None and queue!=p['queue'] and refund>0
        if confirmed or now-p['started']>=3:
            self.log('recovery_refund_observed' if confirmed else 'recovery_refund_unconfirmed',clock=now,
                     building=p['building'],unit=p['unit'],refund_excluding_gathering=refund)
            self.cancel_pending=None

    def fund_scroll(self,b,now):
        g=b.g
        if self.cancel_pending or self.cancel_attempts>=2 or now-self.started>=90:return
        choices=[]
        for building,prod in g.all_production('me'):
            # cancel() removes the last slot: never cancel research/construction.
            if building.type not in {'usep','uslh'} or prod.kind!='queue' or not prod.queue:continue
            code=prod.queue[-1]
            if code not in {'ucry','ugho','uobs','uabo','umtw'}:continue
            progress=getattr(prod,'progress',0) if len(prod.queue)==1 else 0
            choices.append((progress,building.handle,building,prod,code))
        if not choices:return
        _,_,building,prod,code=min(choices,key=lambda r:r[:2]);res=g.resources()
        self.cancel_pending=dict(building=building.handle,unit=code,queue=tuple(prod.queue),
                                 gold=res['gold'],gathered=res.get('gold_gathered',0),started=now)
        self.cancel_attempts+=1;receipt=g.cancel(building)
        self.log('recovery_production_cancel_attempt',clock=now,building=building.type,unit=code,
                 gold=res['gold'],required=250,accepted=bool(receipt),attempt=self.cancel_attempts)

    def statues(self,b,now):
        g=b.g
        units=sorted(g.units('me',{'uobs'}),key=lambda u:u.handle)
        live={u.handle for u in units}
        self.statue_modes={h:s for h,s in self.statue_modes.items() if h in live}
        # A third (life) statue may remain beside another life statue when
        # the low-mana support transforms. Restore one of each supply role.
        modes={s['mode'] for s in self.statue_modes.values()}
        if len(units)>=2 and len(self.statue_modes)==len(units) and len(modes)==1:
            self.statue_modes.pop(units[-1].handle,None)
        for u in units:
            if now<b.cast_until.get(u.handle,0):continue
            previous=self.statue_modes.get(u.handle)
            assigned={s['mode'] for s in self.statue_modes.values()}
            mode=previous['mode'] if previous else ('life' if 'life' not in assigned else 'mana' if 'mana' not in assigned else 'life')
            single=not any(v.handle!=u.handle and g.dist(u,v)<=900 for v in units)
            state=self.statue_modes.get(u.handle)
            if state and state['mode']==mode and state.get('single')==single and (state['accepted'] or state['tries']>=3 or now-state['at']<3):continue
            tries=state['tries']+1 if state and state['mode']==mode and state.get('single')==single else 1
            # Retain automatic coverage during protected casts/retreat. Manual
            # B/C casts add the other resource; a lone local car always heals.
            auto='life' if single else mode
            off=g.cast(u,'replenishmanaoff' if auto=='life' else 'replenishlifeoff')
            on=g.cast(u,'replenishlifeon' if auto=='life' else 'replenishmanaon')
            r=bool(off) and bool(on)
            self.statue_modes[u.handle]=dict(mode=mode,single=single,tries=tries,at=now,accepted=bool(r))
            self.log('statue_recovery_mode_attempt',clock=now,handle=u.handle,mode=mode,manual=True,auto_life=auto=='life',accepted=bool(r))

    def tick(self,b,army,hostiles,now,pulls):
        if not self.active or b.situation.threatened or b.teleport:return False
        g=b.g;core=[u for u in army if u.type in {'Udea','Ulic','Nbrn','Nngs','ucry','uobs','ubsp'}]
        if not core:return False
        b.set_intent('整队恢复 · 雕像回血与群补');b.creeping.pause(now,'army_health_recovery')
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core))
        shop=self.shop;point=(shop.x,shop.y) if shop else (anchor.x,anchor.y)
        if not shop:
            statues=[u for u in core if u.type=='uobs' and clearance((u.x,u.y),hostiles,self.threat_range)>=200]
            if statues:
                statue=min(statues,key=lambda u:g.dist(u,anchor));point=(statue.x,statue.y)
            elif clearance(point,hostiles,self.threat_range)<200:
                point=escape_point(g,anchor,hostiles,self.threat_range,home=(b.home.x,b.home.y)) or point
        for u in core:
            if u.type=='uobs':
                if u.handle in pulls:b.go_raw([u],pulls[u.handle],now)
                continue # Dedicated supply positioning owns safe statues.
            if u.handle in b.shield_moves or now<b.cast_until.get(u.handle,0):continue
            if (u.handle in pulls and clearance((u.x,u.y),hostiles,self.threat_range)<200
                    and clearance(pulls[u.handle],hostiles,self.threat_range)>clearance((u.x,u.y),hostiles,self.threat_range)+80):
                b.go_raw([u],pulls[u.handle],now);continue
            start=(u.x,u.y)
            if g.dist(u,point)>180 and self.safe_path(b,start,point,hostiles) is not None:
                self.held.pop(u.handle,None);b.go_raw([u],point,now)
            elif clearance(start,hostiles,self.threat_range)<200:
                escape=escape_point(g,u,hostiles,self.threat_range,home=(b.home.x,b.home.y))
                if escape is not None:b.go_raw([u],escape,now)
            elif self.held.get(u.handle)!=point:
                if g.hold(u):self.held[u.handle]=point # One hold; do not repeatedly interrupt statue healing.
        if shop and not self.buy_pending and not b.battle_shop.pending:
            heroes=[h for h in core if h.is_hero]
            bags=[g.inventory(h) for h in heroes]
            if any(bag is None for bag in bags) or any(c in SCROLLS for bag in bags for c in bag):return True
            buyer=next((h for h,bag in zip(heroes,bags) if h.type=='Ulic' and can_receive(h,bag,'shea') and h.hp>=.6*h.hp_max
                        and g.dist(h,shop)<=280 and now>=b.cast_until.get(h.handle,0)),None)
            if buyer:
                if g.resources()['gold']<250:self.fund_scroll(b,now)
                elif b.battle_shop.transact(g,buyer,'shea','buy',now,b.cast_until,shop):
                    key=(shop.handle,int(now//120));self.shop_attempts[key]=self.shop_attempts.get(key,0)+1
                    self.buy_pending=dict(shop=shop.handle,started=now)
        return True
