"""Opt-in P1 rule demonstrations, not an actor executor or an approved dataset.

Never serialize SDK objects, event dictionaries, addresses, or raw command args.
Queries and diagnostic lanes are excluded. Effects are subsequent observations,
not successful command receipts. Only an explicit natural referee result rewards.
"""
import copy
import json
import math
import struct
from undead.player_visibility import PlayerVisibility
from run_guard import RunInterrupted
from learning.outcome import NATURAL, classify_outcome

SCHEMA = 'dayuan-trajectory-v1'
PRIMITIVE_SCHEMA = 'dayuan-trajectory-v2'
RESOURCE_FIELDS = ('gold', 'lumber', 'food_used', 'food_cap', 'gold_gathered', 'lumber_gathered')
UNIT_FIELDS = ('x', 'y', 'hp', 'hp_max', 'mana', 'mana_max', 'level')
ACTION_NAMES = ('point', 'target', 'immediate', 'build', 'learn', 'use_item',
                'revive', 'rally', 'buy', 'item_drop')


class BoundaryError(RuntimeError):
    pass


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def code(value):
    return value if isinstance(value, str) and len(value) == 4 else None


def handle(unit):
    value = getattr(unit, 'handle', None)
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise BoundaryError('Missing entity identity')
    if any(type(v) is not int or not 0 < v < 2**32 for v in value):
        raise BoundaryError('Invalid entity identity')
    return tuple(value)


class ObservationBoundary:
    """Bound to one process/epoch/P1; owns memory of legal observations only."""
    def __init__(self, pid, epoch):
        if type(pid) is not int or pid <= 0 or type(epoch) is not int or epoch <= 0:
            raise BoundaryError('Unknown process/epoch')
        self.pid, self.epoch = pid, epoch
        self.clock = None
        self.publication = None
        self.memory = {}

    def validate(self, game, raw):
        if (game.pid != self.pid or game.player != 1 or game.fair is not True
                or raw is None or not raw.in_game or raw.me != 0 or raw.epoch != self.epoch):
            raise BoundaryError('P1 process/observer/epoch binding changed')
        now, publication = number(raw.clock), number(raw.publish_count)
        if now is None or publication is None:
            raise BoundaryError('Unknown observation clock/publication')
        if (self.clock is not None and now < self.clock
                or self.publication is not None and publication < self.publication):
            raise BoundaryError('Stale observation')

    def unit(self, unit):
        own = unit.owner == 1
        data = dict(handle=list(handle(unit)), type=code(unit.type), owner=unit.owner,
                    alive=bool(unit.alive), **{k: number(getattr(unit, k, None)) for k in UNIT_FIELDS})
        # Enemy orders, targets, skill/cooldown/inventory detail are not public inputs.
        if own:
            detailed = getattr(unit, 'has_detail', False) is True
            data['inventory'] = ([code(v) for v in unit.items] if detailed and len(unit.items) == 6 else None)
            data['abilities'] = ([dict(code=code(a.code), level=number(a.level),
                                       cooldown=number(a.cooldown)) for a in unit.abilities] if detailed else None)
        return data

    @staticmethod
    def economic_state(raw, own_handles):
        player = next((p for p in raw.players if p.id == 1), None)
        resources = ({k: number(getattr(player, k, None)) for k in RESOURCE_FIELDS}
                     if player is not None and player.known else None)
        production = []
        for row in raw.production:
            if tuple(row.building) not in own_handles:
                continue
            production.append(dict(building=list(row.building),
                                   kind=row.kind if row.kind in ('queue', 'construction', 'upgrade') else None,
                                   queue=[code(v) for v in row.queue], progress=number(row.progress)))
        return dict(resources=resources, production=sorted(production, key=lambda p: p['building']))

    def project(self, game, raw):
        self.validate(game, raw)
        if self.clock == raw.clock:
            return None  # A paused simulation does not create duplicate decisions.
        units, own_handles = [], set()
        for unit in raw.units:
            # Check visibility BEFORE reading alive/detail: hidden deaths cannot erase memory.
            if unit.owner != 1 and not unit.visible_to(1):
                continue
            data = self.unit(unit)
            units.append(data)
            if unit.owner == 1:
                own_handles.add(handle(unit))
            else:
                self.memory[handle(unit)] = dict(last_seen_clock=raw.clock, unit=copy.deepcopy(data))
        self.clock, self.publication = raw.clock, raw.publish_count
        return dict(player=1, clock=raw.clock, **self.economic_state(raw, own_handles),
                    units=sorted(units, key=lambda u: u['handle']),
                    last_seen=[copy.deepcopy(self.memory[h]) for h in sorted(self.memory)])


