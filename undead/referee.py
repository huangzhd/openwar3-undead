"""Terminal judge. Raw world data stays here and never enters policy observations."""
class Referee:
    def __init__(self):self.saw_opponent=False
    def observe(self,raw,me,is_building):
        if raw is None or not raw.in_game:
            raise RuntimeError('No live referee snapshot; cannot assign a result')
        structures=[u for u in raw.units if u.alive and (is_building(u) or u.type in {'ugol','egol'})]
        mine=any(u.owner==me for u in structures)
        opponent=any(0<=u.owner<12 and u.owner!=me for u in structures)
        if opponent:self.saw_opponent=True
        if not mine and not opponent:
            raise RuntimeError('Both sides absent from snapshot; cannot infer a winner')
        if not mine and opponent:return 'loss','all_own_buildings_destroyed'
        if mine and not opponent and self.saw_opponent:return 'win','all_enemy_buildings_destroyed'
        return None
