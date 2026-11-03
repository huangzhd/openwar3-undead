"""Explicit, bounded P1 primitives. Preflight is not full engine legality.

No raw order IDs, addresses, queue modes or arbitrary SDK method names cross
this boundary. One primitive per decision; replacement orders only.
"""
import copy
import json
import math
import struct

SCHEMA = 'dayuan-primitive-action-v9'
SHOP_SCHEMA = 'dayuan-primitive-action-v8'
RESEARCH_SCHEMA = 'dayuan-primitive-action-v7'
HALL_SCHEMA = 'dayuan-primitive-action-v6'
SPELL_SCHEMA = 'dayuan-primitive-action-v5'
LEARN_SCHEMA = 'dayuan-primitive-action-v4'
HERO_SCHEMA = 'dayuan-primitive-action-v3'
ECONOMY_SCHEMA = 'dayuan-primitive-action-v2'
LEGACY_SCHEMA = 'dayuan-primitive-action-v1'
BASE_OPS = ('wait', 'move', 'attack_move', 'attack', 'stop', 'hold')
from learning import economy_actions, hero_skills, trees, unit_spells, research, items
V2_OPS = BASE_OPS + ('gather_gold', 'build', 'train', 'inspect_trees', 'gather_lumber')
V3_OPS = V2_OPS + ('train_hero',)
V4_OPS = V3_OPS + ('learn_skill',)
V5_OPS = V4_OPS + ('cast_unit',)
V6_OPS = V5_OPS + ('upgrade_hall',)
V7_OPS = V6_OPS + ('inspect_research','research')
V8_OPS = V7_OPS + ('buy_item',)
OPS = V8_OPS + ('use_item_now','use_item_point')
SCHEMA_OPS = {LEGACY_SCHEMA: BASE_OPS, ECONOMY_SCHEMA: V2_OPS, HERO_SCHEMA: V3_OPS, LEARN_SCHEMA: V4_OPS,
              SPELL_SCHEMA: V5_OPS, HALL_SCHEMA: V6_OPS, RESEARCH_SCHEMA: V7_OPS, SHOP_SCHEMA: V8_OPS, SCHEMA: OPS}
MAX_AGE = 8.0  # Game seconds; the real-time engine does not pause for inference.


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def identity(value):
    return (type(value) is list and len(value) == 2
            and all(type(v) is int and 0 < v < 2**32 for v in value))


def validate(action):
    if (type(action) is not dict or type(action.get('schema')) is not str
            or action.get('schema') not in SCHEMA_OPS
            or action.get('op') not in SCHEMA_OPS[action['schema']]):
        raise ValueError('Unsupported primitive schema or operation')
    op = action['op']
    fields = {'schema', 'op'}
    if op not in ('wait', 'inspect_trees', 'inspect_research'):fields.add('unit')
    if op in ('move', 'attack_move', 'build', 'inspect_trees','use_item_point'):fields.update(('x', 'y'))
    if op in ('attack', 'gather_gold', 'gather_lumber', 'cast_unit','buy_item'):fields.add('target')
    if op=='buy_item':fields.add('item')
    if op in ('use_item_now','use_item_point'):fields.update(('item','slot'))
    if op in ('build', 'train', 'train_hero', 'upgrade_hall','inspect_research','research'):fields.add('code')
    if op=='research':fields.add('level')
    if op in ('learn_skill', 'cast_unit'):fields.add('skill')
    if set(action) != fields:
        raise ValueError('Unexpected or missing primitive fields')
    if op in ('use_item_now','use_item_point'):
        if type(action['slot']) is not int or not 0<=action['slot']<6:raise ValueError('Invalid item slot')
        allowed=items.NO_TARGET_ITEMS if op=='use_item_now' else ('stwp',)
        if action['item'] not in allowed:raise ValueError('Unsupported item targeting mode')
    if op=='buy_item' and action['item'] not in items.ITEMS:raise ValueError('Unsupported shop item')
    if op == 'learn_skill' and action['skill'] not in hero_skills.SKILLS:
        raise ValueError('Unsupported hero skill')
    if op == 'cast_unit' and (type(action['skill']) is not str or action['skill'] not in unit_spells.SPELLS):
        raise ValueError('Unsupported unit spell')
    products = {'build':economy_actions.BUILD_CODES, 'train':economy_actions.TRAIN_SOURCES,
                'train_hero':economy_actions.HERO_CODES, 'upgrade_hall':economy_actions.HALL_UPGRADES,
                'research':research.PRODUCERS,'inspect_research':research.PRODUCERS}
    if op in products and (type(action['code']) is not str or action['code'] not in products[op]):
        raise ValueError('Unsupported economic product')
    if op=='research' and (type(action['level']) is not int or not 1<=action['level']<=research.MAX_LEVEL[action['code']]):
        raise ValueError('Invalid target research level')
    for key in ('unit', 'target'):
        if key in action and not identity(action[key]):raise ValueError('Invalid entity handle')
    result = copy.deepcopy(action)
    for key in ('x', 'y'):
        if key in action:
            value = action[key]
            if not finite(value) or abs(value) > 2**20:
                raise ValueError('Invalid primitive coordinate')
            # Store exactly the float32 coordinate sent to the native lane.
            result[key] = struct.unpack('<f', struct.pack('<f', value))[0]
            if op == 'build':result[key] = float(round(result[key]/32)*32)
    return result


