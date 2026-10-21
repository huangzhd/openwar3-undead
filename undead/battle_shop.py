"""Bounded, fair-view item trading and independent DK orb delivery."""
from .equipment import can_receive
from .home_layout import clear_of_buildings
from math import cos,sin,pi

RINGS={'rde0':25,'rde1':62,'rde2':150,'rde3':300,'rde4':400}
UNWANTED_AURAS={'sbch','lhst'} # Vampiric / Devotion: user explicitly wants both sold.

def sellable(hero,code):
    return code in RINGS or code in {'clsd','wlsd','brac'}|UNWANTED_AURAS or (hero.type=='Udea' and code=='woms')

class BattleShop:
    def __init__(self,log):
        self.log=log;self.pending=None;self.attempts={};self.next_at=0;self.confirmed_buys={}
        self.defense=None;self.defense_retry=0
        self.orb=None;self.orb_retry=0;self.potion=None;self.potion_retry=0
        self.rod=None;self.rod_retry=0;self.lich_rod_bought=False;self.lich_rod_attempts=0
        self.bone_chime=None;self.bone_chime_trips={};self.bone_chime_sales={}
        self.bone_chime_retry=0

    @property
    def reserved(self):
        if not self.orb:return set()
        return {self.orb['hero']}|({self.orb['receiver']} if self.orb.get('meeting') else set())

    def orb_meeting(self,b,dk,lich,avoid=None):
        """Meet on open ground reachable by both heroes, outside own buildings."""
        g=b.g;center=((dk.x+lich.x)/2,(dk.y+lich.y)/2)
        buildings=g.my_buildings() if hasattr(g,'my_buildings') else []
        choices=[]
        for radius in (0,128,256,384,512,768):
            for k in range(8 if radius else 1):
                p=(center[0]+radius*cos(k*pi/4),center[1]+radius*sin(k*pi/4))
                if avoid is not None and g.dist(p,avoid)<192:continue
                if not clear_of_buildings(p,buildings):continue
                routes=[g.path_distance((h.x,h.y),p) for h in (dk,lich)]
                if any(d is None for d in routes):continue
                if not all(b.creeping.safe_route(g,(h.x,h.y),p) for h in (dk,lich)):continue
                choices.append((max(routes)+.25*sum(routes),p))
        return min(choices,key=lambda pair:pair[0])[1] if choices else None

    def orb_reserve(self,g):
        # A dispatched courier owns the orb budget until an actual team bag
        # confirms it. LR 0.1.74 spent this money on a fiend before buying.
        if not self.orb:return 0
        return 0 if any('ocor' in (g.inventory(h) or []) for h in g.my_heroes()) else 375

    def orb_purchased(self,g):
        # An order or reserved gold is not ownership. DK may still be delivering.
        return any('ocor' in (g.inventory(h) or []) for h in g.my_heroes())

    def observe(self,g,now):
        p=self.pending
        if not p:return
        hero=g.unit(p['hero']);bag=g.inventory(hero) if hero else None
        changed=bag is not None and bag.count(p['code'])<p['before']
        if p['kind']=='buy':changed=bag is not None and bag.count(p['code'])>p['before']
        if p['kind']=='give':
            receiver=g.unit(p['receiver']);target=g.inventory(receiver) if receiver else None
            changed=changed and target is not None and target.count(p['code'])>p['receiver_before']
        refund=None
        if p['kind']=='sell':
            res=g.resources();refund=res['gold']-p['gold']-(res.get('gold_gathered',0)-p['gathered'])
            changed=changed and (refund>=RINGS[p['code']] if p['code'] in RINGS else refund>0)
        # A neutral shop may choose a different friendly recipient.
        if p['kind']=='buy' and not changed:
            changed=any((g.inventory(h) or []).count(p['code'])>p['team_before'].get(h.handle,0) for h in g.my_heroes())
        if changed and p['kind']=='buy':
            self.confirmed_buys[(p['hero'],p['code'])]=dict(clock=now,before=p['team_before'])
        if changed and p['kind']=='buy' and p['code']=='rnec' and self.rod and p['hero']==self.rod['hero']:
            self.rod['purchased']=True;self.lich_rod_bought=True
        if changed or now-p['started']>=3:
            self.log('shop_transaction_confirmed' if changed else 'shop_transaction_unconfirmed',clock=now,
                     kind=p['kind'],code=p['code'],hero=p['hero'],
                     recipients=[h.handle for h in g.my_heroes() if (g.inventory(h) or []).count(p['code'])>p.get('team_before',{}).get(h.handle,0)] if p['kind']=='buy' else [p.get('receiver',p['hero'])],
                     refund_excluding_gathering=refund)
            self.pending=None

    def transact(self,g,hero,code,kind,now,cast_until,target,allow_portal_sale=False):
        if self.pending or now<self.next_at or now<cast_until.get(hero.handle,0):return False
        bag=g.inventory(hero)
        if bag is None:return False
        key=(kind,hero.handle,code,tuple(bag),target.handle,int(now//120))
        if self.attempts.get(key,0)>=3:return False
        res=g.resources();p=dict(kind=kind,hero=hero.handle,code=code,before=bag.count(code),started=now,
                                gold=res['gold'],gathered=res.get('gold_gathered',0))
        if kind=='buy':
            p['team_before']={h.handle:(g.inventory(h) or []).count(code) for h in g.my_heroes()}
            result=g.buy(target,code)
        elif kind=='give':
            other=g.inventory(target)
            if other is None or None not in other or code not in bag:return False
            p.update(receiver=target.handle,receiver_before=other.count(code))
            result=g.give_item(hero,bag.index(code),target)
            cast_until[target.handle]=now+1.2
        else:
            if not (sellable(hero,code) or code=='stwp' and allow_portal_sale) or code not in bag:return False
            result=g.sell_item(hero,bag.index(code),target)
        self.attempts[key]=self.attempts.get(key,0)+1;self.next_at=now+3;self.pending=p
        cast_until[hero.handle]=now+1.2
        self.log('shop_transaction_attempt',clock=now,kind=kind,code=code,hero=hero.type,accepted=bool(result),reason=getattr(result,'reason',None),attempt=self.attempts[key])
        return True

    def sell_nearby(self,b,heroes,hostiles,now):
        g=b.g
        if self.pending:return True
        if not any(sellable(h,c) for h in heroes for c in g.inventory(h) or []):return False
        shops=b.economy.ready(g,'utom')+[u for u in g.units('all',{'ngme'}) if u.alive and u.visible_to(g.me())]
        for hero in heroes:
            if any(g.dist(e,hero)<950 for e in hostiles):continue
            bag=g.inventory(hero) or []
            ring=next((c for c in bag if c in UNWANTED_AURAS),None) or next((c for c in bag if sellable(hero,c)),None)
            if ring:
                shop=next((s for s in shops if g.dist(hero,s)<300),None)
                if shop and self.transact(g,hero,ring,'sell',now,b.cast_until,shop):return True
        return False

    def bone_chime_tick(self,b,army,hostiles,now):
        """Sell either unwanted aura with its actual holder, then rejoin."""
        g=b.g
        m=self.bone_chime
        def safe(h):
            return (h.hp>0 and h.hp>=.6*h.hp_max and h.handle not in b.micro.pulling
                    and not any(g.dist(e,h)<950 for e in hostiles)
                    and now>=b.cast_until.get(h.handle,0))
        heroes=g.my_heroes()
        hero=next((h for h in heroes if h.handle==m['hero']),None) if m else next(
            (h for h in heroes if safe(h) and any(c in UNWANTED_AURAS
                and self.bone_chime_trips.get((h.handle,c),0)<3
                and self.bone_chime_sales.get((h.handle,c),0)<3 for c in g.inventory(h) or [])),None)
        def end(reason):
            self.log('bone_chime_courier_end',clock=now,reason=reason)
            self.bone_chime=None;self.bone_chime_retry=now+5
            if hero and g.inventory(hero) is not None:
                for code in UNWANTED_AURAS:
                    if code not in g.inventory(hero):
                        self.bone_chime_trips.pop((hero.handle,code),None)
                        self.bone_chime_sales.pop((hero.handle,code),None)
            b.formation.reset();b.formation_at=-100
            return set()
        unsafe=(b.action.name in {'RETREAT','DEFEND'} or b.teleport or b.situation.threatened
                or hero and (hero.hp<.6*hero.hp_max or hero.handle in b.micro.pulling
                             or any(g.dist(e,hero)<950 for e in hostiles)))
        if not hero or unsafe:
            return end('safety_or_hero_missing') if m else set()
        bag=g.inventory(hero)
        if m is None:
            if bag is None or now<self.bone_chime_retry or self.pending:return set()
            code=next((c for c in bag if c in UNWANTED_AURAS
                       and self.bone_chime_trips.get((hero.handle,c),0)<3
                       and self.bone_chime_sales.get((hero.handle,c),0)<3),None)
            if code is None:return set()
            shops=b.economy.ready(g,'utom')+[u for u in g.units('all',{'ngme'}) if u.alive and u.visible_to(g.me())]
            choices=[]
            for shop in shops:
                point=(shop.x,shop.y);distance=g.path_distance((hero.x,hero.y),point)
                if (distance is not None and not any(g.dist(e,shop)<950 for e in hostiles)
                        and b.creeping.safe_route(g,(hero.x,hero.y),point)):
                    choices.append((distance,shop))
            if not choices:return set()
            shop=min(choices,key=lambda x:x[0])[1]
            # Aura sale takes priority over optional supply travel. Replanning
            # later reads actual inventory, so a purchased orb/rod is not rebought.
            if self.orb:self.end_orb(now,'aura_sale_priority');self.orb_retry=now
            if self.rod:self.end_rod(now,'aura_sale_priority');self.rod_retry=now
            if getattr(b,'first_attack_supply',None):b.first_attack_supply.active=None
            key=(hero.handle,code)
            self.bone_chime_trips[key]=self.bone_chime_trips.get(key,0)+1
            m=self.bone_chime=dict(hero=hero.handle,code=code,shop=shop.handle,started=now,progress=now,best=None,returning=False)
            b.formation.reset();b.formation_at=-100
            self.log('bone_chime_courier_started',clock=now,hero=hero.handle,code=code,shop=shop.handle)
        if now-m['started']>120:return end('mission_timeout')
        reserved={hero.handle}
        if bag is None:return reserved
        if m['code'] not in bag and not m['returning']:
            self.log('bone_chime_removed',clock=now,hero=hero.handle,code=m['code'])
            code=next((c for c in bag if c in UNWANTED_AURAS),None)
            m.update(returning=code is None,best=None,progress=now)
            if code is not None:m['code']=code # Sell both in one visit.
        main=[u for u in army if u.handle!=hero.handle and u.type not in {'uske','uskm','nsce','nsca'}]
        if m['returning'] and not main:return end('no_main_body')
        target=min(main,key=lambda u:sum(g.dist(u,v) for v in main)) if m['returning'] else g.unit(m['shop'])
        if target is None:return end('shop_missing')
        if m['returning'] and g.dist(hero,target)<550:return end('rejoined')
        point=(target.x,target.y);distance=g.path_distance((hero.x,hero.y),point)
        if distance is None or not b.creeping.safe_route(g,(hero.x,hero.y),point):return end('unsafe_or_unreachable')
        if m['best'] is None or distance<m['best']-80:m.update(best=distance,progress=now)
        if now-m['progress']>25:return end('travel_or_sale_stalled')
        if self.pending:return reserved
        if m['returning'] or g.dist(hero,target)>280:
            b.go_raw([hero],point,now);return reserved
        key=(hero.handle,m['code'])
        if self.bone_chime_sales.get(key,0)>=3:return end('sale_attempt_limit')
        if self.transact(g,hero,m['code'],'sell',now,b.cast_until,target):
            self.bone_chime_sales[key]=self.bone_chime_sales.get(key,0)+1
        return reserved

    def end_orb(self,now,reason):
        self.log('orb_courier_end',clock=now,reason=reason)
        self.orb=None;self.orb_retry=now+(0 if reason=='delivered' else 5 if reason in {'unsafe_or_hero_missing','player_contact','home_defense','delivery_stalled'} else 120)

    def orb_tick(self,b,army,hostiles,now,tier):
        g=b.g;heroes=g.my_heroes();dk=next((h for h in heroes if h.type=='Udea'),None)
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        unsafe=b.action.name in {'RETREAT','DEFEND'} or b.teleport or b.situation.threatened
        players=[e for e in hostiles if 0<=getattr(e,'owner',12)<12 and e.owner!=g.me()]
        # Low health alone never blocks a trip home. A pullback only owns DK
        # while he is still under fire, or while delivering towards the front.
        db=g.inventory(dk) if dk else None
        target_of=getattr(g,'current_target',lambda u:None)
        under_fire=dk and any((t:=target_of(e)) is not None and t.handle==dk.handle and g.dist(e,dk)<900 for e in hostiles)
        pulling=dk and dk.handle in b.micro.pulling and (under_fire or db is None or 'ocor' in db)
        if self.orb and (not dk or not lich or unsafe or pulling or any(g.dist(e,dk)<950 for e in players)):
            self.end_orb(now,'unsafe_or_hero_missing');return set()
        if not dk or not lich or tier!=3 or unsafe or now<self.orb_retry:return set()
        db=g.inventory(dk);lb=g.inventory(lich)
        if db is None or lb is None:return self.reserved
        if 'ocor' in lb:
            if self.orb:self.end_orb(now,'delivered');b.formation.reset();b.formation_at=-100
            return set()
        if any('ocor' in (g.inventory(h) or []) for h in heroes if h not in (dk,lich)):
            if self.orb:self.end_orb(now,'team_item_pending_transfer')
            return set()
        if not self.orb:
            if pulling or any(g.dist(e,h)<950 for e in players for h in heroes):return set()
            if not can_receive(lich,lb,'ocor'):return set()
            portal_sale=getattr(b,'first_attack_all_in',False) and 'stwp' in db
            if 'ocor' not in db and (None not in db and not portal_sale and not any(sellable(dk,c) for c in db)):return set()
            if 'ocor' not in db and g.resources()['gold']+sum(RINGS.get(c,0) for c in db)+(175 if portal_sale else 0)<375:return set()
            # Collect nearby rings before DK departs; transactions are observed before continuing.
            for h in heroes:
                ring=next((c for c in g.inventory(h) or [] if c in RINGS),None)
                if h is not dk and ring and None in db and g.dist(h,dk)<350:
                    if self.transact(g,h,ring,'give',now,b.cast_until,dk):return {dk.handle}
                    if self.pending:return {dk.handle}
            shops=b.economy.ready(g,'utom')
            shop=min(shops,key=lambda s:g.dist(dk,s)) if shops else None
            if not shop:return set()
            if not b.creeping.safe_route(g,(dk.x,dk.y),(shop.x,shop.y)):return set()
            self.orb=dict(hero=dk.handle,shop=shop.handle,started=now,progress_at=now,best=None,target=None)
            b.micro.dk_recovering=None;b.formation.reset();b.formation_at=-100
            self.log('orb_courier_started',clock=now,hero=dk.handle,shop=shop.handle)
        mission=self.orb
        if now-mission['started']>120:
            self.end_orb(now,'travel_timeout');return set()
        if self.pending:return self.reserved
        shop=g.unit(mission['shop'])
        target=lich if 'ocor' in db else shop
        if target is None:self.end_orb(now,'shop_missing');return set()
        point=(target.x,target.y);route=g.path_distance((dk.x,dk.y),point)
        delivering='ocor' in db
        if delivering and (mission.get('meeting') or route is None or
                mission['target']==target.handle and now-mission['progress_at']>6 and g.dist(dk,lich)>200):
            meeting=mission.get('meeting')
            if meeting is None or now-mission.get('meeting_progress_at',now)>8:
                if mission.get('meeting_attempts',0)>=3:
                    self.end_orb(now,'delivery_stalled');return set()
                meeting=self.orb_meeting(b,dk,lich,meeting)
                if meeting is None:
                    self.end_orb(now,'delivery_stalled');return set()
                mission.update(meeting=meeting,receiver=lich.handle,meeting_progress_at=now,
                               meeting_best=None,meeting_attempts=mission.get('meeting_attempts',0)+1)
                self.log('orb_meeting_planned',clock=now,point=meeting,dk=dk.handle,lich=lich.handle)
            remaining=max(g.dist(h,meeting) for h in (dk,lich))
            if mission['meeting_best'] is None or remaining<mission['meeting_best']-40:
                mission.update(meeting_best=remaining,meeting_progress_at=now)
            # Actual bag changes, not accepted give orders, complete this task.
            if g.dist(dk,lich)<=200:
                self.transact(g,dk,'ocor','give',now,b.cast_until,lich)
            else:
                b.go_raw([dk,lich],meeting,now)
            return self.reserved
        if route is None or not b.creeping.safe_route(g,(dk.x,dk.y),point):
            self.end_orb(now,'unsafe_route');return set()
        if not delivering:
            b.micro.pulling.discard(dk.handle)
            b.micro.dk_recovering=None;b.micro.dk_support=None
        if mission['target']!=target.handle:
            mission.update(target=target.handle,best=route,progress_at=now)
        elif mission['best'] is None or route<mission['best']-80:
            mission.update(best=route,progress_at=now)
        if g.dist(dk,target)>(200 if delivering else 280):
            if now-mission['progress_at']>25:
                self.end_orb(now,'travel_timeout');return set()
            b.go_raw([dk],point,now);return self.reserved
        # Waiting for funds at the shop is not travel stagnation. The whole
        # mission still has its 120s ceiling, with bounded transaction retries.
        if 'ocor' not in db and g.resources()['gold']<375 and now-mission.get('wait_log',-100)>=5:
            mission['wait_log']=now
            self.log('orb_purchase_wait',clock=now,gold=g.resources()['gold'],required=375)
        if 'ocor' in db:
            self.transact(g,dk,'ocor','give',now,b.cast_until,lich)
        else:
            ring=next((c for c in db if sellable(dk,c)),None)
            if getattr(b,'first_attack_all_in',False) and 'stwp' in db:
                self.transact(g,dk,'stwp','sell',now,b.cast_until,shop,allow_portal_sale=True)
            elif ring:self.transact(g,dk,ring,'sell',now,b.cast_until,shop)
            elif not b.economy.revival_pending(g) and g.resources()['gold']>=375 and None in db:
                self.transact(g,dk,'ocor','buy',now,b.cast_until,shop)
        return self.reserved

    def end_rod(self,now,reason):
        self.log('rod_courier_end',clock=now,reason=reason)
        self.rod=None;self.rod_retry=now+(0 if reason=='rejoined' else 120)

    def rod_tick(self,b,hostiles,now,tier):
        """The new Lich buys one rod, then rejoins DK without recalling the army."""
        g=b.g;heroes=g.my_heroes()
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        dk=next((h for h in heroes if h.type=='Udea'),None)
        unsafe=b.action.name in {'RETREAT','DEFEND'} or b.teleport or b.situation.threatened
        bag=g.inventory(lich) if lich else None
        stop=getattr(b,'ni_rod_stop',None)
        receipt=self.confirmed_buys.get((dk.handle,'rnec')) if dk else None
        if (lich and stop and stop.mission and receipt and receipt['clock']>=stop.mission['started']
                and bag is not None and bag.count('rnec')>receipt['before'].get(lich.handle,0)
                and not self.lich_rod_bought and not unsafe):
            # The shop gave DK's purchased rod to Lich. Let DK collect it;
            # this does not fulfil Lich's own separate first purchase.
            return {lich.handle}
        if self.rod and (not lich or not dk or unsafe or lich.handle in b.micro.pulling
                         or any(g.dist(e,lich)<950 for e in hostiles)):
            self.end_rod(now,'unsafe_or_hero_missing');return set()
        if not lich or not dk or unsafe:return set()
        if bag is not None and 'rnec' in bag:self.lich_rod_bought=True
        if self.rod is None:
            if (self.lich_rod_bought or self.lich_rod_attempts>=3 or tier<2 or now<self.rod_retry or self.orb or self.pending or bag is None or 'rnec' in bag
                    or not b.economy.opening_rod_allowed or b.economy.revival_pending(g)
                    or lich.hp<.6*lich.hp_max or lich.handle in b.micro.pulling
                    or any(g.dist(e,lich)<950 for e in hostiles) or None not in bag):return set()
            shops=b.economy.ready(g,'utom')
            shop=min(shops,key=lambda u:g.dist(lich,u),default=None)
            if shop is None:return set()
            self.rod=dict(hero=lich.handle,shop=shop.handle,started=now,progress=now,best=None,
                          returning=False,buys=0,team_before={h.handle:(g.inventory(h) or []).count('rnec') for h in heroes})
            b.formation.reset();b.formation_at=-100
            self.log('rod_courier_started',clock=now,hero=lich.handle,leader=dk.handle,shop=shop.handle)
        m=self.rod;reserved={lich.handle}
        if now-m['started']>120:
            self.end_rod(now,'mission_timeout');return set()
        if bag is None:return reserved
        if 'rnec' in bag and not m['returning']:
            m.update(returning=True,best=None,progress=now)
            self.log('rod_courier_inventory_confirmed',clock=now,hero=lich.handle)
        if m['returning'] and g.dist(lich,dk)<=550:
            self.end_rod(now,'rejoined');b.formation.reset();b.formation_at=-100;return set()
        donor=next((h for h in heroes if h.handle!=lich.handle and (g.inventory(h) or []).count('rnec')>m['team_before'].get(h.handle,0)),None)
        target=dk if m['returning'] else donor or g.unit(m['shop'])
        if target is None:self.end_rod(now,'shop_missing');return set()
        point=(target.x,target.y);route=g.path_distance((lich.x,lich.y),point)
        if route is None or not b.creeping.safe_route(g,(lich.x,lich.y),point):
            self.end_rod(now,'unsafe_or_unreachable');return set()
        if m['best'] is None or route<m['best']-80:m.update(best=route,progress=now)
        if now-m['progress']>25:
            self.end_rod(now,'travel_or_stock_stalled');return set()
        if now<b.cast_until.get(lich.handle,0):return reserved
        if g.dist(lich,target)>280 or m['returning']:
            b.go_raw([lich],point,now);return reserved
        if self.pending:return reserved
        if donor:
            # A shop can choose another nearby hero; transfer the observed rod, never buy again.
            if g.dist(donor,lich)<=350:self.transact(g,donor,'rnec','give',now,b.cast_until,lich)
            else:b.go_raw([lich],(donor.x,donor.y),now)
            return reserved
        if m.get('purchased'):
            self.end_rod(now,'purchased_rod_recipient_missing');return set()
        if self.lich_rod_attempts>=3:
            self.end_rod(now,'purchase_unconfirmed');return set()
        if g.resources()['gold']>=150 and None in bag and not b.economy.revival_pending(g):
            if self.transact(g,lich,'rnec','buy',now,b.cast_until,target):
                m['buys']+=1;self.lich_rod_attempts+=1
        return reserved

    def defend_tick(self,b,hostiles,now,tier):
        """Local defensive supply: reserve only the buyer, never the whole army."""
        from .retreat import clearance
        from .controller import ground_attack_range
        from math import ceil
        g=b.g;heroes=g.my_heroes()
        dk=next((h for h in heroes if h.type=='Udea'),None)
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        if self.orb:self.end_orb(now,'home_defense')
        if not dk or not lich or b.teleport or b.economy.revival_pending(g):return set()
        if self.pending:
            return {self.pending['hero'],*([self.pending['receiver']] if 'receiver' in self.pending else [])}
        if now<self.defense_retry:return set()
        bags={h.handle:g.inventory(h) for h in heroes}
        if any(bag is None for bag in bags.values()):return set()
        code=None;receiver=None
        if dk.mana<75 and now>=440 and g.dist(dk,b.home)<1600 and g.dist(dk,lich)<1100:
            if not any(c in bags[dk.handle] for c in ('pman','pgma','mnst','pres')):
                code='pman';receiver=dk
        if code is None and tier==3 and 'ocor' not in bags[lich.handle]:
            code='ocor';receiver=lich
        if code is None or not can_receive(receiver,bags[receiver.handle],code):return set()
        codes=('pman','pgma','mnst') if code=='pman' else ('ocor',)
        donor=next((h for h in heroes if any(c in bags[h.handle] for c in codes)),None)
        if donor:
            if donor is not receiver and g.dist(donor,receiver)<350:
                item=next(c for c in bags[donor.handle] if c in codes)
                if self.transact(g,donor,item,'give',now,b.cast_until,receiver):return {donor.handle,receiver.handle}
            return set() # Never duplicate an item carried by another hero.
        if g.resources()['gold']<({'pman':200,'ocor':375}[code]):return set()
        shops=[s for s in b.economy.ready(g,'utom') if g.dist(s,b.home)<1200 and clearance((s.x,s.y),hostiles,ground_attack_range)>=100]
        buyers=[receiver] if code=='pman' else [lich,dk]
        for hero in buyers:
            if hero.hp/hero.hp_max<.6 or g.dist(hero,b.home)>1600 or now<b.cast_until.get(hero.handle,0):continue
            if None not in bags[hero.handle]:continue
            for shop in sorted(shops,key=lambda s:g.dist(hero,s)):
                start=(hero.x,hero.y);point=(shop.x,shop.y);length=g.path_distance(start,point)
                if length is None or length>900:continue
                before=clearance(start,hostiles,ground_attack_range)
                path=g.walk_path(start,point)
                if not path or g.dist(path[-1],point)>128:continue
                safe=True;a=start
                for z in path:
                    count=max(1,ceil(g.dist(a,z)/96))
                    if any(clearance((a[0]+(z[0]-a[0])*i/count,a[1]+(z[1]-a[1])*i/count),hostiles,ground_attack_range)<min(100,before)-32 for i in range(1,count+1)):
                        safe=False;break
                    a=z
                if not safe:continue
                if g.dist(hero,shop)<=280:
                    self.defense=None
                    if self.transact(g,hero,code,'buy',now,b.cast_until,shop):
                        self.log('defense_supply',clock=now,hero=hero.type,code=code,stage='purchase')
                        return {hero.handle}
                    return set()
                key=(hero.handle,shop.handle,code)
                if not self.defense or self.defense['key']!=key:self.defense=dict(key=key,started=now)
                if now-self.defense['started']>12:
                    self.defense=None;self.defense_retry=now+30;return set()
                b.go_raw([hero],point,now)
                self.log('defense_supply',clock=now,hero=hero.type,code=code,stage='approach')
                return {hero.handle}
        return set()

    def prepare_mana(self,b,army,dk,now):
        # Local ItemData.slk: 200 gold, first stock 440s, replenishment 120s.
        g=b.g;bag=g.inventory(dk)
        if bag is None or any(c in bag for c in ('pman','pgma','mnst','pres')):return False
        if None not in bag or b.economy.revival_pending(g):return False
        heroes=g.my_heroes();foes=g.enemies()+g.creeps()
        if any(g.dist(e,h)<950 for e in foes for h in heroes):return False
        donor=next((h for h in heroes if h.handle!=dk.handle and any(c in (g.inventory(h) or []) for c in ('pman','pgma','mnst'))),None)
        if donor:
            if g.dist(donor,dk)<350:
                code=next(c for c in g.inventory(donor) if c in ('pman','pgma','mnst'))
                self.transact(g,donor,code,'give',now,b.cast_until,dk)
                return True
            point=(dk.x,dk.y)
            route=g.path_distance((donor.x,donor.y),point)
            if route is None or route>2400 or not b.creeping.safe_route(g,(donor.x,donor.y),point):return False
            b.go(army,point,now)
            b.go_raw([donor],point,now)
            return True
        if now<440:return False
        shops=[s for s in b.economy.ready(g,'utom') if not any(g.dist(e,s)<950 for e in foes)]
        shop=g.nearest(shops,dk) if shops else None
        if shop is None or g.resources()['gold']<200:return False
        point=(shop.x,shop.y);route=g.path_distance((dk.x,dk.y),point)
        if route is None or route>2400 or not b.creeping.safe_route(g,(dk.x,dk.y),point):return False
        b.set_intent('出征补给 · 死亡骑士魔法药水')
        b.go(army,point,now)
        if g.dist(dk,shop)>280 or self.pending:return True
        if b.clear_full_shop_heroes(heroes,dk,shop,now):return True
        self.transact(g,dk,'pman','buy',now,b.cast_until,shop)
        return True

    def needs_potion(self,b,now):
        g=b.g;heroes=g.my_heroes();lich=next((h for h in heroes if h.type=='Ulic'),None)
        if not lich or now<440 or now<self.potion_retry:return False
        if any(c in {'pnvl','pnvu'} for h in heroes for c in g.inventory(h) or []):return False
        if not can_receive(lich,g.inventory(lich),'pnvl'):return False
        return any(u.alive and u.visible_to(g.me()) for u in g.units('all',{'ngme'}))

    def prepare_potion(self,b,army,hostiles,now,opportunistic=False):
        g=b.g;heroes=g.my_heroes();lich=next((h for h in heroes if h.type=='Ulic'),None)
        if not lich:return True
        bag=g.inventory(lich)
        if bag is None:return True
        if any(c in bag for c in ('pnvl','pnvu')):self.potion=None;return True
        donor=next((h for h in heroes if h is not lich and any(c in (g.inventory(h) or []) for c in ('pnvl','pnvu'))),None)
        if donor and can_receive(lich,bag,'pnvl') and g.dist(donor,lich)<350:
            code=next(c for c in g.inventory(donor) if c in {'pnvl','pnvu'})
            self.transact(g,donor,code,'give',now,b.cast_until,lich);return opportunistic
        if not self.needs_potion(b,now):return True
        if any(g.dist(e,h)<950 for e in hostiles for h in heroes) or b.economy.revival_pending(g):return True
        shops=[u for u in g.units('all',{'ngme'}) if u.alive and u.visible_to(g.me())]
        choices=[]
        for shop in shops:
            point=(shop.x,shop.y);route=g.path_distance((lich.x,lich.y),point)
            if any(g.dist(e,shop)<950 for e in hostiles):continue
            if (not opportunistic or g.dist(lich,shop)<=280) and route is not None and route<6000 and b.creeping.safe_route(g,(lich.x,lich.y),point):choices.append((route,shop.handle,shop))
        if not choices:self.potion_retry=now+120;return True
        _,_,shop=min(choices)
        if self.potion is None:self.potion=dict(started=now,progress_at=now,best=None)
        mission=self.potion;distance=g.dist(lich,shop)
        if mission['best'] is None or distance<mission['best']-80:mission.update(best=distance,progress_at=now)
        if now-mission['started']>60 or now-mission['progress_at']>20:
            self.potion=None;self.potion_retry=now+120;return True
        if not opportunistic:
            b.set_intent('出征补给 · 巫妖小型无敌药水')
            b.go(army,(shop.x,shop.y),now)
        if distance>280 or self.pending:return opportunistic
        if self.sell_nearby(b,heroes,hostiles,now):return opportunistic
        if g.resources()['gold']>=150:
            self.transact(g,lich,'pnvl','buy',now,b.cast_until,shop)
        return opportunistic
