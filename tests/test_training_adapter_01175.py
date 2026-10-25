"""The pinned map sends round metadata without exposing JASS to the policy."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from training import TrainingController, board_signal, board_state, contact_reason
from test_baseline import unit
from training_map import source_map, patch_script
import training_control
from undead.micro import Micro
from undead.battle_spells import silence_key_hero
from w3mpq import Mpq


class TrainingAdapterTests(unittest.TestCase):
    def test_non_tc_silence_waits_for_enemy_hero_buff_to_be_removed(self):
        dark = unit('Nbrn', 1, owner=0, x=0);dark.mana=300;dark.has_detail=True
        chief = unit('Oshd', 2, owner=1, x=250);chief.has_detail=True
        effects = {chief.handle:['Broa']}
        casts = []
        controller = object.__new__(TrainingController)
        controller.training_orc = True
        controller.cast_until = {}
        controller.g = SimpleNamespace(dist=lambda a,b: abs(a.x-b.x),
                                       buffs=lambda u: effects.get(u.handle,[]),
                                       abilities=lambda u: [],
                                       cast=lambda *args,**kwargs: casts.append((args,kwargs)) or True)
        controller.log = lambda *args,**kwargs: None
        with patch('undead.battle_spells.level', return_value=1), \
             patch('undead.battle_spells.ready', return_value=True):
            silence_key_hero(controller,[dark],[chief],10)
            self.assertFalse(casts)
            effects[chief.handle]=[]
            silence_key_hero(controller,[dark],[chief],11)
            self.assertEqual(casts[0][0][1],'silence')
            effects[chief.handle]=['BNsi']
            silence_key_hero(controller,[dark],[chief],12)
            self.assertEqual(len(casts),1)

    def test_round_protocol_and_original_adjudication(self):
        source = Mpq(source_map()).read('war3map.j')
        script = patch_script(source, 'orc', 2, 'easy').decode('latin-1')
        def body(name):
            return script.split('function ' + name + ' takes nothing returns nothing', 1)[1].split('endfunction', 1)[0]
        self.assertIn('set udg_RoundNo = 2', body('Trig_Initialiaztion_Actions'))
        self.assertIn('SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_LUMBER, 1)', body('Trig_Main_Actions'))
        self.assertEqual(sum(body('OWT_CountdownRelease'+str(side)).count('SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_LUMBER, 2)') for side in (0,1)), 2)
        self.assertIn('100 + CountUnitsInGroup(GetUnitsOfPlayerMatching(Player(1)',
                      body('Trig_CheckWin10_Actions'))
        result = body('Trig_CheckPass_Actions')
        self.assertIn('2 + udg_win', result)
        self.assertNotIn('gg_trg_Main', result)
        self.assertNotIn('RemoveUnit', result)
        self.assertIn('function Trig_Player1Win_Actions', script)
        self.assertIn('function Trig_Player2Win_Actions', script)
        self.assertNotIn('LeaderboardGetLabelText', script)

    def test_audit_reads_only_reserved_integer(self):
        class Jass:
            def __init__(self, state): self.state = state; self.calls = []
            def Player(self, slot): self.calls.append(('Player', slot)); return slot
            def ConvertPlayerState(self, kind): self.calls.append(('ConvertPlayerState', kind)); return kind
            def GetPlayerState(self, slot, kind):
                self.calls.append(('GetPlayerState', slot, kind)); return self.state
        for state in (0, 1, 2, 3, 4):
            j = Jass(state)
            self.assertEqual(board_state(SimpleNamespace(jass=j)), state)
            self.assertEqual(j.calls, [('Player', 0), ('ConvertPlayerState', 1), ('GetPlayerState', 0, 1)])
        self.assertEqual(board_state(SimpleNamespace(jass=Jass(500))), 1)
        self.assertEqual(board_signal(SimpleNamespace(jass=Jass(107))), (1, 7))
        self.assertEqual(board_signal(SimpleNamespace(resources=lambda: {'lumber': 3})), (3, None))
        self.assertEqual(board_signal(SimpleNamespace(resources=lambda: {'lumber': 107})), (1, 7))
        with self.assertRaises(RuntimeError):
            board_state(SimpleNamespace(jass=Jass(5)))

    def test_combat_starts_when_countdown_marker_is_lost(self):
        ally = SimpleNamespace(handle=1, alive=True, type='Udea', hp=800, hp_max=800)
        foe = SimpleNamespace(handle=2, alive=True, type='Otch', hp=700, hp_max=700)
        game = SimpleNamespace(current_target=lambda u: None)
        self.assertIsNone(contact_reason(game, [ally], [foe]))
        game.current_target = lambda u: ally
        self.assertEqual(contact_reason(game, [ally], [foe]), 'enemy_targeting_army')
        game.current_target = lambda u: None
        ally.hp = 790
        self.assertEqual(contact_reason(game, [ally], [foe]), 'army_took_damage')

    def test_panel_commands_are_scoped_to_one_training_session(self):
        with TemporaryDirectory() as temporary:
            with patch.object(training_control, 'STATUS', Path(temporary)/'status.json'), \
                 patch.object(training_control, 'COMMAND', Path(temporary)/'command.json'):
                first = training_control.begin({'matchup': 'orc', 'level': 2})
                self.assertFalse(training_control.post(first, 'restart'))
                training_control.status(first, phase='running')
                self.assertTrue(training_control.post(first, 'restart'))
                self.assertIsNone(training_control.take('unrelated'))
                self.assertEqual(training_control.take(first)['action'], 'restart')
                self.assertIsNone(training_control.take(first))
                next_selection = {'matchup': 'orc', 'level': 3, 'mode': 'hard'}
                self.assertFalse(training_control.post(first, 'switch', {'matchup': 'orc', 'level': 11, 'mode': 'hard'}))
                self.assertTrue(training_control.post(first, 'switch', next_selection))
                self.assertEqual(training_control.take(first)['selection'], next_selection)
                training_control.status(first, phase='finished', result='forfeit')
                self.assertFalse(training_control.post(first, 'forfeit'))

    def test_training_heroes_keep_fighting_when_enemy_hero_is_lower(self):
        def unit(code, handle, hp, maximum, x=0):
            return SimpleNamespace(type=code, handle=handle, hp=hp, hp_max=maximum,
                                   x=x, y=0, mana=0, is_hero=code[0].isupper())
        dk = unit('Udea', 1, 800, 800)
        lich = unit('Ulic', 2, 270, 525, 50)
        dark = unit('Nbrn', 3, 320, 625, 80)
        enemy = unit('Otch', 4, 180, 700, 260)
        def distance(a, b):
            a = (a.x, a.y) if hasattr(a, 'x') else a
            b = (b.x, b.y) if hasattr(b, 'x') else b
            return abs(a[0]-b[0]) + abs(a[1]-b[1])
        micro = Micro(lambda *a, **k: None)
        moves = micro.plan([dk, lich, dark], [enemy], 1, lambda _: lich.handle,
                           distance, lambda *p: True, (-500, 0),
                           aggressive_training=True)
        self.assertNotIn(lich.handle, moves)
        self.assertNotIn(dark.handle, moves)
        moves = Micro(lambda *a, **k: None).plan([dk, lich], [enemy], 1,
            lambda _: dk.handle, distance, lambda *p: True, (-500, 0),
            aggressive_training=True)
        self.assertNotIn(dk.handle, moves)

    def test_training_target_count_does_not_pull_healthy_heroes(self):
        def unit(code, handle, hp, maximum, x):
            return SimpleNamespace(type=code, handle=handle, hp=hp, hp_max=maximum,
                                   x=x, y=0, mana=0, is_hero=code[0].isupper())
        dk = unit('Udea', 1, 800, 800, 0)
        lich = unit('Ulic', 2, 270, 525, 0)
        dark = unit('Nbrn', 3, 320, 625, 0)
        enemies = [unit('ohun', 4, 500, 500, 300), unit('ohun', 5, 500, 500, 350)]
        for hero in (dk, lich, dark):
            micro = Micro(lambda *a, **k: None)
            moves = micro.plan([dk, lich, dark], enemies, 1, lambda _: hero.handle,
                               lambda a, b: 0, lambda *p: True, (-1000, 0),
                               aggressive_training=True)
            self.assertNotIn(hero.handle, moves)

    def test_training_backline_reengages_once_no_longer_threatened(self):
        def unit(code, handle, hp, maximum, x):
            return SimpleNamespace(type=code, handle=handle, hp=hp, hp_max=maximum,
                                   x=x, y=0, mana=0, is_hero=code[0].isupper())
        dk = unit('Udea', 1, 800, 800, 0)
        lich = unit('Ulic', 2, 100, 525, 0)
        dark = unit('Nbrn', 3, 130, 625, -100)
        foe = unit('ohun', 4, 500, 500, 300)
        for hero in (lich, dark):
            micro = Micro(lambda *a, **k: None)
            micro.plan([dk, lich, dark], [foe], 1, lambda _: hero.handle,
                       lambda a, b: 100, lambda *p: True, (-1000, 0),
                       aggressive_training=True)
            self.assertIn(hero.handle, micro.pulling)
            hero.x = -1000
            moves = micro.plan([dk, lich, dark], [foe], 5, lambda _: None,
                               lambda a, b: 100, lambda *p: True, (-1000, 0),
                               aggressive_training=True)
            self.assertNotIn(hero.handle, micro.pulling)
            self.assertNotIn(hero.handle, moves)

    def test_training_searches_last_contact_then_map_for_survivors(self):
        events = []
        controller = object.__new__(TrainingController)
        controller.log = lambda event, **data: events.append((event, data))
        controller.enemy_main = (832., 384.)
        controller.last_foe_position = None
        controller.search_route = []
        controller.search_index = 0
        controller.search_since = None
        ally = SimpleNamespace(type='Ulic', x=-1500., y=100.)
        foe = SimpleNamespace(type='okod', hp=18., x=-590., y=-148.)
        self.assertIsNone(controller.search_target([ally], [foe], 1))
        self.assertEqual(controller.search_target([ally], [], 2), (-590., -148.))
        ally.x, ally.y = -590., -148.
        self.assertEqual(controller.search_target([ally], [], 3), (320., 160.))
        self.assertTrue(any(name == 'training_survivor_search_started' for name, _ in events))


if __name__ == '__main__': unittest.main()
