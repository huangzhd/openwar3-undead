"""Framework-independent model tensors and current-observation pointer actions.

This is an adapter, not a trained policy. No policy rules or fallback decisions.
"""
import copy
from dataclasses import dataclass
import math
import hashlib
import json

from learning.actions import BASE_OPS,SCHEMA,LEGACY_SCHEMA,SCHEMA_OPS,checked_bounds,validate as validate_action
from learning.economy_actions import BUILD_CODES,TRAIN_SOURCES
from learning.hero_skills import SKILLS
from learning.unit_spells import BUFFS
from learning.research import MAX_LEVEL
from learning.items import ITEMS
from learning.observation_schema import validate as validate_observation
from learning.trajectory import RESOURCE_FIELDS,UNIT_FIELDS

INPUT_SCHEMA='dayuan-model-input-v8'
DECISION_SCHEMA='dayuan-model-decision-v9'
# Stable categorical indices: extending these requires an explicit contract change.
OPERATIONS=('wait','move','attack_move','attack','stop','hold','gather_gold','build','train','inspect_trees','gather_lumber','train_hero','learn_skill','cast_unit','upgrade_hall','inspect_research','research','buy_item','use_item_now','use_item_point')
PRODUCTS=('uaco','uaod','ucry','ugho','ugrv','usep','utom','uzig','Udea','Ulic','Udre','Ucrl','unp1','unp2','Rura','Rucr','Ruwb')


def model_contract():
    contract=dict(input_schema=INPUT_SCHEMA,decision_schema=DECISION_SCHEMA,
                  operations=list(OPERATIONS),products=list(PRODUCTS),skills=list(SKILLS),skill_point_scale=10,
                  item_codes=list(ITEMS),inventory_slots=6,item_slot_base=0,research_codes=list(MAX_LEVEL),research_level_scales=list(MAX_LEVEL.values()),research_level_encoding='one_based_goal',research_age_scale=60,own_spell_buffs=list(BUFFS),resource_fields=list(RESOURCE_FIELDS),
                  unit_fields=list(UNIT_FIELDS),coordinates='normalized_public_bounds',unknowns='values_and_known',
                  resource_scales=[1000,1000,100,100,1000,1000],
                  unit_scales=[1,1,2000,2000,1000,1000,10],code_encoding='four_ascii_bytes_divided_by_255')
    contract['sha256']=hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return contract


def require(condition,reason):
    if not condition:raise ValueError(reason)


def scalar(value,scale=1):return (0.,0) if value is None else (value/scale,1)
def vector(values):
    pairs=[scalar(v,s) for v,s in values]
    require(all(math.isfinite(v) for v,_ in pairs),'nonfinite_model_feature')
    return dict(values=[v for v,_ in pairs],known=[m for _,m in pairs])
def code_vector(code):return vector([(ord(c),255) for c in code] if code is not None else [(None,255)]*4)


@dataclass(frozen=True)
class EncodedObservation:
    features: dict
    entities: tuple
    trees: tuple
    bounds: tuple
    action_schema: str
    supported: tuple


