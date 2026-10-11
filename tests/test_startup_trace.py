import unittest
from types import SimpleNamespace as N
from unittest.mock import patch

import psutil
import trace_kk_startup as t


class StartupTraceTests(unittest.TestCase):
    row = {'pid':123, 'create_time':42}

    def test_access_denied_is_unknown_not_exit(self):
        with patch.object(t.psutil, 'Process', side_effect=psutil.AccessDenied(123)):
            self.assertEqual(t.game_liveness(self.row), 'unknown')

    def test_pid_reuse_and_exit_are_distinct(self):
        with patch.object(t.psutil, 'Process', return_value=N(create_time=lambda:43)):
            self.assertEqual(t.game_liveness(self.row), 'pid_reused')
        with patch.object(t.psutil, 'Process', side_effect=psutil.NoSuchProcess(123)):
            self.assertEqual(t.game_liveness(self.row), 'exited')

    def test_module_access_denied_does_not_suppress_independent_ipc_check(self):
        events = []
        def denied(): raise psutil.AccessDenied(123)
        with patch.object(t, 'game_liveness', return_value='alive'), patch.object(t.psutil, 'Process', return_value=N(memory_maps=denied)), patch.object(t, 'mapping_access', return_value={'winerror':2}) as access:
            t.sample_game(self.row, lambda event,**data:events.append((event,data)), {})
        access.assert_called_once()
        self.assertEqual([event for event,_ in events], ['module_sample_error','bridge_access'])
        self.assertEqual(events[-1][1]['winerror'], 2)

    def test_identity_change_before_ipc_check_stops_sampling(self):
        events = []
        with patch.object(t, 'game_liveness', side_effect=['alive','pid_reused']), patch.object(t.psutil, 'Process', return_value=N(memory_maps=lambda:[])), patch.object(t, 'mapping_access') as access:
            t.sample_game(self.row, lambda event,**data:events.append(event), {})
        access.assert_not_called()
