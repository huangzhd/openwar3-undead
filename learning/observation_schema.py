"""Closed observation schema for offline inputs; unknown fields fail closed."""
import math
from learning.actions import identity
from learning.trajectory import RESOURCE_FIELDS, UNIT_FIELDS


class ObservationError(ValueError):
    pass


def require(condition, message):
    if not condition:raise ObservationError(message)


def fields(value, expected):
    require(type(value) is dict and set(value)==set(expected), 'unexpected_observation_fields')


def number(value, *, nullable=True, minimum=None):
    if value is None and nullable:return
    require(type(value) in (int,float) and math.isfinite(value), 'invalid_observation_number')
    require(minimum is None or value>=minimum, 'invalid_observation_range')


def code(value, nullable=True):
    require(value is None and nullable or type(value) is str and len(value)==4 and value.isascii(), 'invalid_observation_code')


def unit(value):
    require(type(value) is dict, 'invalid_unit')
    own=value.get('owner')==1
    fields(value, ('handle','type','owner','alive',*UNIT_FIELDS,*(('inventory','abilities') if own else ())))
    require(identity(value['handle']), 'invalid_unit_handle')
    require(type(value['owner']) is int and 0<=value['owner']<16, 'invalid_unit_owner')
    require(type(value['alive']) is bool, 'invalid_unit_alive')
    code(value['type'])
    for key in UNIT_FIELDS:number(value[key])
    if own:
        items=value['inventory']
        require(items is None or type(items) is list and len(items)==6, 'invalid_inventory')
        for item in items or ():code(item)
        skills=value['abilities']
        require(skills is None or type(skills) is list and len(skills)<=128, 'invalid_abilities')
        for skill in skills or ():
            fields(skill,('code','level','cooldown'));code(skill['code'])
            number(skill['level']);number(skill['cooldown'])


def validate(observation, version):
    require(version in ('strict-p1-observation-v1','strict-p1-observation-v2'), 'unsupported_observation_version')
    expected=('player','clock','resources','units','production','last_seen')
    if version.endswith('v2'):expected+=('tree_sightings',)
    fields(observation,expected)
    require(type(observation['player']) is int and observation['player']==1, 'non_p1_observation')
    number(observation['clock'],nullable=False,minimum=0)
    resources=observation['resources']
    if resources is not None:
        fields(resources,RESOURCE_FIELDS)
        for v in resources.values():number(v)
    units=observation['units']
    require(type(units) is list and len(units)<=8192,'invalid_units')
    handles=set();own=set()
    for row in units:
        unit(row);h=tuple(row['handle']);require(h not in handles,'duplicate_unit_handle');handles.add(h)
        if row['owner']==1:own.add(h)
    production=observation['production']
    require(type(production) is list,'invalid_production')
    for row in production:
        fields(row,('building','kind','queue','progress'))
        require(identity(row['building']) and tuple(row['building']) in own,'unowned_production')
        require(row['kind'] in (None,'queue','construction','upgrade'),'invalid_production_kind')
        require(type(row['queue']) is list and len(row['queue'])<=7,'invalid_queue')
        for product in row['queue']:code(product)
        number(row['progress'])
    memory=observation['last_seen'];require(type(memory) is list,'invalid_memory');seen=set()
    for row in memory:
        fields(row,('last_seen_clock','unit'));unit(row['unit'])
        require(row['unit']['owner']!=1,'owned_unit_in_enemy_memory')
        number(row['last_seen_clock'],nullable=False,minimum=0)
        require(row['last_seen_clock']<=observation['clock'],'future_enemy_memory')
        h=tuple(row['unit']['handle']);require(h not in seen,'duplicate_enemy_memory');seen.add(h)
    if version.endswith('v2'):
        trees=observation['tree_sightings'];require(type(trees) is list and len(trees)<=64,'invalid_tree_sightings');seen=set()
        for row in trees:
            fields(row,('handle','type','x','y','seen_clock'))
            require(identity(row['handle']),'invalid_tree_handle');code(row['type'])
            number(row['x'],nullable=False);number(row['y'],nullable=False)
            number(row['seen_clock'],nullable=False,minimum=0)
            require(row['seen_clock']<=observation['clock'],'future_tree_sighting')
            h=tuple(row['handle']);require(h not in seen,'duplicate_tree_sighting');seen.add(h)
    return observation
