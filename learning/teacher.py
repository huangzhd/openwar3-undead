"""Read-only translation of a subset of issued SDK orders into primitive labels."""
from learning.actions import SCHEMA, validate, preflight, MAX_AGE
from learning.dataset import native_payload
from learning import economy_actions, hero_skills, unit_spells

POLICY='rule_teacher'
TRAJECTORY='dayuan-teacher-trajectory-v1'
ACTION='dayuan-teacher-orders-v1'


def translate(native):
    """No inferred buyer, research level, historical tree or unsupported queue."""
    op,code=native['op'],native['code']
    action=dict(schema=SCHEMA,unit=native['unit'])
    if op=='point' and code in (851986,851983):
        action.update(op='move' if code==851986 else 'attack_move',x=native['x'],y=native['y'])
    elif op=='target' and code in (851971,852018):
        action.update(op='attack' if code==851971 else 'gather_gold',target=native['target'])
    elif op=='target' and code in {v[2] for v in unit_spells.SPELLS.values()}:
        skill=next(k for k,v in unit_spells.SPELLS.items() if v[2]==code)
        action.update(op='cast_unit',skill=skill,target=native['target'])
    elif op=='immediate' and code in (851972,851993):
        action.update(op='stop' if code==851972 else 'hold')
    elif op in ('immediate','build','learn') and type(code) is int and 0<=code<2**32:
        symbol=code.to_bytes(4,'big').decode('ascii',errors='replace')
        if op=='build' and symbol in economy_actions.BUILD_CODES:
            action.update(op='build',code=symbol,x=native['x'],y=native['y'])
        elif op=='learn' and symbol in hero_skills.SKILLS:
            action.update(op='learn_skill',skill=symbol)
        elif op=='immediate' and symbol in economy_actions.TRAIN_SOURCES:
            action.update(op='train',code=symbol)
        elif op=='immediate' and symbol in economy_actions.HERO_CODES:
            action.update(op='train_hero',code=symbol)
        elif op=='immediate' and symbol in economy_actions.HALL_UPGRADES:
            action.update(op='upgrade_hall',code=symbol)
        else:return None
    elif op=='use_item' and native['mode'] in (0,1):
        action.update(op='use_item_now' if native['mode']==0 else 'use_item_point',
                      slot=native['slot'],item=native['item_at_issue'])
        if native['mode']==1:action.update(x=native['x'],y=native['y'])
    else:return None
    try:action=validate(action)
    except ValueError:return None
    return action if native_payload(action)==native else None


def capture(call, native, decision, issue, bounds):
    if decision is None:
        return None,'outside_teacher_tick'
    if native['op']!='use_item' and any(call.args[9:11]):
        return None,'unsupported_queue_or_mode'
    if native['op'] not in ('point','build','use_item') and any(call.args[7:9]):
        return None,'unexpected_point_arguments'
    if not 0<=issue['clock']-decision['clock']<=MAX_AGE:
        return None,'stale_teacher_tick'
    action=translate(native)
    if action is None:return None,'unsupported_order_or_arguments'
    for name,frame in (('tick',decision),('issue',issue)):
        reason=preflight(action,frame,bounds)
        if reason!='allowed':return None,name+'_'+reason
    return action,'candidate'
