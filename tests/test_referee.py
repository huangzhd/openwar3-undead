import unittest
from types import SimpleNamespace as N
from undead.referee import Referee

class RefereeTests(unittest.TestCase):
    def test_undead_mine_keeps_player_alive(self):
        r=Referee()
        raw=N(in_game=True,units=[N(type='ugol',owner=0,alive=True),N(type='htow',owner=1,alive=True)])
        self.assertIsNone(r.observe(raw,0,lambda u:u.type=='htow'))
        raw.units[0].alive=False
        self.assertEqual(r.observe(raw,0,lambda u:u.type=='htow')[0],'loss')
    def test_our_structure_remaining_and_seen_opponent_eliminated_is_win(self):
        r=Referee()
        raw=N(in_game=True,units=[N(type='unpl',owner=0,alive=True),N(type='htow',owner=1,alive=True)])
        r.observe(raw,0,lambda u:True)
        raw.units[1].alive=False
        self.assertEqual(r.observe(raw,0,lambda u:True)[0],'win')
    def test_empty_or_ended_world_is_error_not_a_fabricated_result(self):
        r=Referee()
        with self.assertRaises(RuntimeError):r.observe(N(in_game=True,units=[]),0,lambda u:True)
        with self.assertRaises(RuntimeError):r.observe(N(in_game=False,units=[]),0,lambda u:True)

if __name__=='__main__':unittest.main()