def checked_bounds(bounds):
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or not all(finite(v) for v in bounds)
            or not bounds[0] < bounds[1] or not bounds[2] < bounds[3]):
        raise ValueError('Verified public map bounds required')
    return list(bounds)


def receipt_diagnostics(result):
    """Diagnostic-only scalar allowlist; synthetic/missing replies stay unknown."""
    def uint(value):
        return value if type(value) is int and 0 <= value < 2**32 else None
    status = uint(getattr(result, 'status', None))
    native = result is not None and status is not None and status <= 8
    return dict(native_status=status, **{key: uint(getattr(result, key, None)) if native else None
        for key in ('verdict', 'engine_return', 'order_before', 'order_after')})


def preflight(action, observation, bounds, costs=None):
    """Only consult the white-listed observation, never hidden SDK entities."""
    action = validate(action)
    if not isinstance(observation, dict) or observation.get('player') != 1:
        return 'observation_unavailable'
    if action['op'] in ('wait','inspect_research'):return 'allowed'
    if action['op'] == 'inspect_trees':
        xmin, xmax, ymin, ymax = checked_bounds(bounds)
        return 'allowed' if xmin <= action['x'] <= xmax and ymin <= action['y'] <= ymax else 'point_outside_map'
    units = {tuple(u['handle']): u for u in observation['units']}
    unit = units.get(tuple(action['unit']))
    if unit is None or unit['owner'] != 1 or unit['alive'] is not True:
        return 'source_not_owned_alive'
    abilities = unit.get('abilities')
    if abilities is None:return 'source_capabilities_unknown'
    if action['op'] == 'learn_skill':return hero_skills.preflight(action, observation, unit)
    if action['op'] == 'cast_unit':
        return unit_spells.preflight(action, observation, unit, units.get(tuple(action['target'])))
    known = {a['code'] for a in abilities if finite(a.get('level')) and a['level'] > 0}
    if action['op'] in ('use_item_now','use_item_point'):
        if action['op']=='use_item_point':
            xmin,xmax,ymin,ymax=checked_bounds(bounds)
            if not xmin<=action['x']<=xmax or not ymin<=action['y']<=ymax:return 'point_outside_map'
        return items.use_reason(action,observation,unit)
    if action['op']=='buy_item':return items.buy_reason(action, observation, unit, units.get(tuple(action['target'])))
    if action['op']=='research':return research.preflight(action,observation,unit,known)
    if action['op'] == 'gather_lumber':return trees.preflight(action, observation, unit, known)
    if action['op'] in economy_actions.OPS:
        if action['op'] == 'build':
            xmin, xmax, ymin, ymax = checked_bounds(bounds)
            if not xmin <= action['x'] <= xmax or not ymin <= action['y'] <= ymax:return 'point_outside_map'
        return economy_actions.preflight(action, observation, unit, known,
                                         economy_actions.catalog() if costs is None else costs)
    # This version only controls mobile units, including stop/hold.
    if 'Amov' not in known:return 'source_not_mobile'
    if action['op'] in ('attack', 'attack_move') and 'Aatk' not in known:
        return 'source_attack_unknown'
    if action['op'] in ('move', 'attack_move'):
        xmin, xmax, ymin, ymax = checked_bounds(bounds)
        if not xmin <= action['x'] <= xmax or not ymin <= action['y'] <= ymax:
            return 'point_outside_map'
    if action['op'] == 'attack':
        target = units.get(tuple(action['target']))
        # LR/KFAI has exactly one hostile player, P2. No neutral/ally smart orders.
        if target is None or target['owner'] != 2 or target['alive'] is not True:
            return 'target_not_visible_enemy_alive'
        if not finite(target.get('hp')) or target['hp'] <= 0:
            return 'target_not_visible_enemy_alive'
    return 'allowed'