class PointVisibility(PlayerVisibility):
    """Narrow read-only P1 oracle on a separate local dev client.

    SDK q_visible is documented as local-player view; JASS is disallowed on a
    player/fair lane. This separate client never supplies state to the actor.
    Errors yield unknown, never an observer-view or radius-based fallback.
    """
    def __init__(self, client, pid, epoch):
        super().__init__(client, pid, epoch, player=1)


class TrajectoryRecorder:
    """Observe a rule player's existing lane; never executes/replaces actions.

    Eligibility below is a provenance filter, NOT full gameplay legality. Engine
    receipts remain distinct; new model execution/preconditions need an adapter.
    """
    def __init__(self, game, path, *, visibility=None, public_points=(), capture_receipts=False, policy='rule'):
        if policy not in ('rule','external_primitives'):raise ValueError('Unsupported trajectory policy')
        raw = game.world.read()
        self.boundary = ObservationBoundary(game.pid, getattr(raw, 'epoch', None))
        self.boundary.validate(game, raw)
        self.game, self.visibility = game, visibility
        self.trees = None
        if policy == 'external_primitives':
            from learning.trees import TreeSightings
            self.trees = TreeSightings(game, self.boundary)
        self.points = tuple(sorted(set(tuple(p) for p in public_points)))
        if len(self.points) > 16 or any(len(p) != 2 or any(number(v) is None for v in p) for p in self.points):
            raise BoundaryError('Expected at most 16 public coordinates without slot identities')
        if self.points and visibility is None:
            raise BoundaryError('Point observations require an explicit P1 oracle')
        self.ops = {game._w3fast.OP[n]: n for n in ACTION_NAMES}
        self.stream = path.open('x', encoding='utf-8')
        self.observation_id = self.action_id = 0
        self.last_points = -float('inf')
        self.last_observation = None
        self.closed = False
        self.receipt_buffer = [] if capture_receipts else None
        self.original = game.lane.commands
        self.wrapper = self.commands
        try:
            self.write('header', schema=PRIMITIVE_SCHEMA if self.trees else SCHEMA, player=1, epoch=raw.epoch,
                       policy=policy, training_actor_approved=False,
                       limitations=['teacher_visibility_not_live_audited', 'no_model_action_adapter',
                                    'receipts_do_not_prove_effects', 'ground_items_and_map_grid_omitted']
                       if policy == 'rule' else ['partial_primitive_adapter', 'receipts_do_not_prove_effects',
                                                'ground_items_and_map_grid_omitted'])
            self.observe(raw)
        except Exception:
            self.stream.close()
            raise
        game.lane.commands = self.wrapper

    def write(self, event, **data):
        self.stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False, allow_nan=False)+'\n')
        self.stream.flush()
        if event == 'action_receipt' and self.receipt_buffer is not None:
            self.receipt_buffer.append(copy.deepcopy(data))

    def drain_receipts(self):
        if self.receipt_buffer is None:return []
        receipts, self.receipt_buffer = self.receipt_buffer, []
        return receipts

    def observe(self, raw=None):
        raw = self.game.world.read() if raw is None else raw
        observation = self.boundary.project(self.game, raw)
        if observation is not None:
            if self.trees is not None:observation['tree_sightings'] = self.trees.rows()
            self.observation_id += 1
            self.last_observation = copy.deepcopy(observation)
            self.write('observation', id=self.observation_id, observation=observation)
        return raw

    def observe_points(self):
        raw = self.game.world.read()
        self.boundary.validate(self.game, raw)
        if self.visibility is not None and raw.clock-self.last_points >= 1:
            points = [self.visibility.query(*p) for p in self.points]
            self.boundary.validate(self.game, self.game.world.read())
            self.last_points = raw.clock
            self.write('point_visibility', player=1, points=points)

    def request(self, call, raw):
        op = self.ops[call.op]
        args = call.args
        if len(args) != 11:
            return None, 'malformed_command'
        # Address is checked only internally; no addresses/raw arguments leave here.
        def resolve(offset):
            key = tuple(args[offset+1:offset+3])
            return next((u for u in raw.units if u.handle == key and u.addr == args[offset]), None)
        unit = resolve(0)
        if unit is None or unit.owner != 1 or not unit.alive:
            return None, 'source_not_owned_alive'  # Neutral shop purchases omitted in v1.
        target = None
        target_kind = 'unit'
        if any(args[4:7]):
            target = resolve(4)
            if target is None and self.trees is not None:
                target = self.trees.resolve_visible(list(args[5:7]))
                if target is not None and target.addr != args[4]:target = None
                if target is not None:target_kind = 'tree'
            if target is None or target_kind == 'unit' and target.owner != 1 and not target.visible_to(1):
                return None, 'target_not_currently_observable'
        observable = {tuple(u['handle']) for u in self.last_observation['units']}
        if self.trees is not None:observable.update(tuple(t['handle']) for t in self.last_observation['tree_sightings'])
        target_handle = None
        if target is not None:
            from learning.trees import identity as tree_identity
            target_handle = tree_identity(target) if target_kind == 'tree' else target.handle
        if unit.handle not in observable or target_handle is not None and target_handle not in observable:
            return None, 'not_in_recorded_observation'
        data = dict(op=op, unit=list(unit.handle), code=args[3],
                    target=list(target_handle) if target_handle is not None else None)
        if target_kind == 'tree':data['target_kind'] = 'tree'
        if op in ('point', 'build', 'rally', 'use_item', 'item_drop'):
            x, y = (struct.unpack('<f', struct.pack('<I', v))[0] for v in args[7:9])
            if number(x) is None or number(y) is None:
                return None, 'invalid_coordinates'
            data.update(x=x, y=y)
        # extra/mode can have op-specific meanings; omitted until an action adapter exists.
        return data, 'observable_owned_request'

    def commands(self, calls, *args, **kwargs):
        calls = list(calls)
        selected = [(i, c) for i, c in enumerate(calls) if c.op in self.ops]
        if not selected:
            return self.original(calls, *args, **kwargs)
        raw = self.observe()
        requests = []
        for index, call in selected:
            payload, reason = self.request(call, raw)
            self.action_id += 1
            requests.append((index, self.action_id))
            self.write('action_request', id=self.action_id, observation_id=self.observation_id,
                       clock=raw.clock, eligible=payload is not None, eligibility=reason, action=payload)
        try:
            receipts = self.original(calls, *args, **kwargs)
        except BaseException as exc:
            for _, action_id in requests:
                self.write('action_receipt', id=action_id, accepted=None,
                           status='interrupted' if isinstance(exc, RunInterrupted) else 'transport_error', effect='unverified')
            raise
        for index, action_id in requests:
            receipt = receipts[index] if index < len(receipts) else None
            self.write('action_receipt', id=action_id,
                       accepted=bool(receipt.ok) if receipt is not None and receipt.status != 99 else None,
                       status=number(getattr(receipt, 'status', None)), effect='unverified')
        return receipts

    def finish(self, outcome, reason, *, natural_confirmed=False):
        if self.closed:
            return
        try:
            termination = classify_outcome(outcome, reason, natural_confirmed=natural_confirmed)
            # No raw referee state, exception strings, UI actions, or opponent labels.
            self.write('terminal', **termination,
                       last_observation_id=self.observation_id, training_actor_approved=False)
        finally:
            self.closed = True
            if self.game.lane.commands is self.wrapper:
                self.game.lane.commands = self.original
            self.stream.close()
