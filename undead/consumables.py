"""Conservative consumables using own inventories and fair nearby threats."""
from .equipment import can_receive,BLUE_POTIONS,HEALTH_POTIONS,HEALING_SCROLLS,Equipment,scroll_priority
from .targeting import enemy_player,can_engage,in_weapon_range,unit_stats
from .coil import ready as coil_ready,level as coil_level,heal_eligible
from .nc_combo import DISABLED_CASTERS
from .structures import is_structure

# Pinned installation AbilityData.slk: ability, heal, mana, radius, buff.
ITEMS={
    'phea':('AIh1',250,0,0,None), 'pghe':('AIh2',500,0,0,None),
    'pman':('AIm1',0,150,0,None), 'pgma':('AIm2',0,300,0,None),
    # LR 20261012-145656: DK kept mnst while unable to cast Coil.
    # Local ItemData/AbilityData: active AIm2 restores 300, like pgma.
    'mnst':('AIm2',0,300,0,None),
    'pres':('AIre',500,200,0,None),
    'pnvu':('AIvu',0,0,0,'Bvul'), 'pnvl':('AIvl',0,0,0,'Bvul'),
    'shea':('AIha',150,0,600,None), 'sres':('AIra',300,150,600,None),
    'spro':('AIda',0,0,600,'Bdef'), 'sror':('AIrr',0,0,500,'Broa'),
}
REGEN={f'rej{i}':(f'AIp{i}',hp,mp,area,'BIrg') for i,hp,mp,area in
       [(1,100,25,0),(2,150,50,0),(3,200,75,0),(4,400,125,0),(5,250,100,600),(6,450,150,600)]}
REGEN['envl']=REGEN['rej3']
ITEMS.update(REGEN)
ITEMS['fgsk']=('AIfs',0,0,0,None)
SCROLLS=HEALING_SCROLLS
ORGANIC={'Udea','Ulic','Nbrn','Nngs','Ucrl','uabo','ucry','ugho','ubsp','uban'}
ITEM_DISABLED={'BOhx','Bply','BPse','BPSE','BSTN','Bstn','BUsl','Bcyc'}
# Pinned AbilityData.slk, HeroDur1. Timers start at the attempt, only after
# observing Bvul; a receipt or item disappearance alone never grants safety.
INVUL_DURATION={'pnvu':15.,'pnvl':7.}