def encode_observation(observation,context,version):
    validate_observation(observation,version)
    bounds=checked_bounds(context['bounds']);xmin,xmax,ymin,ymax=bounds
    require(xmax-xmin>=1 and ymax-ymin>=1,'invalid_model_map_extent')
    schema=context['schema'];require(schema in SCHEMA_OPS,'unsupported_action_schema')
    supported=context.get('supported_operations')
    if supported is None:supported=SCHEMA_OPS[schema]
    require(type(supported) in (tuple,list) and all(op in SCHEMA_OPS[schema] for op in supported),'unsupported_operation')
    if schema==LEGACY_SCHEMA:require(all(op in BASE_OPS for op in supported),'legacy_operation_mismatch')
    def position(v,axis):
        if v is None:return None
        low,high=(xmin,xmax) if axis=='x' else (ymin,ymax)
        return (v-(low+high)/2)/((high-low)/2)
    points={tuple(r['unit']):r['points'] for r in observation.get('hero_skill_points',())}
    statuses={tuple(r['unit']):r['buffs'] for r in observation.get('own_spell_status',())}
    def entity(u):
        pairs=[(position(u[k],k),1) if k in ('x','y') else (u[k],2000 if k.startswith('hp') else 1000 if k.startswith('mana') else 10)
               for k in UNIT_FIELDS]
        row=dict(type=code_vector(u['type']),state=vector(pairs),alive=int(u['alive']),
                 relation=[int(u['owner']==1),int(u['owner']==2),int(u['owner'] not in (1,2))])
        if u['owner']==1:
            buffs=statuses.get(tuple(u['handle']))
            row['spell_buffs']=vector([(None if buffs is None else int(b in buffs),1) for b in BUFFS])
            row.update(skill_points=vector([(points.get(tuple(u['handle'])),10)]),
                       inventory_known=int(u['inventory'] is not None),
                       inventory=[code_vector(v) for v in u['inventory'] or [None]*6],
                       abilities_known=int(u['abilities'] is not None),
                       abilities=[dict(type=code_vector(a['code']),state=vector([(a['level'],10),(a['cooldown'],60)])) for a in u['abilities'] or []])
        return row
    entities=observation['units'];trees=observation.get('tree_sightings',[])
    entity_indices={tuple(u['handle']):i for i,u in enumerate(entities)}
    resources=observation['resources'] or {k:None for k in RESOURCE_FIELDS}
    features=dict(schema=INPUT_SCHEMA,clock=observation['clock']/3600,
        resources=vector([(resources[k],100 if k.startswith('food') else 1000) for k in RESOURCE_FIELDS]),
        entities=[entity(u) for u in entities],
        production=[dict(building=entity_indices[tuple(p['building'])],
                         kind=[int(p['kind']==k) for k in ('queue','construction','upgrade')],
                         kind_known=int(p['kind'] is not None),queue=[code_vector(c) for c in p['queue']],
                         progress=vector([(p['progress'],1)])) for p in observation['production']],
        memory=[dict(entity=entity(m['unit']),age=(observation['clock']-m['last_seen_clock'])/60) for m in observation['last_seen']],
        trees=[dict(type=code_vector(t['type']),state=vector([(position(t['x'],'x'),1),(position(t['y'],'y'),1),
                    (observation['clock']-t['seen_clock'],60)])) for t in trees],
        supported_operations=[int(op in supported) for op in OPERATIONS])
    levels=observation.get('research_levels',{})
    features['research']=[vector([(levels.get(c,{}).get('level'),MAX_LEVEL[c]),
                                  ((observation['clock']-levels[c]['clock']) if c in levels else None,60)]) for c in MAX_LEVEL]
    return EncodedObservation(features,tuple(tuple(u['handle']) for u in entities),
                              tuple(tuple(t['handle']) for t in trees),tuple(bounds),schema,tuple(supported))


