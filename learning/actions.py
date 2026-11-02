"""Explicit, bounded P1 primitives. Preflight is not full engine legality.

No raw order IDs, addresses, queue modes or arbitrary SDK method names cross
this boundary. One primitive per decision; replacement orders only.
"""
import copy
import json
import math
import struct

SCHEMA = 'dayuan-primitive-action-v1'
OPS = ('wait', 'move', 'attack_move', 'attack', 'stop', 'hold')
MAX_AGE = 8.0  # Game seconds; the real-time engine does not pause for inference.


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def identity(value):
    return (type(value) is list and len(value) == 2
            and all(type(v) is int and 0 < v < 2**32 for v in value))


def validate(action):
    if type(action) is not dict or action.get('schema') != SCHEMA or action.get('op') not in OPS:
        raise ValueError('Unsupported primitive schema or operation')
    op = action['op']
    fields = {'schema', 'op'}
    if op != 'wait':fields.add('unit')
    if op in ('move', 'attack_move'):fields.update(('x', 'y'))
    if op == 'attack':fields.add('target')
    if set(action) != fields:
        raise ValueError('Unexpected or missing primitive fields')
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
    return result


def checked_bounds(bounds):
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or not all(finite(v) for v in bounds)
            or not bounds[0] < bounds[1] or not bounds[2] < bounds[3]):
        raise ValueError('Verified public map bounds required')
    return list(bounds)


def preflight(action, observation, bounds):
    """Only consult the white-listed observation, never hidden SDK entities."""
    action = validate(action)
    if not isinstance(observation, dict) or observation.get('player') != 1:
        return 'observation_unavailable'
    if action['op'] == 'wait':return 'allowed'
    units = {tuple(u['handle']): u for u in observation['units']}
    unit = units.get(tuple(action['unit']))
    if unit is None or unit['owner'] != 1 or unit['alive'] is not True:
        return 'source_not_owned_alive'
    abilities = unit.get('abilities')
    if abilities is None:return 'source_capabilities_unknown'
    known = {a['code'] for a in abilities if finite(a.get('level')) and a['level'] > 0}
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
        self.stream = path.open('x', encoding='utf-8')
        self.sequence = 0
        self.pending = []
        self.receipts = []
        self.closed = False
        try:
            self.write('header', schema=SCHEMA, player=1, epoch=recorder.boundary.epoch,
                       policy='external_primitives', training_actor_approved=False,
                       bounds=self.bounds, max_decision_age_game_seconds=MAX_AGE,
                       limitations=['partial_action_space', 'preflight_not_full_engine_legality',
                                    'receipts_and_later_observations_do_not_prove_effects'])
        except BaseException:
            self.stream.close()
            raise

    def write(self, event, **data):
        self.stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False, allow_nan=False)+'\n')
        self.stream.flush()

    def execute(self, action, decision, decision_id):
        action = validate(action)
        self.sequence += 1
        ident = self.sequence
        self.write('request', id=ident, observation_id=decision_id, action=action)
        before = self.recorder.action_id
        receipt = dict(id=ident, accepted=None, status='unknown', effect='unverified')
        try:
            raw = self.recorder.observe()  # Checks PID/player/epoch and monotonic publication.
            current = dict(self.recorder.last_observation, clock=raw.clock,
                           units=[self.recorder.boundary.unit(u) for u in raw.units
                                  if u.owner == 1 or u.visible_to(1)])
            clock = decision.get('clock')
            reason = preflight(action, decision, self.bounds)
            if not finite(clock) or not 0 <= raw.clock-clock <= MAX_AGE:
                reason = 'stale_decision'
            elif reason == 'allowed':
                reason = preflight(action, current, self.bounds)
            # Even on the same game clock, re-project current visibility/ownership;
            # a paused/same-clock recorder intentionally retains its prior frame.
            if reason == 'allowed' and action['op'] != 'wait':
                wanted = [action['unit']] + ([action['target']] if 'target' in action else [])
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
                    elif len(resolved) == 2 and (resolved[1].owner != 2 or not resolved[1].alive):
                        reason = 'target_not_visible_enemy_alive'
            self.write('preflight', id=ident, observation_id=self.recorder.observation_id,
                       clock=raw.clock, allowed=reason == 'allowed', reason=reason)
            if reason != 'allowed':
                receipt.update(accepted=False, status='preflight_rejected', reason=reason)
            elif action['op'] == 'wait':
                receipt.update(status='no_command')
            else:
                op = action['op']
                # No dynamic dispatch of caller-supplied method names.
                if op == 'move':result = self.game.move(own, action['x'], action['y'])
                elif op == 'attack_move':result = self.game.attack_move(own, action['x'], action['y'])
                elif op == 'attack':result = self.game.attack(own, resolved[1])
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
            self.stream.close()
