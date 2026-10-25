import re
import unittest
from types import SimpleNamespace as N
from training_map import source_map, patch_script, MATCHUPS
from training import board_signal
from w3mpq import Mpq


def body(script,name):
    return re.search(r'function '+name+r' takes[^\n]*\n(.*?)endfunction',script,re.S).group(1)


class CountdownTimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=Mpq(source_map()).read('war3map.j')
        cls.original=cls.raw.decode('latin1')
        cls.script=patch_script(cls.raw,'orc',2,'easy').decode('latin1')

    def test_display_and_release_use_same_timer_without_sleep_or_one_shot_zero_poll(self):
        action=body(self.script,'Trig_ComputerForceCountdown_Actions')
        self.assertNotIn('TriggerSleepAction',action)
        self.assertNotIn('TimerGetRemaining',action)
        for side,title in ((0,216),(1,215)):
            self.assertIn(f'CreateTimerDialogBJ( GetLastCreatedTimerBJ(), "TRIGSTR_{title}" )',action)
            self.assertIn(f'TimerStart(GetLastCreatedTimerBJ(), udg_WaitingTime, false, function OWT_CountdownRelease{side})',action)
            self.assertLess(self.script.index('function OWT_CountdownRelease'+str(side)+' takes'),self.script.index('function Trig_ComputerForceCountdown_Actions takes'))
        # No hard-coded multiplier: both clocks now belong to the same engine timer.
        self.assertNotIn('speed',action.lower())

    def test_original_unit_placement_reveal_and_unpause_calls_are_preserved_exactly(self):
        old=body(self.original,'Trig_ComputerForceCountdown_Actions')
        for branch,inner,side in (('011','008',1),('012','007',0)):
            start=old.index(f'        if ( Trig_ComputerForceCountdown_Func{branch}Func{inner}C() ) then')
            end=old.index('set udg_Counting = false',start)
            expected=[line.strip() for line in old[start:end].splitlines() if line.strip().startswith('call ')]
            callback=body(self.script,'OWT_CountdownRelease'+str(side))
            actual=[line.strip() for line in callback.splitlines() if line.strip().startswith('call ')][:len(expected)]
            self.assertEqual(actual,expected)
            self.assertIn('if udg_RoundOver or not udg_Counting then',callback)
            self.assertLess(callback.index('return'),callback.index(expected[0]))
            self.assertLess(callback.index('set udg_Counting = false'),callback.index('SetPlayerState'))
            self.assertNotIn('TriggerSleepAction',callback)

    def test_early_ready_and_original_winner_actions_are_unchanged(self):
        for name in ('Trig_P1_Ready_Vs_Com_Actions','Trig_P2_Ready_Vs_Com_Actions',
                     'Trig_Player1Win_Actions','Trig_Player2Win_Actions'):
            self.assertEqual(body(self.original,name),body(self.script,name))

    def test_dust_delay_uses_game_timer_and_does_not_reenable_after_round_end(self):
        callback=body(self.script,'OWT_CountdownDustReady')
        self.assertIn('DestroyTimer(GetExpiredTimer())',callback)
        self.assertIn('if not udg_RoundOver then',callback)
        self.assertEqual(callback.count('call EnableTrigger'),2)
        for side in (0,1):self.assertIn('TimerStart(CreateTimer(), 30.00, false, function OWT_CountdownDustReady)',body(self.script,'OWT_CountdownRelease'+str(side)))

    def test_periodic_enemy_count_preserves_battle_phase_and_final_result(self):
        action=body(self.script,'Trig_CheckWin10_Actions')
        self.assertIn('if not udg_RoundOver then',action)
        self.assertIn('if udg_Counting then',action)
        self.assertIn('200 + CountUnitsInGroup',action)
        for marker,expected in ((112,(1,12)),(212,(2,12)),(200,(2,0)),(3,(3,None)),(4,(4,None))):
            self.assertEqual(board_signal(N(resources=lambda:{'lumber':marker})),expected)

    def test_all_races_levels_and_modes_keep_countdown_lengths_and_unique_callbacks(self):
        expected=body(self.original,'Trig_ComputerForceCountdown_Actions').split('    if ( Trig_ComputerForceCountdown_Func011C() ) then')[0]
        for race in MATCHUPS:
            for level in range(1,11):
                for mode in ('easy','hard'):
                    script=patch_script(self.raw,race,level,mode).decode('latin1')
                    self.assertTrue(body(script,'Trig_ComputerForceCountdown_Actions').startswith(expected))
                    for name in ('OWT_CountdownRelease0','OWT_CountdownRelease1','OWT_CountdownDustReady'):
                        self.assertEqual(script.count('function '+name+' takes'),1)


if __name__=='__main__':unittest.main()