def decode_decision(encoded,decision):
    require(type(decision) is dict and decision.get('schema')==DECISION_SCHEMA,'invalid_model_decision_schema')
    require(decision.get('contract_sha256')==model_contract()['sha256'],'model_contract_mismatch')
    index=decision.get('op');require(type(index) is int and 0<=index<len(OPERATIONS),'invalid_operation_index')
    op=OPERATIONS[index];require(op in encoded.supported,'operation_not_supported')
    fields={'schema','contract_sha256','op'}
    if op not in ('wait','inspect_trees','inspect_research'):fields.add('unit')
    if op in ('attack','gather_gold','cast_unit','buy_item'):fields.add('target')
    if op=='buy_item':fields.add('item')
    if op in ('use_item_now','use_item_point'):fields.update(('slot','item'))
    if op=='gather_lumber':fields.add('tree')
    if op in ('move','attack_move','build','inspect_trees','use_item_point'):fields.add('point')
    if op in ('build','train','train_hero','upgrade_hall','inspect_research','research'):fields.add('product')
    if op=='research':fields.add('level')
    if op in ('learn_skill','cast_unit'):fields.add('skill')
    require(set(decision)==fields,'unexpected_model_decision_fields')
    action=dict(schema=encoded.action_schema,op=op)
    if 'slot' in fields:action['slot']=decision['slot']
    if 'item' in fields:
        idx=decision['item']
        require(type(idx) is int and 0<=idx<len(ITEMS),'invalid_item_index')
        action['item']=ITEMS[idx]
    if 'level' in fields:action['level']=decision['level']
    if 'skill' in fields:
        idx=decision['skill']
        require(type(idx) is int and 0<=idx<len(SKILLS),'invalid_skill_index')
        action['skill']=SKILLS[idx]
    for field,mapping in (('unit',encoded.entities),('target',encoded.entities),('tree',encoded.trees)):
        if field not in fields:continue
        idx=decision[field];require(type(idx) is int and 0<=idx<len(mapping),'invalid_entity_pointer')
        action['target' if field=='tree' else field]=list(mapping[idx])
    if 'product' in fields:
        idx=decision['product'];require(type(idx) is int and 0<=idx<len(PRODUCTS),'invalid_product_index')
        action['code']=PRODUCTS[idx]
    if 'point' in fields:
        point=decision['point'];require(type(point) is list and len(point)==2
            and all(type(v) in (float,int) and math.isfinite(v) and -1<=v<=1 for v in point),'invalid_model_point')
        xmin,xmax,ymin,ymax=encoded.bounds
        action.update(x=xmin+(point[0]+1)*(xmax-xmin)/2,y=ymin+(point[1]+1)*(ymax-ymin)/2)
    return validate_action(action)


def encode_action(encoded,action):
    action=validate_action(action);op=action['op'];require(op in encoded.supported,'operation_not_supported')
    result=dict(schema=DECISION_SCHEMA,contract_sha256=model_contract()['sha256'],op=OPERATIONS.index(op))
    for field in ('unit','target'):
        if field not in action:continue
        tree=field=='target' and op=='gather_lumber';mapping=encoded.trees if tree else encoded.entities
        try:result['tree' if tree else field]=mapping.index(tuple(action[field]))
        except ValueError as exc:raise ValueError('action_entity_not_observed') from exc
    if 'code' in action:result['product']=PRODUCTS.index(action['code'])
    if 'slot' in action:result['slot']=action['slot']
    if 'item' in action:result['item']=ITEMS.index(action['item'])
    if 'level' in action:result['level']=action['level']
    if 'skill' in action:result['skill']=SKILLS.index(action['skill'])
    if 'x' in action:
        xmin,xmax,ymin,ymax=encoded.bounds
        result['point']=[2*(action['x']-xmin)/(xmax-xmin)-1,2*(action['y']-ymin)/(ymax-ymin)-1]
    decode_decision(encoded,result)  # Validate pointers, product and coordinate range.
    return result


def prepare_command(frame,predict):
    """Call a supplied model once; caller passes the result to env.step()."""
    require(frame.get('done') is False and frame.get('token',{}).get('player')==1,'active_p1_frame_required')
    observation=frame['observation']
    version=('strict-p1-observation-v5' if 'research_levels' in observation else
             'strict-p1-observation-v4' if 'own_spell_status' in observation else
             'strict-p1-observation-v3' if 'hero_skill_points' in observation else
             'strict-p1-observation-v2' if 'tree_sightings' in observation else 'strict-p1-observation-v1')
    encoded=encode_observation(observation,frame['action_context'],version)
    token=copy.deepcopy(frame['token'])
    decision=predict(copy.deepcopy(encoded.features))
    return dict(kind='primitive',token=token,action=decode_decision(encoded,decision))


def encode_sample(sample,context,version):
    current=encode_observation(sample['input'],context,version)
    following=encode_observation(sample['next_observation'],context,version)
    return dict(input=current.features,label=encode_action(current,sample['action']),
                next_input=following.features,step_id=sample['step_id'],
                observation_id=sample['observation_id'],next_observation_id=sample['next_observation_id'],
                next_sample_contiguous=sample['next_sample_contiguous'],
                terminated=sample['terminated'],truncated=sample['truncated'],terminal_reward=sample['terminal_reward'])
