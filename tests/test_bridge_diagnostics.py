import mmap
import unittest
import uuid
from unittest.mock import patch

import bridge_diagnostics as d


class BridgeDiagnosticsTests(unittest.TestCase):
    def diagnose(self, *errors):
        with patch.object(d, 'mapping_access', side_effect=[{'winerror':e} for e in errors]) as access:
            result = d.diagnose_unavailable(123, 'SDK original failure')
        self.assertFalse(result['diagnostic']['platform_block_proven'])
        self.assertEqual(result['diagnostic']['sdk_detail'], 'SDK original failure')
        return result, access

    def test_missing_object_is_not_reported_as_platform_rejection(self):
        r, access = self.diagnose(2)
        self.assertEqual(r['bridge_state'], 'mapping_absent')
        self.assertEqual(access.call_count, 1)

    def test_denied_read_does_not_claim_runtime_absent(self):
        r, access = self.diagnose(5)
        self.assertEqual(r['bridge_state'], 'access_denied')
        self.assertEqual(access.call_count, 1)

    def test_readable_but_sdk_all_access_denied(self):
        r, access = self.diagnose(0, 5)
        self.assertEqual(r['bridge_state'], 'access_denied')
        self.assertEqual(access.call_args_list[1].args[1], d.FILE_MAP_ALL)

    def test_incomplete_companion_mapping_retains_evidence(self):
        r, _ = self.diagnose(0, 0, 2, 0)
        self.assertEqual(r['bridge_state'], 'runtime_incomplete_or_incompatible')
        self.assertEqual(r['diagnostic']['checks'][2]['winerror'], 2)

    def test_existing_mappings_do_not_hide_protocol_failure(self):
        r, _ = self.diagnose(0, 0, 0, 0)
        self.assertEqual(r['bridge_state'], 'runtime_incomplete_or_incompatible')

    def test_mapping_disappearing_during_check_is_not_permission_failure(self):
        r, _ = self.diagnose(0, 2)
        self.assertEqual(r['bridge_state'], 'mapping_changed_or_error')

    def test_unknown_windows_error_remains_unknown(self):
        r, _ = self.diagnose(87)
        self.assertEqual(r['bridge_state'], 'mapping_open_error')

    def test_real_windows_mapping_probe_does_not_create_or_retain_object(self):
        name = 'Local\\OpenWar3DiagnosticTest_' + uuid.uuid4().hex
        self.assertEqual(d.mapping_access(name, d.FILE_MAP_READ)['winerror'], 2)
        with mmap.mmap(-1, 4096, tagname=name) as mem:
            mem[:4] = b'test'
            self.assertEqual(d.mapping_access(name, d.FILE_MAP_READ)['winerror'], 0)
            self.assertEqual(d.mapping_access(name, d.FILE_MAP_ALL)['winerror'], 0)
            self.assertEqual(mem[:4], b'test')
        self.assertEqual(d.mapping_access(name, d.FILE_MAP_READ)['winerror'], 2)
