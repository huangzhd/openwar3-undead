"""Safe hero equipment handoffs; inventory observations confirm every transfer."""
import json
from bootstrap import UPSTREAM

BLUE_POTIONS={'pman','pgma','mnst'} # Mana Stone follows DK mana-supply ownership.
HEALTH_POTIONS={'phea','pghe'}
HEALING_SCROLLS={'shea','sres'}
HEALTH_HEROES=('Ulic','Nbrn')
CLAWS={'rat3':3,'rat6':6,'rat9':9,'ratc':12,'ratf':15}
# Lich gains attack from intelligence and attack speed from agility. The pinned
# local item catalog supplies numeric bonuses; these additional item abilities
# carry attack/orb or endurance-aura bonuses not expanded by that catalog.
_ITEM_CATALOG=json.loads((UPSTREAM/'data/game/items.json').read_text(encoding='utf-8'))
DK_RINGS={code for code in _ITEM_CATALOG if code.startswith('rde')}
AGILITY_ITEMS={code for code,row in _ITEM_CATALOG.items() if not row.get('powerup',False)
               and row.get('effects',{}).get('agi',0)>0 and not row.get('effects',{}).get('int',0)}
LICH_ITEMS={'pnvl','pnvu','sror'}|set(CLAWS)|{'bspd','ajen','ocor','odef','ofir','ofro','olig','oli2','oslo','oven','ward'}|{
    code for code,row in _ITEM_CATALOG.items() if not row.get('powerup',False)
    and any(row.get('effects',{}).get(effect,0)>0
            for effect in ('attack','attack_speed','int','aura_trueshot'))}
LICH_ITEMS-=AGILITY_ITEMS|DK_RINGS


def gear_owner(code):
    if code in DK_RINGS:return 'Udea'
    if code in AGILITY_ITEMS:return 'Nbrn'
    if code in LICH_ITEMS:return 'Ulic'
    return None



def can_receive(hero,bag,code):
    if bag is None:return False
    # Roar is spent on contact and temporarily occupies the future orb slot.
    reserve=hero.type=='Ulic' and 'ocor' not in bag and 'sror' not in bag and code not in {'ocor','sror'}
    return bag.count(None)>=(2 if reserve else 1)


def supply_receiver(hero,bag,code):
    """Ownership only; capacity and safe delivery are checked separately."""
    if bag is None:return False
    if code in HEALTH_POTIONS:
        return hero.type in HEALTH_HEROES and not any(c in HEALTH_POTIONS for c in bag)
    return True


def can_release(hero,bag,code):
    if code=='sror' and hero.type=='Ulic':return False
    if code in HEALTH_POTIONS and hero.type in HEALTH_HEROES:
        return sum(c in HEALTH_POTIONS for c in bag)>1
    if code in HEALING_SCROLLS:return sum(c in HEALING_SCROLLS for c in bag)>1
    return True


def scroll_priority(hero,bag):
    count=sum(c in HEALING_SCROLLS for c in bag)
    return count, 0 if hero.type=='Ulic' else 1 if hero.type=='Udea' else 2


