"""Pick up visible drops after a safe camp clear and verify their observed effect."""
from math import hypot
from .equipment import LICH_ITEMS,BLUE_POTIONS,can_receive

class Loot:
    def __init__(self,catalog,log):
        self.catalog,self.log=catalog,log
        self.pending=None
        self.attempts={}
        self.done=set()
        self.lich_seen=False

    @staticmethod
    def key(item): return (item.handle_lo,item.handle_hi)

    def tick(self,g,army,hostiles,now,all_heroes=None):
        present=[u for u in (army if all_heroes is None else all_heroes) if u.is_hero]
        lich_present=any(u.type=='Ulic' for u in present)
        self.lich_seen=self.lich_seen or lich_present
        heroes=[u for u in army if u.is_hero and u.hp/u.hp_max>.35]
        if not heroes: return None
        center=min(heroes,key=lambda h:sum(g.dist(h,u) for u in army))
        if any(g.dist(e,center)<950 for e in hostiles):
            self.pending=None
            return None
        visible={self.key(it):it for it in g.items_on_ground() if it.life>0}
        p=self.pending
        if p:
            hero=g.unit(p['hero'])
            item=visible.get(p['key'])
            if hero is None:
                self.pending=None
                return None
            if item is None:
                inv=g.inventory(hero) or []
                confirmed=(p['addr'] in getattr(hero,'item_addrs',[])) or inv.count(p['code'])>p['count']
                effect=hero.xp>p['xp'] or hero.hp_max>p['hp_max'] or hero.mana_max>p['mana_max']
                consumed=p['powerup'] and p['near'] and g.visible(*p['point']) and p['accepted']
                event='loot_confirmed' if confirmed else 'powerup_confirmed' if effect and p['powerup'] else 'powerup_collected' if consumed else 'loot_unconfirmed'
                self.log(event,clock=now,code=p['code'],hero=hero.type,attribute_change=bool(effect))
                if confirmed or consumed or effect:self.done.add(p['key'])
                self.pending=None
                return None
            p['near']=p['near'] or g.dist(hero,item)<180
            if now-p['started']>10:
                self.log('loot_retry_expired',clock=now,code=p['code'])
                self.pending=None
                return None
            if now-p['issued']>=2:
                p['issued']=now
                p['accepted']=bool(g.pick_up(hero,item)) or p['accepted']
            return hero,p['point']
        candidates=[it for key,it in visible.items() if key not in self.done and self.attempts.get(key,0)<3 and g.dist(it,center)<900]
        for item in sorted(candidates,key=lambda it:g.dist(it,center)):
            if item.type=='stwp' and any('stwp' in (g.inventory(h) or []) for h in present):continue
            row=self.catalog.get(item.type,{})
            powerup=row.get('powerup',False)
            eligible=[h for h in heroes if g.inventory(h) is not None and (powerup or can_receive(h,g.inventory(h),item.type))]
            if not eligible:continue
            if powerup and row.get('effects',{}).get('tome_int',0)>0:
                # Consumable stat gains cannot be handed over later. Once Lich
                # has joined, leave his book on the ground while unavailable.
                preferred='Ulic' if lich_present or self.lich_seen else 'Udea'
                eligible=[h for h in eligible if h.type==preferred]
                if not eligible:continue
            if item.type in BLUE_POTIONS and any(h.type=='Udea' for h in eligible):
                eligible=[h for h in eligible if h.type=='Udea']
            if item.type in LICH_ITEMS and any(h.type=='Ulic' for h in eligible):
                eligible=[h for h in eligible if h.type=='Ulic']
            preferred='Ulic' if 'tome_int' in row.get('effects',{}) else 'Nbrn' if 'tome_agi' in row.get('effects',{}) else 'Udea'
            hero=min(eligible,key=lambda h:g.dist(h,item)+(0 if h.type==preferred else 150))
            route=g.path_distance((hero.x,hero.y),(item.x,item.y))
            if route is None or route>1100:continue
            key=self.key(item)
            self.attempts[key]=self.attempts.get(key,0)+1
            accepted=bool(g.pick_up(hero,item))
            self.pending=dict(key=key,code=item.type,addr=item.addr,hero=hero.handle,point=(item.x,item.y),started=now,issued=now,
                count=(g.inventory(hero) or []).count(item.type),powerup=powerup,xp=hero.xp,hp_max=hero.hp_max,mana_max=hero.mana_max,
                near=g.dist(hero,item)<180,accepted=accepted)
            self.log('loot_attempt',clock=now,code=item.type,hero=hero.type,powerup=powerup,accepted=accepted)
            return hero,(item.x,item.y)
        return None
