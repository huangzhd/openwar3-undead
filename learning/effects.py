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
        if action['op']=='learn_skill':
            from learning.hero_skills import unspent, learned_rank
            for suffix,obs,u in (('before',before,a),('after',after,b)):
                points=unspent(obs,action['unit'])
                facts['skill_points_'+suffix]=points
                facts['skill_rank_'+suffix]=learned_rank(u,action['skill'],points)
    target=tuple(action.get('target',()))
    if action['op']=='cast_unit':
        from learning.unit_spells import buffs
        for suffix,obs,units in (('before',before,old),('after',after,new)):
            caster=units.get(h)
            facts['caster_mana_'+suffix]=caster['mana'] if caster else None
            rows=[r for r in (caster['abilities'] or []) if r['code']==action['skill']] if caster else []
            facts['spell_cooldown_'+suffix]=rows[0]['cooldown'] if len(rows)==1 else None
            if action['skill']=='AUfu':
                statuses=buffs(obs,action['target'])
                facts['target_frost_armor_'+suffix]=None if statuses is None else 'BUfa' in statuses
    if target in old and target in new and old[target]['hp'] is not None and new[target]['hp'] is not None:
        facts['visible_target_hp_delta']=new[target]['hp']-old[target]['hp']
    if action['op'] in ('use_item_now','use_item_point'):
        for side,units in (('before',old),('after',new)):
            hero=units.get(h)
            bag=hero.get('inventory') if hero and hero['owner']==1 else None
            facts['inventory_known_'+side]=bag is not None
            facts['slot_item_'+side]=None if bag is None else bag[action['slot']]
            facts['matching_item_count_'+side]=None if bag is None else bag.count(action['item'])
    if action['op']=='buy_item':
        gains=[]
        for key,u in new.items():
            earlier=old.get(key)
            if u['owner']!=1 or not earlier or earlier['owner']!=1:continue
            bag=u.get('inventory');previous=earlier.get('inventory')
            if bag is not None and previous is not None and bag.count(action['item'])>previous.count(action['item']):
                gains.append(list(key))
        facts['observed_item_gainers']=gains
        facts['intended_item_gain_observed']=action['target'] in gains
    if action['op'] in ('inspect_research','research'):
        for side,obs in (('before',before),('after',after)):
            sample=obs.get('research_levels',{}).get(action['code'],{})
            facts['research_level_'+side]=sample.get('level')
            facts['research_read_clock_'+side]=sample.get('clock')
        if action['op']=='research':
            facts['research_queued_after']=any(p['building']==action['unit'] and action['code'] in p['queue']
                                               for p in after['production'])
    if action['op']=='upgrade_hall':
        facts['later_hall_type']=new[h]['type'] if h in new and new[h]['owner']==1 else None
        facts['upgrade_in_progress_observed']=any(
            p['building']==action['unit'] and p['kind']=='upgrade' and action['code'] in p['queue']
            for p in after['production'])
    if action['op'] in ('build','train','train_hero'):
        candidates=[u for key,u in new.items() if key not in old and u['owner']==1 and u['type']==action['code']]
        if action['op']=='build':
            candidates=[u for u in candidates if u['x'] is not None and u['y'] is not None
                        and math.hypot(u['x']-action['x'],u['y']-action['y'])<=96]
        facts['matching_new_own_handles']=[u['handle'] for u in candidates]
        facts['producer_queue_observed']=any(p['building']==action['unit'] and action['code'] in p['queue']
                                             for p in after['production'])
    return facts