class Equipment:
    def __init__(self,log):
        self.log=log
        self.pending=None
        self.attempts={}

    @property
    def reserved(self):
        return {self.pending['donor'],self.pending['receiver']} if self.pending else set()

    def release(self,cast_until):
        for handle in self.reserved:
            if cast_until.get(handle)==self.pending.get('lock_until'):
                cast_until.pop(handle,None)
        self.pending=None

    def tick(self,g,army,hostiles,now,cast_until,potions_only=False):
        heroes=[u for u in army if u.is_hero]
        bags={u.handle:g.inventory(u) for u in heroes}
        p=self.pending
        if p:
            donor=next((u for u in heroes if u.handle==p['donor']),None)
            receiver=next((u for u in heroes if u.handle==p['receiver']),None)
            a=bags.get(p['donor']);b=bags.get(p['receiver'])
            if a is not None and b is not None and a.count(p['code'])<p['from_count'] and b.count(p['code'])>p['to_count']:
                self.log('equipment_transfer_confirmed',clock=now,code=p['code'],from_hero=donor.type,to_hero=receiver.type,inventory=b)
                self.release(cast_until)
            elif any(g.dist(e,h)<950 for e in hostiles for h in heroes):
                self.log('equipment_transfer_aborted',clock=now,code=p['code'],reason='enemy_approach')
                self.release(cast_until)
                return False
            elif now-p['started']<3:return False
            else:
                self.log('equipment_transfer_unconfirmed',clock=now,code=p['code'])
                self.release(cast_until)
        # Never arrange an inventory swap through combat, pullback, or spell casting.
        if any(g.dist(e,h)<950 for e in hostiles for h in heroes):return False
        dk=next((u for u in heroes if u.type=='Udea' and bags[u.handle] is not None),None)
        if dk:
            for donor in heroes:
                if donor.handle==dk.handle:continue
                for slot,code in enumerate(bags[donor.handle] or []):
                    if code in BLUE_POTIONS and g.dist(donor,dk)<350 and can_receive(dk,bags[dk.handle],code):
                        return self.transfer(g,donor,slot,dk,bags,now,cast_until)
        # One blood potion per ranged hero; never take their only bottle.
        # Shared by training preparation and ordinary safe inventory management.
        receivers=sorted(heroes,key=lambda u:HEALTH_HEROES.index(u.type) if u.type in HEALTH_HEROES else 2)
        for receiver in receivers:
            for donor in heroes:
                if donor.handle==receiver.handle:continue
                for slot,code in enumerate(bags[donor.handle] or []):
                    if code not in HEALTH_POTIONS:continue
                    if (can_release(donor,bags[donor.handle],code)
                        and supply_receiver(receiver,bags[receiver.handle],code)
                        and can_receive(receiver,bags[receiver.handle],code)
                        and g.dist(donor,receiver)<350
                        and all(now>=cast_until.get(u.handle,0) for u in (donor,receiver))):
                        return self.transfer(g,donor,slot,receiver,bags,now,cast_until)
        # Give Lich the first scroll, then balance extras across living heroes.
        known=[h for h in heroes if bags[h.handle] is not None]
        for receiver in sorted(known,key=lambda h:scroll_priority(h,bags[h.handle])):
            count=scroll_priority(receiver,bags[receiver.handle])[0]
            for donor in sorted(known,key=lambda h:-scroll_priority(h,bags[h.handle])[0]):
                if donor.handle==receiver.handle:continue
                donor_count=scroll_priority(donor,bags[donor.handle])[0]
                if not (donor_count>count+1 or receiver.type=='Ulic' and count==0 and donor_count>0):continue
                code=next(c for c in bags[donor.handle] if c in HEALING_SCROLLS)
                if (can_receive(receiver,bags[receiver.handle],code) and g.dist(donor,receiver)<350
                    and all(now>=cast_until.get(u.handle,0) for u in (donor,receiver))):
                    return self.transfer(g,donor,bags[donor.handle].index(code),receiver,bags,now,cast_until)
        if potions_only:return False
        # Clear role-specific gear first; the freed slots allow full opening
        # bags to hand over circlets without dropping or selling anything.
        for donor in heroes:
            for slot,code in enumerate(bags[donor.handle] or []):
                owner=gear_owner(code)
                if owner not in {'Udea','Nbrn'} or donor.type==owner:continue
                receiver=next((h for h in heroes if h.type==owner and
                    can_receive(h,bags[h.handle],code) and g.dist(donor,h)<350),None)
                if receiver and self.transfer(g,donor,slot,receiver,bags,now,cast_until):return True
        lich=next((u for u in heroes if u.type=='Ulic' and bags[u.handle] is not None),None)
        if not lich:return False
        bag=bags[lich.handle]
        incoming=[(u,i,c) for u in heroes if u is not lich
                  for i,c in enumerate(bags[u.handle] or []) if c in LICH_ITEMS]
        if not potions_only and 'ocor' not in bag and 'sror' not in bag and None not in bag:
            # Reserve the orb even if a legacy/full inventory already exists.
            # Otherwise keep every equipped item; overflow remains with teammates.
            slot=next((i for i in reversed(range(len(bag))) if bag[i] not in {'ocor','stwp','rnec'}|HEALTH_POTIONS|HEALING_SCROLLS),None)
            if slot is not None:
                receiver=next((u for u in heroes if u is not lich and can_receive(u,bags[u.handle],bag[slot]) and g.dist(u,lich)<350),None)
                if receiver:return self.transfer(g,lich,slot,receiver,bags,now,cast_until)
            return False
        for donor,slot,code in incoming:
            if g.dist(donor,lich)<350 and can_receive(lich,bag,code):
                return self.transfer(g,donor,slot,lich,bags,now,cast_until)
        return False

    def transfer(self,g,donor,slot,receiver,bags,now,cast_until):
        if any(now<cast_until.get(u.handle,0) for u in (donor,receiver)):return False
        code=bags[donor.handle][slot]
        key=(donor.handle,tuple(bags[donor.handle]),receiver.handle,tuple(bags[receiver.handle]),slot)
        attempts=self.attempts.get(key,0)
        if attempts>=3:return False
        self.attempts[key]=attempts+1
        from_count=bags[donor.handle].count(code);to_count=bags[receiver.handle].count(code)
        # give_item walks the donor to the receiver. Keep the receiver still
        # and reserve BOTH heroes until inventory observation or timeout.
        if hasattr(g,'hold'):g.hold(receiver)
        receipt=g.give_item(donor,slot,receiver)
        self.log('equipment_transfer_attempt',clock=now,code=code,from_hero=donor.type,to_hero=receiver.type,accepted=bool(receipt),attempt=attempts+1)
        self.pending=dict(donor=donor.handle,receiver=receiver.handle,code=code,started=now,
                          from_count=from_count,to_count=to_count,lock_until=now+3.1)
        if receipt:
            cast_until[donor.handle]=now+3.1
            cast_until[receiver.handle]=now+3.1
        return bool(receipt)
