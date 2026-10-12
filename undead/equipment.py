"""Safe hero equipment handoffs; inventory observations confirm every transfer."""
import json
from bootstrap import UPSTREAM

BLUE_POTIONS={'pman','pgma','mnst'} # Mana Stone follows DK mana-supply ownership.
CLAWS={'rat3':3,'rat6':6,'rat9':9,'ratc':12,'ratf':15}
# Lich gains attack from intelligence and attack speed from agility. The pinned
# local item catalog supplies numeric bonuses; these additional item abilities
# carry attack/orb or endurance-aura bonuses not expanded by that catalog.
_ITEM_CATALOG=json.loads((UPSTREAM/'data/game/items.json').read_text(encoding='utf-8'))
LICH_ITEMS={'pnvl','pnvu'}|set(CLAWS)|{'bspd','ajen','ocor','odef','ofir','ofro','olig','oli2','oslo','oven','ward'}|{
    code for code,row in _ITEM_CATALOG.items() if not row.get('powerup',False)
    and any(row.get('effects',{}).get(effect,0)>0
            for effect in ('attack','attack_speed','int','agi','aura_trueshot'))}



def can_receive(hero,bag,code):
    if bag is None:return False
    reserve=hero.type=='Ulic' and 'ocor' not in bag and code!='ocor'
    return bag.count(None)>=(2 if reserve else 1)



class Equipment:
    def __init__(self,log):
        self.log=log
        self.pending=None
        self.attempts={}

    def tick(self,g,army,hostiles,now,cast_until):
        heroes=[u for u in army if u.is_hero]
        bags={u.handle:g.inventory(u) for u in heroes}
        p=self.pending
        if p:
            donor=next((u for u in heroes if u.handle==p['donor']),None)
            receiver=next((u for u in heroes if u.handle==p['receiver']),None)
            a=bags.get(p['donor']);b=bags.get(p['receiver'])
            if a is not None and b is not None and a.count(p['code'])<p['from_count'] and b.count(p['code'])>p['to_count']:
                self.log('equipment_transfer_confirmed',clock=now,code=p['code'],from_hero=donor.type,to_hero=receiver.type,inventory=b)
                self.pending=None
            elif now-p['started']<3:return False
            else:
                self.log('equipment_transfer_unconfirmed',clock=now,code=p['code'])
                self.pending=None
        # Never arrange an inventory swap through combat, pullback, or spell casting.
        if any(g.dist(e,h)<950 for e in hostiles for h in heroes):return False
        dk=next((u for u in heroes if u.type=='Udea' and bags[u.handle] is not None),None)
        if dk:
            for donor in heroes:
                if donor.handle==dk.handle:continue
                for slot,code in enumerate(bags[donor.handle] or []):
                    if code in BLUE_POTIONS and g.dist(donor,dk)<350 and can_receive(dk,bags[dk.handle],code):
                        return self.transfer(g,donor,slot,dk,bags,now,cast_until)
        lich=next((u for u in heroes if u.type=='Ulic' and bags[u.handle] is not None),None)
        if not lich:return False
        bag=bags[lich.handle]
        incoming=[(u,i,c) for u in heroes if u is not lich
                  for i,c in enumerate(bags[u.handle] or []) if c in LICH_ITEMS]
        if 'ocor' not in bag and None not in bag:
            # Reserve the orb even if a legacy/full inventory already exists.
            # Otherwise keep every equipped item; overflow remains with teammates.
            slot=next((i for i in reversed(range(len(bag))) if bag[i] not in {'ocor','stwp','rnec'}),None)
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
        receipt=g.give_item(donor,slot,receiver)
        self.log('equipment_transfer_attempt',clock=now,code=code,from_hero=donor.type,to_hero=receiver.type,accepted=bool(receipt),attempt=attempts+1)
        self.pending=dict(donor=donor.handle,receiver=receiver.handle,code=code,started=now,
                          from_count=bags[donor.handle].count(code),to_count=bags[receiver.handle].count(code))
        if receipt:
            cast_until[donor.handle]=now+2
            cast_until[receiver.handle]=now+2
        return bool(receipt)
