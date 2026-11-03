"""Own Tomb of Relics purchases. The native shop selects its recipient."""
import math
from functools import lru_cache
from learning.economy_actions import completed, known_number, HALLS
from learning.hero_skills import KITS

ITEMS=('rnec','dust','skul','phea','pman','stwp','ocor','shea')
BUY_RANGE=300
EXCLUSIVE_RANGE=900
USE_ABILITIES={'phea':'AIh1','pman':'AIm1','shea':'AIha','dust':'AItb','stwp':'AItp'}
NO_TARGET_ITEMS=('phea','pman','shea','dust')


@lru_cache(maxsize=1)
def catalog():
    import w3paths
    from w3slk import read_slk
    result={}
    for row in read_slk(w3paths.game_data('ItemData.slk')):
        if row.get('itemID') in ITEMS:
            result[row['itemID']]={name:int(row[key]) for name,key in
                                   [('gold','goldcost'),('lumber','lumbercost'),('earliest','stockStart')]}
    if set(result)!=set(ITEMS) or any(v<0 for entry in result.values() for v in entry.values()):
        raise ValueError('Incomplete public item catalog')
    return result


def distance(a,b):
    if any(type(u[k]) not in (int,float) or not math.isfinite(u[k]) for u in (a,b) for k in ('x','y')):
        return None
    return math.hypot(a['x']-b['x'], a['y']-b['y'])


def recipient_reason(shop, hero, observation):
    if shop['type']!='utom' or shop['owner']!=1 or not shop['alive']:
        return 'own_relic_shop_required'
    if not hero or hero['owner']!=1 or hero['type'] not in KITS or not hero['alive']:
        return 'own_undead_hero_required'
    abilities={a['code'] for a in hero['abilities'] or [] if known_number(a['level']) and a['level']>0}
    if not {'AInv','AHer'}<=abilities or hero['inventory'] is None or None not in hero['inventory']:
        return 'hero_inventory_unavailable_or_full'
    d=distance(shop,hero)
    if d is None or d>BUY_RANGE:
        return 'intended_hero_not_in_purchase_range'
    for other in observation['units']:
        if other['owner']!=1 or not other['alive'] or other['handle'] in (hero['handle'],shop['handle']):
            continue
        # Engine buy has no recipient argument. Treat unknown unit/detail and
        # nearby additional heroes or inventory bearers as ambiguous.
        if (other['type'] is None or other['type'][:1].isupper() or other['abilities'] is None
                or any(a['code']=='AInv' for a in other['abilities'])):
            d=distance(shop,other)
            if d is None or d<=EXCLUSIVE_RANGE:
                return 'shop_recipient_ambiguous'
    return 'allowed'


def buy_reason(action, observation, shop, hero):
    reason=recipient_reason(shop,hero,observation)
    if reason!='allowed':return reason
    prod=observation['production']
    if not completed(shop,prod) or not any(a['code']=='Apit' and known_number(a['level']) and a['level']>0
                                            for a in shop['abilities'] or []):
        return 'shop_not_ready'
    code=action['item']
    ready={u['type'] for u in observation['units'] if u['owner']==1 and u['alive'] and completed(u,prod)}
    if (code=='skul' and 'ugrv' not in ready or code in ('shea','ocor') and 'unp2' not in ready
            or code in ('phea','pman','stwp') and not ready.intersection(HALLS[1:])):
        return 'item_prerequisites_missing'
    cost=catalog()[code]
    if observation['clock']<cost['earliest']:return 'item_before_initial_stock'
    resources=observation.get('resources') or {}
    for resource in ('gold','lumber'):
        if not known_number(resources.get(resource)):return 'resources_unknown'
        if resources[resource]<cost[resource]:return 'insufficient_'+resource
    return 'allowed'


def use_reason(action, observation, hero):
    if hero['owner']!=1 or not hero['alive'] or hero['type'] not in KITS:
        return 'own_undead_hero_required'
    bag=hero['inventory']
    code=action['item']
    if bag is None or len(bag)!=6 or bag[action['slot']]!=code:
        return 'expected_item_not_in_slot'
    rows=hero['abilities'] or []
    known={a['code'] for a in rows if known_number(a['level']) and a['level']>0}
    if not {'AInv','AHer',USE_ABILITIES[code]}<=known:
        return 'item_ability_unknown'
    skill=[a for a in rows if a['code']==USE_ABILITIES[code]]
    if len(skill)!=1 or not known_number(skill[0]['cooldown']) or skill[0]['cooldown']!=0:
        return 'item_cooldown_not_ready'
    if code=='stwp':
        if not any(u['owner']==1 and u['alive'] and u['type'] in HALLS and u['x']==action['x']
                   and u['y']==action['y'] and completed(u,observation['production']) for u in observation['units']):
            return 'portal_requires_ready_own_hall_point'
    return 'allowed'
