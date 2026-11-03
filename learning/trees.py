"""Explicit, local P1 tree sightings; hidden tree life is never an observation."""
import copy

RADIUS = 256
MAX_SIGHTINGS = 64
MAX_AGE = 8.


def identity(tree):
    # SDK Tree is not a Unit and deliberately has no .handle property.
    result = (getattr(tree,'handle_lo',None),getattr(tree,'handle_hi',None))
    if any(type(v) is not int or not 0 < v < 2**32 for v in result):
        from learning.trajectory import BoundaryError
        raise BoundaryError('Invalid tree identity')
    return result


class TreeSightings:
    def __init__(self, game, boundary):
        self.game, self.boundary = game, boundary
        self.memory = {}

    def geometry(self):
        from w3world import tree_types
        kinds = tree_types()
        if not kinds:raise RuntimeError('Verified public tree-type catalog unavailable')
        # Do NOT use trees()'s default alive filter: hidden deaths are private.
        return [t for t in self.game.world.trees(alive=False) if t.type in kinds]

    def check_binding(self):
        raw = self.game.world.read()
        self.boundary.validate(self.game, raw)
        return raw

    def scan(self, x, y):
        self.check_binding()
        if self.game.visible(x, y) is not True:return 'tree_query_point_not_visible'
        # Selection before visibility uses geometry only, never life/dead flags.
        # Limit AFTER visibility, so removing hidden trees cannot reveal others.
        candidates = [t for t in self.geometry() if (t.x-x)**2+(t.y-y)**2 <= RADIUS**2]
        found = []
        for tree in sorted(candidates, key=lambda t:(t.x,t.y,identity(t))):
            if self.game.visible(tree.x, tree.y) is not True:continue
            raw = self.check_binding()
            from learning.trajectory import code
            found.append(dict(handle=list(identity(tree)),type=code(tree.type),x=tree.x,y=tree.y,
                              seen_clock=raw.clock))
        for row in found[:MAX_SIGHTINGS]:self.memory[tuple(row['handle'])] = row
        latest = sorted(self.memory.values(), key=lambda r:(-r['seen_clock'],r['handle']))[:MAX_SIGHTINGS]
        self.memory = {tuple(r['handle']):r for r in latest}
        self.check_binding()
        return 'allowed'

    def rows(self):
        return [copy.deepcopy(self.memory[h]) for h in sorted(self.memory)]

    def resolve_visible(self, wanted):
        """Execution/provenance only. No hidden life, and no guessed target."""
        self.check_binding()
        tree = next((t for t in self.geometry() if list(identity(t)) == wanted), None)
        if tree is None or self.game.visible(tree.x,tree.y) is not True:return None
        self.check_binding()
        return tree


def preflight(action, observation, source, abilities):
    if source['type'] != 'ugho' or not {'Amov','Ahrl'} <= abilities:return 'source_cannot_gather_lumber'
    sighting = next((t for t in observation.get('tree_sightings',[]) if t['handle']==action['target']),None)
    if sighting is None:return 'tree_not_observed'
    age = observation['clock']-sighting['seen_clock']
    if not 0 <= age <= MAX_AGE:return 'tree_sighting_stale'
    return 'allowed'