class Consumables:
    def __init__(self,log):
        self.log=log;self.pending={};self.attempts={};self.retry={};self.group_until=0;self.buff_until={}
        self.invulnerable_until={}
        self.emergency_scroll_at={}
        self.coverage_after={}
        self.hp_history={};self.aoe_cooldowns={};self.aoe_casts=[];self.aoe_used=-100

    def observe_burst(self,g,army,hostiles,now):
        """Visible cooldown transitions plus own HP loss, never hidden spell state."""
        live={u.handle for u in army if u.hp>0}
        self.hp_history={h:rows for h,rows in self.hp_history.items() if h in live}
        for u in army:
            if u.hp<=0:continue
            rows=[r for r in self.hp_history.get(u.handle,[]) if now-r[0]<=5]
            rows.append((now,u.hp));self.hp_history[u.handle]=rows
        observed={}
        for e in hostiles:
            if not can_engage(e) or not getattr(e,'has_detail',False):continue
            for a in getattr(g,'abilities',lambda _:[])(e):
                code=a.get('code');cd=a.get('cooldown')
                if code not in {'AOws','AOcl','AOsh','AHfs','AHbz','ANbf','AUfn'} or not a.get('level',0) or cd is None:continue
                key=(e.handle,code);previous=self.aoe_cooldowns.get(key)
                if previous and now-previous[0]<=1.5 and cd>previous[1]+.5:
                    self.aoe_casts.append((now,code,e.handle))
                    self.log('enemy_aoe_cooldown_started',clock=now,handle=e.handle,ability=code,damage_confirmed=False)
                observed[key]=(now,cd)
        self.aoe_cooldowns=observed
        self.aoe_casts=[r for r in self.aoe_casts if now-r[0]<=4 and r[0]>self.aoe_used]

    def burst_scroll(self,g,targets,hostiles,now,heal):
        if not self.aoe_casts:return False,[]
        nearby={e.handle for e in hostiles if any(g.dist(e,u)<=1100 for u in targets)}
        casts=[r for r in self.aoe_casts if r[2] in nearby]
        if not casts or now-max(r[0] for r in casts)>2:return False,[]
        codes={r[1] for r in casts}
        types={e.type for e in hostiles if e.handle in nearby}
        # This common Orc combo is one round: wait for both casts unless the
        # ordinary severe-injury/emergency rule has already become necessary.
        if {'Otch','Ofar'}<=types and not {'AOws','AOcl'}<=codes:return False,[]
        hurt=[u for u in targets if max((hp for t,hp in self.hp_history.get(u.handle,[]) if now-t<=5),default=u.hp)-u.hp>=40
              and u.hp_max-u.hp>=heal*.8]
        useful=sum(min(heal,u.hp_max-u.hp) for u in hurt)
        return len(hurt)>=3 and useful>=heal*3*.85,sorted(codes)

    def scroll_emergency(self,g,victim,army,hostiles,now,cast_until,blocked,urgent,pending_heals=()):
        """Last resort for an endangered hero with no timely personal/Coil rescue."""
        if not victim.is_hero or victim.hp<=0 or victim.hp_max<=0:return False
        ratio=victim.hp/victim.hp_max
        effects=set(g.buffs(victim))
        if 'Bvul' in effects or 'BHds' in effects:return False
        danger=any(can_engage(e) and g.dist(e,victim)<700 for e in hostiles)
        if not danger or not (ratio<=.25 or victim.handle in urgent and ratio<=.35):return False
        defense=unit_stats(victim.type)
        dps=sum(s.dps_vs(defense) for e in hostiles if defense and
                (t:=getattr(g,'current_target',lambda _:None)(e)) is not None and t.handle==victim.handle
                and in_weapon_range(g,e,victim) and (s:=unit_stats(e.type)))
        lifetime=victim.hp/dps if dps else float('inf')
        pending=self.pending.get(victim.handle)
        if pending and pending.get('accepted') and now-pending['started']<.3:
            row=ITEMS[pending['code']]
            if not row[3] and (row[1] or row[4]=='Bvul') and lifetime>.3:return False
        if any(p['target']==victim.handle and 0<=now-p['started']<.8 and
               lifetime>.8-(now-p['started']) for p in pending_heals):return False
        # Only an executable item is an alternative, not merely owning one.
        if victim.handle not in blocked and not effects&ITEM_DISABLED:
            bag=g.inventory(victim) or []
            for slot,code in enumerate(bag):
                row=ITEMS.get(code)
                if not row or row[3] or not (row[1]>0 and code not in REGEN or row[4]=='Bvul'):continue
                if now<cast_until.get(victim.handle,0) and row[4]!='Bvul':continue
                addrs=getattr(victim,'item_addrs',()) or ()
                identity=addrs[slot] if len(addrs)>slot and addrs[slot] else (slot,code)
                key=(victim.handle,identity)
                if (g.cooldown(victim,row[0])==0 and now>=self.retry.get(key,0) and
                        (row[4]=='Bvul' or self.attempts.get(key,0)<3)):return False
        if victim.type in {'Ulic','Nbrn'}:
            dk=next((u for u in army if u.type=='Udea' and u.hp>0),None)
            cover=bool(dk and dk.mana>=75 and dk.handle not in blocked and now>=cast_until.get(dk.handle,0)
                       and g.dist(dk,victim)<750 and not set(g.buffs(dk))&DISABLED_CASTERS
                       and (hasattr(g,'abilities') or hasattr(g,'coil_level')) and coil_level(g,dk)>0
                       and coil_ready(g,dk,now))
            if cover:
                if lifetime>.7+g.dist(dk,victim)/1100:return False
        return True

    def observe(self,g,now):
        for handle in list(self.invulnerable_until):
            hero=g.unit(handle)
            if not hero or 'Bvul' not in g.buffs(hero):self.invulnerable_until.pop(handle,None)
        for handle,p in list(self.pending.items()):
            hero=g.unit(handle);bag=g.inventory(hero) if hero else None
            ability,heal,mana,radius,buff=ITEMS[p['code']]
            consumed=bag is not None and bag.count(p['code'])<p['count']
            if consumed:
                # A later item may reuse the same engine address or inventory slot.
                self.attempts.pop(p['key'],None);self.retry.pop(p['key'],None)
            gains=[];buffed=[]
            for h,(hp,mp) in p['before'].items():
                u=g.unit(h)
                if u:
                    dh=u.hp-hp;dm=getattr(u,'mana',0)-mp
                    if (heal and dh>=50) or (mana and dm>=40):
                        gains.append(dict(handle=h,hp_gain=round(dh,2),mana_gain=round(dm,2)))
                    if buff and buff in g.buffs(u):buffed.append(h)
            # Receipt alone, passive regeneration, and disappearance alone are not effects.
            summoned=[]
            if p['code']=='fgsk':
                summoned=[u.handle for u in g.units('me',{'nsce','nsca'}) if u.handle not in p['summons_before']]
            if (consumed and gains) or buffed or (consumed and summoned):
                if buff=='Bvul' and handle in buffed:
                    self.invulnerable_until[handle]=p['started']+INVUL_DURATION[p['code']]
                self.log('consumable_effect_observed',clock=now,hero=p['hero'],code=p['code'],
                         consumed=consumed,gains=gains,buffed=buffed,summoned=summoned)
                self.pending.pop(handle)
            elif now-p['started']>=(.25 if buff=='Bvul' and not consumed else 3):
                self.log('consumable_effect_unconfirmed',clock=now,hero=p['hero'],code=p['code'],consumed=consumed)
                self.pending.pop(handle)

    def tick(self,g,army,hostiles,now,cast_until,blocked=(),coil_needed=False,attacking=False,urgent=(),preparing=False,pending_heals=(),controller=None):
        self.observe(g,now)
        self.observe_burst(g,army,hostiles,now)
        # Most injured hero first; only one area scroll per observation window.
        for hero in sorted((u for u in army if u.is_hero),key=lambda u:u.hp/max(1,u.hp_max)):
            if hero.hp<=0 or not getattr(hero,'alive',True) or hero.handle in blocked or hero.handle in self.pending:continue
            locked=now<cast_until.get(hero.handle,0)
            bag=g.inventory(hero)
            if not bag:continue
            candidates=[]
            threat=any(g.dist(e,hero)<700 for e in hostiles)
            ratio=hero.hp/max(1,hero.hp_max)
            buffs=set(g.buffs(hero)) if any(c in ITEMS for c in bag) else set()
            dk=next((u for u in army if u.type=='Udea'),None)
            coil_cover=bool(heal_eligible(hero) and dk and getattr(dk,'alive',True) and dk.hp>0 and dk.mana>=75
                and dk.handle not in blocked and now>=cast_until.get(dk.handle,0)
                and g.dist(dk,hero)<750 and hasattr(g,'buffs') and not set(g.buffs(dk))&DISABLED_CASTERS
                and (hasattr(g,'coil_level') or hasattr(g,'abilities')) and coil_level(g,dk)>0
                and coil_ready(g,dk,now)) if hero.type=='Ulic' else False
            focused=sum((t:=getattr(g,'current_target',lambda e:None)(e)) is not None
                        and t.handle==hero.handle and g.dist(e,hero)<900 for e in hostiles)>=2
            emergency=hero.handle in urgent or ratio<=.25 or (focused and ratio<=.5)
            rescue_targets=[u for u in army if u.is_hero and g.dist(hero,u)<=600 and
                            self.scroll_emergency(g,u,army,hostiles,now,cast_until,blocked,urgent,pending_heals)] if any(c in SCROLLS for c in bag) else []
            rescue_targets=[u for u in rescue_targets if now-self.emergency_scroll_at.get(u.handle,-100)>=.8]
            scroll_notes={}
            # Lich's 30% gate also applies under focus, urgent flags and TC approach.
            invul_hp=(ratio<=.30) if hero.type=='Ulic' else (ratio<=.35 or emergency)
            invul_needed=threat and invul_hp and 'Bvul' not in buffs
            # Latest policy: a genuinely available Coil takes priority, even
            # at critical HP. Otherwise keep requesting invulnerability through
            # stun; an accepted item order is not evidence that it was used.
            if hero.type=='Ulic' and coil_cover:invul_needed=False
            for slot,code in enumerate(bag):
                if code not in ITEMS:continue
                if code in SCROLLS and buffs&ITEM_DISABLED:continue
                if code=='sror' and (hero.type!='Ulic' or buffs&ITEM_DISABLED or
                    not any(enemy_player(g,e) and can_engage(e) and not is_structure(e) for e in hostiles)):continue
                ability,heal,mana,radius,buff=ITEMS[code]
                if locked and not (buff=='Bvul' and invul_needed or code in SCROLLS and rescue_targets or hero.type=='Ulic' and code in HEALTH_POTIONS and 'Bvul' in buffs):continue
                if hero.type=='Ulic' and code in HEALTH_POTIONS and coil_cover:continue
                if g.cooldown(hero,ability)!=0:continue # unknown is not ready
                addrs=getattr(hero,'item_addrs',()) or ()
                identity=addrs[slot] if len(addrs)>slot and addrs[slot] else (slot,code)
                key=(hero.handle,identity)
                if not (code in SCROLLS and rescue_targets) and ((buff!='Bvul' and self.attempts.get(key,0)>=3) or now<self.retry.get(key,0)):continue
                targets=[u for u in army if u.type in ORGANIC and u.hp>0 and g.dist(u,hero)<=radius] if radius else [hero]
                if code=='fgsk':
                    if ratio<.35 or not any(enemy_player(g,e) and can_engage(e) and g.dist(e,hero)<700 for e in hostiles):continue
                    priority=6
                elif code in REGEN:
                    if threat or buffs & {'BIrg','BIrl','BIrm'}:continue
                    hp_need=sum(min(heal,max(0,u.hp_max-u.hp)) for u in targets)
                    mp_need=sum(min(mana,max(0,getattr(u,'mana_max',0)-getattr(u,'mana',0))) for u in targets)
                    if hp_need<heal*.6 and mp_need<mana*.6:continue
                    priority=3
                elif buff=='Bvul':
                    if not invul_needed:continue
                    priority=0
                elif radius:
                    if buff:
                        if now<self.buff_until.get(buff,0):continue
                        targets=[u for u in targets if buff not in g.buffs(u)]
                        if code=='sror':
                            fiends=[u for u in army if u.type=='ucry' and u.hp>0]
                            if not targets or any(g.dist(u,hero)>radius for u in fiends):continue
                        elif not threat or len(targets)<3:continue
                        priority=5
                    else:
                        group_emergency=bool(rescue_targets)
                        if now<self.group_until and not group_emergency:continue
                        injured=[u for u in targets if u.hp<=u.hp_max*.5]
                        useful=sum(min(heal,max(0,u.hp_max-u.hp)) for u in injured)
                        required=max(3,(len(targets)+1)//2)
                        after_aoe,aoe_codes=self.burst_scroll(g,targets,hostiles,now,heal)
                        # Several pressured units must not die while we wait
                        # for untouched units to cross a majority threshold.
                        wounded=[u for u in targets if u.hp<=u.hp_max*.6 and u.hp_max-u.hp>=heal*.85]
                        pressured=[u for u in wounded if any((t:=getattr(g,'current_target',lambda _:None)(e)) is not None
                                   and t.handle==u.handle and in_weapon_range(g,e,u) for e in hostiles)]
                        recent=[u for u in targets if u.hp<=u.hp_max*.75 and u.hp_max-u.hp>=heal*.85
                                and max((hp for t,hp in self.hp_history.get(u.handle,[]) if now-t<=5 and t>=self.aoe_used),default=u.hp)-u.hp>=40]
                        sustained=len(recent)>=3 and sum(e.type=='owyv' and g.dist(hero,e)<1100 for e in hostiles)>=2
                        timely=len(wounded)>=3 and len(pressured)>=2 or sustained
                        if not group_emergency and not (after_aoe or timely or len(injured)>=required and useful>=heal*len(injured)*.85):
                            # Reposition a ready carrier before scattered wounded units
                            # disappear from the local healing threshold altogether.
                            outside=[u for u in army if u.type in ORGANIC and 0<u.hp<=u.hp_max*.65
                                     and u.hp_max-u.hp>=heal*.85 and g.dist(hero,u)<950]
                            if controller is not None and len(outside)>=3:
                                from .stomp_response import improve_scroll_position
                                if improve_scroll_position(controller,hero,army,hostiles,now,radius,heal):
                                    candidates=[];break
                            continue
                        priority=-1 if group_emergency else 2
                        scroll_notes[slot]=dict(scroll_emergency=group_emergency,half_health_units=len(injured),
                            required_units=required,effective_healing=round(useful,1),
                            after_aoe=after_aoe,aoe_abilities=aoe_codes,pressured_units=len(pressured),recent_wounded=len(recent),
                            total_effective_healing=round(sum(min(heal,max(0,u.hp_max-u.hp)) for u in targets),1),
                            rescue_heroes=[u.handle for u in rescue_targets])
                else:
                    missing=hero.hp_max-hero.hp;mp=getattr(hero,'mana',0);missing_mp=getattr(hero,'mana_max',0)-mp
                    if heal and now<self.group_until and ratio>.25:continue
                    need_hp=heal and ratio<=.60 and missing>=min(heal*.6,300)
                    minimum={'Udea':75,'Ulic':125,'Nngs':120,'Nbrn':75}.get(hero.type,100)
                    need_mp=mana and mp<minimum and missing_mp>=mana*.65
                    if code in BLUE_POTIONS:
                        need_mp=hero.type=='Udea' and (mp<75 or (preparing and mp<150 and missing_mp>=min(mana,150)*.65))
                    if not (need_hp or need_mp):continue
                    priority=1 if need_hp else 4
                candidates.append((priority,slot,code,key,targets))
            if not candidates:continue
            _,slot,code,key,targets=min(candidates,key=lambda x:x[:2])
            if code in SCROLLS and controller is not None and not rescue_targets:
                from .stomp_response import improve_scroll_position
                if improve_scroll_position(controller,hero,army,hostiles,now,ITEMS[code][3],ITEMS[code][1]):continue
            before={u.handle:(u.hp,getattr(u,'mana',0)) for u in targets}
            count=bag.count(code)
            summons_before={u.handle for u in g.units('me',{'nsce','nsca'})} if code=='fgsk' else set()
            r=g.use_item(hero,slot)
            if code in SCROLLS:
                for u in rescue_targets:self.emergency_scroll_at[u.handle]=now
                self.aoe_used=now
            invulnerable=ITEMS[code][4]=='Bvul'
            self.attempts[key]=self.attempts.get(key,0)+1;self.retry[key]=now+(.25 if invulnerable else 4)
            # Protect even an uncertain receipt until fresh observation; never spam.
            cast_until[hero.handle]=max(cast_until.get(hero.handle,0),now+(2 if invulnerable else 1.2))
            if ITEMS[code][3]:
                if ITEMS[code][4]:self.buff_until[ITEMS[code][4]]=now+3
                else:self.group_until=now+3
            self.pending[hero.handle]=dict(code=code,key=key,hero=hero.type,count=count,started=now,before=before,accepted=bool(r),
                summons_before=summons_before)
            self.log('consumable_use_attempt',clock=now,hero=hero.type,handle=hero.handle,code=code,
                     hp=hero.hp,hp_max=hero.hp_max,accepted=bool(r),attempt=self.attempts[key],targets=[u.handle for u in targets],
                     eligible_units=[u.handle for u in army if u.hp>0 and u.type in ORGANIC] if ITEMS[code][3] else [hero.handle],
                     missed_units=[u.handle for u in army if u.hp>0 and u.type in ORGANIC and g.dist(u,hero)>ITEMS[code][3]] if ITEMS[code][3] else [],
                     buffs=sorted(buffs),emergency=emergency,overrode_cast_lock=locked,
                     focused=focused,coil_cover=coil_cover,controlled=bool(buffs&ITEM_DISABLED),**scroll_notes.get(slot,{}))

class ScrollSupply:
    def __init__(self,log):
        self.log=log;self.pending=None;self.next_at=0;self.attempts={};self.equipment=Equipment(log)

    def tick(self,g,heroes,shops,now,reserved_gold,cast_until,safe=True):
        bags={h.handle:g.inventory(h) for h in heroes}
        if any(b is None for b in bags.values()):return
        total=sum(sum(b.count(c) for c in SCROLLS) for b in bags.values())
        if self.pending:
            p=self.pending
            if total>p['total']:
                self.log('healing_scroll_purchase_confirmed',clock=now,total=total,
                         inventories=[dict(hero=h.type,bag=bags[h.handle]) for h in heroes])
                self.pending=None
            elif now-p['started']<3:return
            else:
                self.log('healing_scroll_purchase_unconfirmed',clock=now,shop=p['shop'])
                self.pending=None
        if not safe:return
        # Engine-selected buyers may receive a scroll on the wrong hero.
        # Use the same observed handoff policy as training and melee equipment.
        if self.equipment.tick(g,heroes,[],now,cast_until,True) or self.equipment.pending:return
        res=g.resources()
        if now<self.next_at or total>=3 or res.get('food_used',0)<50 or res.get('gold',0)-reserved_gold<500:return
        candidates=[h for h in heroes if not any(c in SCROLLS for c in bags[h.handle])
                    and can_receive(h,bags[h.handle],'shea') and now>=cast_until.get(h.handle,0) and h.hp/h.hp_max>.6]
        for h in sorted(candidates,key=lambda h:scroll_priority(h,bags[h.handle])):
            for shop in sorted(shops,key=lambda s:g.dist(s,h)):
                if g.dist(h,shop)>300:continue # optional purchase only when already at a safe shop
                nearby=[v for v in heroes if g.dist(v,shop)<900]
                if any(not can_receive(v,bags[v.handle],'shea') for v in nearby):continue
                # At most three attempts per stock regeneration interval, with fresh funds each time.
                key=(shop.handle,int(now//120))
                if self.attempts.get(key,0)>=3:continue
                r=g.buy(shop,'shea');self.attempts[key]=self.attempts.get(key,0)+1
                self.next_at=now+3;self.pending=dict(total=total,started=now,shop=shop.handle)
                self.log('healing_scroll_purchase_attempt',clock=now,hero=h.type,shop=shop.type,
                         accepted=bool(r),gold=res['gold'],reserved_gold=reserved_gold,total_before=total)
                return