class PrimitiveExecutor:
    """One owned session, using SDK public commands and the existing recorder."""
    def __init__(self, game, recorder, path):
        self.game, self.recorder = game, recorder
        self.bounds = checked_bounds(getattr(game.map(), 'bounds', None))
        self.costs = economy_actions.catalog()
        self.stream = path.open('x', encoding='utf-8')
        self.sequence = 0
        self.pending = []
        self.receipts = []
        self.closed = False
        self.diagnostics = None
        try:
            self.diagnostics = path.with_name('primitive-diagnostics.jsonl').open('x', encoding='utf-8')
            self.write_diagnostic('header', schema='dayuan-primitive-diagnostics-v1',
                                  excluded_from_actor=True, player=1, epoch=recorder.boundary.epoch)
            self.write('header', schema=SCHEMA, player=1, epoch=recorder.boundary.epoch,
                       policy='external_primitives', training_actor_approved=False,
                       bounds=self.bounds, max_decision_age_game_seconds=MAX_AGE,
                       economic_catalog=self.costs, supported_operations=OPS,
                       limitations=['partial_action_space', 'preflight_not_full_engine_legality',
                                    'receipts_and_later_observations_do_not_prove_effects'])
        except BaseException:
            self.stream.close()
            if self.diagnostics is not None:self.diagnostics.close()
            raise

    def write(self, event, **data):
        self.stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False, allow_nan=False)+'\n')
        self.stream.flush()

    def write_diagnostic(self, event, **data):
        self.diagnostics.write(json.dumps(dict(event=event, **data), allow_nan=False)+'\n')
        self.diagnostics.flush()

    def execute(self, action, decision, decision_id):
        action = validate(action)
        self.sequence += 1
        ident = self.sequence
        self.write('request', id=ident, observation_id=decision_id, action=action)
        before = self.recorder.action_id
        receipt = dict(id=ident, accepted=None, status='unknown', effect='unverified')
        result = None
        try:
            raw = self.recorder.observe()  # Checks PID/player/epoch and monotonic publication.
            current = dict(self.recorder.last_observation, clock=raw.clock,
                           units=[self.recorder.boundary.unit(u) for u in raw.units
                                  if u.owner == 1 or u.visible_to(1)])
            current.update(self.recorder.boundary.economic_state(raw,
                {u.handle for u in raw.units if u.owner == 1}))
            current['hero_skill_points'] = hero_skills.points(raw)
            current['own_spell_status'] = unit_spells.statuses(raw)
            clock = decision.get('clock')
            reason = preflight(action, decision, self.bounds, self.costs)
            if not finite(clock) or not 0 <= raw.clock-clock <= MAX_AGE:
                reason = 'stale_decision'
            elif reason == 'allowed':
                reason = preflight(action, current, self.bounds, self.costs)
            # Even on the same game clock, re-project current visibility/ownership;
            # a paused/same-clock recorder intentionally retains its prior frame.
            if reason == 'allowed' and action['op'] not in ('wait','inspect_trees','inspect_research'):
                wanted = [action['unit']] + ([action['target']] if 'target' in action and action['op']!='gather_lumber' else [])
                resolved = []
                for handle in wanted:
                    unit = next((u for u in raw.units if list(u.handle) == handle), None)
                    if unit is None or (unit.owner != 1 and not unit.visible_to(1)):
                        reason = 'entity_no_longer_observable';break
                    resolved.append(unit)
                if reason == 'allowed':
                    own = resolved[0]
                    if own.owner != 1 or not own.alive:
                        reason = 'source_not_owned_alive'
                    elif action['op'] == 'attack' and (resolved[1].owner != 2 or not resolved[1].alive):
                        reason = 'target_not_visible_enemy_alive'
            if reason == 'allowed' and action['op'] == 'gather_lumber':
                tree = self.recorder.trees.resolve_visible(action['target'])
                if tree is None:reason = 'tree_no_longer_visible'
                elif not finite(tree.life) or tree.life <= 0:reason = 'tree_not_alive'
                else:resolved.append(tree)
            if reason == 'allowed' and action['op'] == 'inspect_trees':
                reason = self.recorder.trees.scan(action['x'], action['y'])
            if reason=='allowed' and action['op'] in ('inspect_research','research'):
                actual=research.read_level(self.recorder,action['code'])
                if actual is None:reason='research_level_unknown'
                elif action['op']=='research' and actual!=action['level']-1:reason='research_level_changed'
            if reason == 'allowed' and action['op'] == 'build':
                reason = economy_actions.placement_reason(self.game, action, self.costs, self.bounds)
            if reason == 'allowed' and action['op'] in ('train', 'train_hero', 'upgrade_hall','research'):
                verdict = self.game.can_do(own, action['code'])
                if type(verdict) is not int or verdict not in (0, 220):
                    reason = 'engine_prerequisites_unknown' if verdict is None else 'engine_prerequisites_rejected'
            self.write('preflight', id=ident, observation_id=self.recorder.observation_id,
                       clock=raw.clock, allowed=reason == 'allowed', reason=reason)
            if reason != 'allowed':
                receipt.update(accepted=False, status='preflight_rejected', reason=reason)
            elif action['op'] == 'wait':
                receipt.update(status='no_command')
            elif action['op'] in ('inspect_trees','inspect_research'):
                receipt.update(status='observation_only')
            else:
                op = action['op']
                # No dynamic dispatch of caller-supplied method names.
                if op == 'move':result = self.game.move(own, action['x'], action['y'])
                elif op == 'attack_move':result = self.game.attack_move(own, action['x'], action['y'])
                elif op == 'attack':result = self.game.attack(own, resolved[1])
                elif op in ('gather_gold','gather_lumber'):result = self.game.gather(own, resolved[1])
                elif op == 'build':result = self.game.build(own, action['code'], action['x'], action['y'])
                elif op in ('train', 'train_hero', 'upgrade_hall','research'):result = self.game.train(own, action['code'])
                elif op=='use_item_now':result=self.game.use_item(own,action['slot'])
                elif op=='use_item_point':result=self.game.use_item(own,action['slot'],x=action['x'],y=action['y'])
                elif op == 'buy_item':result = self.game.buy(own,action['item'])
                elif op == 'learn_skill':result = self.game.learn(own, action['skill'])
                elif op == 'cast_unit':result = self.game.cast(own, unit_spells.SPELLS[action['skill']][1], target=resolved[1])
                elif op == 'stop':result = self.game.stop(own)
                else:result = self.game.hold(own)
                timed_out = result is not None and result.status == 99
                receipt.update(accepted=bool(result.ok) if result is not None and not timed_out else None,
                               status='timeout_unknown' if timed_out else 'returned' if result is not None else 'missing_receipt',
                               native_status=getattr(result, 'status', None))
        except BaseException:
            receipt.update(accepted=None, status='interrupted_or_error')
            raise
        finally:
            receipt['native_request_ids'] = list(range(before+1, self.recorder.action_id+1))
            self.write('receipt', **receipt)
            self.receipts.append(copy.deepcopy(receipt))
            self.pending.append((ident, self.recorder.last_observation['clock']))
            self.write_diagnostic('receipt', id=ident, **receipt_diagnostics(result))

    def observe(self, final=False):
        """Link later evidence, without attributing damage/movement to the action."""
        remaining = []
        clock = self.recorder.last_observation['clock']
        for ident, after_clock in self.pending:
            later = clock > after_clock
            if later or final:
                self.write('next_observation', id=ident,
                           observation_id=self.recorder.observation_id if later else None,
                           clock=clock if later else None, effect='unverified')
            else:remaining.append((ident, after_clock))
        self.pending = remaining

    def drain_receipts(self):
        receipts, self.receipts = self.receipts, []
        return receipts

    def close(self):
        if self.closed:return
        try:self.observe(final=True)
        finally:
            self.closed = True
            try:self.stream.close()
            finally:
                if self.diagnostics is not None:self.diagnostics.close()
