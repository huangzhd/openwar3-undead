"""Conservative consumables using own inventories and fair nearby threats."""
from .equipment import can_receive,BLUE_POTIONS,HEALTH_POTIONS,HEALING_SCROLLS,Equipment,scroll_priority
from .targeting import enemy_player,can_engage
from .coil import ready as coil_ready,level as coil_level,heal_eligible
from .nc_combo import DISABLED_CASTERS

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
ORGANIC={'Udea','Ulic','Nbrn','Nngs','ucry','ugho'}
ITEM_DISABLED={'BOhx','Bply','BPse','BPSE','BSTN','Bstn','BUsl','Bcyc'}

class Consumables:
    def __init__(self,log):
        self.log=log;self.pending={};self.attempts={};self.retry={};self.group_until=0;self.buff_until={}

    def observe(self,g,now):
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
                self.log('consumable_effect_observed',clock=now,hero=p['hero'],code=p['code'],
                         consumed=consumed,gains=gains,buffed=buffed,summoned=summoned)
                self.pending.pop(handle)
            elif now-p['started']>=(.25 if buff=='Bvul' and not consumed else 3):
                self.log('consumable_effect_unconfirmed',clock=now,hero=p['hero'],code=p['code'],consumed=consumed)
                self.pending.pop(handle)

    def tick(self,g,army,hostiles,now,cast_until,blocked=(),coil_needed=False,attacking=False,urgent=(),preparing=False):
        self.observe(g,now)
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
            # Lich's 30% gate also applies under focus, urgent flags and TC approach.
            invul_hp=(ratio<=.30) if hero.type=='Ulic' else (ratio<=.35 or emergency)
            invul_needed=threat and invul_hp and 'Bvul' not in buffs
            # Latest policy: a genuinely available Coil takes priority, even
            # at critical HP. Otherwise keep requesting invulnerability through
            # stun; an accepted item order is not evidence that it was used.
            if hero.type=='Ulic' and coil_cover:invul_needed=False
            for slot,code in enumerate(bag):
                if code not in ITEMS:continue
                if code=='sror' and (not attacking or not any(0<=getattr(e,'owner',12)<12 and g.dist(e,hero)<700 for e in hostiles)):continue
                ability,heal,mana,radius,buff=ITEMS[code]
                if locked and not (buff=='Bvul' and invul_needed or hero.type=='Ulic' and code in HEALTH_POTIONS and 'Bvul' in buffs):continue
                if hero.type=='Ulic' and code in HEALTH_POTIONS and coil_cover:continue
                if g.cooldown(hero,ability)!=0:continue # unknown is not ready
                addrs=getattr(hero,'item_addrs',()) or ()
                identity=addrs[slot] if len(addrs)>slot and addrs[slot] else (slot,code)
                key=(hero.handle,identity)
                if (buff!='Bvul' and self.attempts.get(key,0)>=3) or now<self.retry.get(key,0):continue
                targets=[u for u in army if u.type in ORGANIC and g.dist(u,hero)<=radius] if radius else [hero]
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
                        if not threat or len(targets)<3:continue
                        priority=5
                    else:
                        if now<self.group_until:continue
                        injured=[u for u in targets if u.hp_max-u.hp>=75]
                        useful=sum(min(heal,max(0,u.hp_max-u.hp)) for u in injured)
                        mana_need=sum(min(mana,max(0,getattr(u,'mana_max',0)-getattr(u,'mana',0))) for u in targets)
                        group_emergency=threat and any(u.is_hero and u.hp/u.hp_max<=.25 and u.hp_max-u.hp>=100 for u in targets)
                        if not group_emergency and not (len(injured)>=2 and useful>=250) and not (code=='sres' and len(injured)>=1 and useful>=150 and mana_need>=150):continue
                        priority=2
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
            before={u.handle:(u.hp,getattr(u,'mana',0)) for u in targets}
            count=bag.count(code)
            summons_before={u.handle for u in g.units('me',{'nsce','nsca'})} if code=='fgsk' else set()
            r=g.use_item(hero,slot)
            invulnerable=ITEMS[code][4]=='Bvul'
            self.attempts[key]=self.attempts.get(key,0)+1;self.retry[key]=now+(.25 if invulnerable else 4)
            # Protect even an uncertain receipt until fresh observation; never spam.
            cast_until[hero.handle]=max(cast_until.get(hero.handle,0),now+(2 if invulnerable else 1.2))
            if ITEMS[code][3]:
                if ITEMS[code][4]:self.buff_until[ITEMS[code][4]]=now+3
                else:self.group_until=now+3
            self.pending[hero.handle]=dict(code=code,key=key,hero=hero.type,count=count,started=now,before=before,
                summons_before=summons_before)
            self.log('consumable_use_attempt',clock=now,hero=hero.type,handle=hero.handle,code=code,
                     hp=hero.hp,hp_max=hero.hp_max,accepted=bool(r),attempt=self.attempts[key],targets=[u.handle for u in targets],
                     buffs=sorted(buffs),emergency=emergency,overrode_cast_lock=locked,
                     focused=focused,coil_cover=coil_cover,controlled=bool(buffs&ITEM_DISABLED))

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
