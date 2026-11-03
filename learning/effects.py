"""Observable transition facts, without causal attribution or shaped rewards."""
import math


def transition_facts(action, before, after):
    old={tuple(u['handle']):u for u in before['units']}
    new={tuple(u['handle']):u for u in after['units']}
    facts=dict(causally_attributed=False,elapsed_game_seconds=after['clock']-before['clock'])
    if before['resources'] is not None and after['resources'] is not None:
        facts['resource_deltas']={k:after['resources'][k]-v for k,v in before['resources'].items()
                                 if v is not None and after['resources'][k] is not None}
    h=tuple(action.get('unit',()))
    if h in old and h in new:
        a,b=old[h],new[h]
        if all(u[k] is not None for u in (a,b) for k in ('x','y')):
            facts['source_displacement']=math.hypot(b['x']-a['x'],b['y']-a['y'])
        facts['source_alive_after']=b['alive']
    target=tuple(action.get('target',()))
    if target in old and target in new and old[target]['hp'] is not None and new[target]['hp'] is not None:
        facts['visible_target_hp_delta']=new[target]['hp']-old[target]['hp']
    if action['op'] in ('build','train'):
        candidates=[u for key,u in new.items() if key not in old and u['owner']==1 and u['type']==action['code']]
        if action['op']=='build':
            candidates=[u for u in candidates if u['x'] is not None and u['y'] is not None
                        and math.hypot(u['x']-action['x'],u['y']-action['y'])<=96]
        facts['matching_new_own_handles']=[u['handle'] for u in candidates]
        facts['producer_queue_observed']=any(p['building']==action['unit'] and action['code'] in p['queue']
                                             for p in after['production'])
    return facts
