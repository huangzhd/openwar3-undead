"""A bounded DK shop trip: sell the opening portal, carry mana into the first attack."""
from .equipment import BLUE_POTIONS
from .micro import COIL_MANA


class AttackSupplies:
    def __init__(self,log):
        self.log=log;self.active=None;self.done=False;self.confirmed=False

    def core_ready(self,b):
        heroes=b.g.my_heroes()
        return (any('ocor' in (b.g.inventory(h) or []) for h in heroes)
                and any(h.type not in {'Udea','Ulic'} for h in heroes))

    def ready(self,b):
        # Optional mana supplies cannot hold the first attack; the portal sale remains required.
        bags=[b.g.inventory(h) for h in b.g.my_heroes()]
        return bool(bags) and all(bag is not None and 'stwp' not in bag for bag in bags)

    def reserve(self,b,tier):
        if not b.first_attack_all_in or self.done or tier<3:return 0
        if b.action.name in {'DEFEND','RETREAT'} or b.situation.threatened or not self.core_ready(b):return 0
        dk=next((h for h in b.g.my_heroes() if h.type=='Udea'),None)
        if not dk or dk.mana>=2*COIL_MANA:return 0
        if not any(b.g.dist(dk,s)<=280 for s in b.economy.ready(b.g,'utom')):return 0
        return 0 if any(c in BLUE_POTIONS for h in b.g.my_heroes() for c in b.g.inventory(h) or []) else 200

    def finish(self,now,reason,confirmed=False):
        self.log('first_attack_supply_end',clock=now,reason=reason,confirmed=confirmed)
        self.done=True;self.confirmed=confirmed;self.active=None

    def tick(self,b,army,hostiles,now,tier):
        if not b.first_attack_all_in or self.done or tier!=3:return set()
        g=b.g;heroes=g.my_heroes();dk=next((h for h in heroes if h.type=='Udea'),None)
        if not dk:return set()
        if b.action.name in {'RETREAT','DEFEND'} or b.teleport or b.situation.threatened:return set()
        if dk.handle in b.micro.pulling or any(g.dist(e,dk)<950 for e in hostiles):return set()
        bags={h.handle:g.inventory(h) for h in heroes}
        if any(bag is None for bag in bags.values()):return set()
        # TP is normally on DK; a previous transfer must not evade the sale.
        holder=next((h for h in heroes if 'stwp' in bags[h.handle]),None)
        potion=next(((h,c) for h in heroes for c in bags[h.handle] if c in BLUE_POTIONS),None)
        if not holder and potion and potion[0].handle==dk.handle:
            self.finish(now,'portal_absent_and_dk_mana_item_observed',True);return set()
        if not holder and dk.mana>=2*COIL_MANA:
            self.finish(now,'dk_mana_sufficient_no_potion_needed',True);return set()
        if not holder and not potion and not self.core_ready(b):
            self.active=None;return set() # Fund the orb and third hero first.
        shops=b.economy.ready(g,'utom')
        shop=min(shops,key=lambda s:g.dist(dk,s),default=None)
        if not shop:return set()
        if not holder and not potion and (g.dist(dk,shop)>280 or g.resources()['gold']<200):
            self.active=None;return set() # Optional potion: no separate army-stalling trip.
        if self.active is None:
            self.active=dict(started=now,progress=now,best=None)
            self.log('first_attack_supply_started',clock=now,hero=dk.handle,shop=shop.handle)
        m=self.active
        if now-m['started']>90:
            self.finish(now,'supply_unconfirmed_timeout');return set()
        actor=holder or dk
        if potion and not holder and potion[0].handle!=dk.handle:
            actor=potion[0];point=(dk.x,dk.y);target=dk
        else:target=shop;point=(shop.x,shop.y)
        if actor.handle in b.micro.pulling or any(g.dist(e,actor)<950 for e in hostiles):return set()
        route=g.path_distance((actor.x,actor.y),point)
        if route is None or not b.creeping.safe_route(g,(actor.x,actor.y),point):
            self.finish(now,'unsafe_or_unreachable');return set()
        reserved={dk.handle,actor.handle}
        b.set_intent('首攻备战 · 出售回城' if holder else '按需补给 · 购买蓝瓶')
        if g.dist(actor,target)>280:
            if m['best'] is None or route<m['best']-80:m.update(best=route,progress=now)
            if now-m['progress']>25:
                self.finish(now,'travel_stalled');return set()
            b.go_raw([actor],point,now);return reserved
        if b.battle_shop.pending:return reserved
        if holder:
            b.battle_shop.transact(g,holder,'stwp','sell',now,b.cast_until,shop,allow_portal_sale=True)
        elif potion:
            b.battle_shop.transact(g,actor,potion[1],'give',now,b.cast_until,dk)
        elif now>=440 and g.resources()['gold']>=200 and None in bags[dk.handle]:
            b.battle_shop.transact(g,dk,'pman','buy',now,b.cast_until,shop)
        return reserved
