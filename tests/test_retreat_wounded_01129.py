import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.controller import Controller
from undead.policy import Action, Situation


class WoundedRetreatTests(unittest.TestCase):
    def recorded(self):
        data=json.loads((Path(__file__).parent/'fixtures/ch-retreat-wounded-01129.json').read_text(encoding='utf-8'))
        earlier,later=data['frames']
        heroes=[N(**dict(u,handle=tuple(u['handle']))) for u in later['heroes']]
        events=[]
        b=Controller(N(my_heroes=lambda:heroes),lambda e,**kw:events.append(dict(event=e,**kw)))
        previous={tuple(u['handle']):u['hp'] for u in earlier['heroes']}
        for u in heroes:
            if u.hp<previous[u.handle]:b.micro.hit[u.handle]=later['clock']
        r=data['premature_release']
        b.retreat_active=True;b.retreat_safe_since=r['clock']-5
        b.situation=Situation(r['clock'],army_hp=r['army_hp'],local_enemy_hp=r['enemy_hp'],attack_committed=True)
        return b,heroes,events

    def test_recorded_wounded_heroes_reset_exit_timer_despite_low_enemy_hp(self):
        b,heroes,events=self.recorded()
        self.assertEqual(b.retreat_rule(Action.ATTACK),Action.RETREAT)
        self.assertIsNone(b.retreat_safe_since)
        self.assertTrue(any(e['event']=='retreat_wounded_damage' for e in events))

    def test_damage_free_wounded_heroes_release_without_full_heal_wait(self):
        b,heroes,events=self.recorded()
        self.assertEqual(b.retreat_rule(Action.ATTACK),Action.RETREAT)
        for now in (1066,1069,1070.9):
            b.situation.now=now
            self.assertEqual(b.retreat_rule(Action.ATTACK),Action.RETREAT)
        b.situation.now=1071
        self.assertEqual(b.retreat_rule(Action.ATTACK),Action.ATTACK)
        self.assertTrue(any(u.hp/u.hp_max<.5 for u in heroes))

    def test_recent_damage_does_not_start_retreat_or_hold_healed_heroes(self):
        b,heroes,events=self.recorded();b.retreat_active=False
        self.assertEqual(b.retreat_rule(Action.ATTACK),Action.ATTACK)
        b.retreat_active=True
        for u in heroes:u.hp=u.hp_max
        self.assertEqual(b.retreat_rule(Action.ATTACK),Action.ATTACK)
