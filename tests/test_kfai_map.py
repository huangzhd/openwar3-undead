import hashlib
import re
import unittest

import kfai_map
from extract_map_pool import parse_w3i, placements
from w3mpq import Mpq


class KfaiMapTests(unittest.TestCase):
    def test_opt_in_trace_changes_only_human_ai_and_keeps_default_map(self):
        from kfai_strategy import patch_human_ai,HUMAN_AI_MEMBER
        plain,_=kfai_map.prepare_map()
        traced,catalog=kfai_map.prepare_map(strategy_trace=True)
        before,after=Mpq(plain.read_bytes()),Mpq(traced.read_bytes())
        for name in before.read('(listfile)').decode('utf-8').splitlines():
            if name not in (HUMAN_AI_MEMBER,'(attributes)','(listfile)'):
                self.assertEqual(before.read(name),after.read(name),name)
        self.assertEqual(after.read(HUMAN_AI_MEMBER),patch_human_ai(before.read(HUMAN_AI_MEMBER)))
        from kfai_strategy import PUBLISHER,MISSION
        restored=after.read(HUMAN_AI_MEMBER).decode('utf-8').replace('\r\n','\n').replace(PUBLISHER,'')
        restored=restored.replace('  call FlushStoredMission(amaiCache, "'+MISSION+'")\n','')
        restored=restored.replace('      call DAYUAN_RecordStrategy()\n','')
        self.assertEqual(restored,before.read(HUMAN_AI_MEMBER).decode('utf-8').replace('\r\n','\n'))
        self.assertNotEqual(plain,traced)
        self.assertEqual(kfai_map.prepare_map()[0],plain)
        with self.assertRaises(ValueError):patch_human_ai(after.read(HUMAN_AI_MEMBER))
        with self.assertRaises(ValueError):patch_human_ai(before.read(HUMAN_AI_MEMBER).replace(b'call init_strategy()',b'call changed()'))
        self.assertFalse(catalog['strategy_trace']['live_verified'])

    def test_derivative_preserves_assets_and_isolates_native_ai(self):
        original = kfai_map.SOURCE.read_bytes()
        path, catalog = kfai_map.prepare_map()
        before, after = Mpq(original), Mpq(path.read_bytes())
        for name in before.read('(listfile)').decode('utf-8').splitlines():
            if name not in ('war3map.j', 'war3map.w3i', '(listfile)', '(attributes)'):
                self.assertEqual(before.read(name), after.read(name), name)
        script = after.read('war3map.j').decode('utf-8')
        old = before.read('war3map.j').decode('utf-8')
        for fn in ('CreateNeutralHostile', 'CreateNeutralPassive', 'CreateNeutralPassiveBuildings'):
            self.assertEqual(placements(old, fn), placements(script, fn))
        meta = parse_w3i(after.read('war3map.w3i'), {})
        self.assertEqual([(p['id'],p['type']) for p in meta['players']], [(0,1),(1,2),(2,2)])
        self.assertNotIn('call MeleeStartingAI()', script)
        self.assertEqual(script.count('call StartMeleeAI(Player(2), "human.ai")'), 1)
        hero = re.search(r'function AIsystem___RegisterAICenter .*?endfunction', script, re.S).group()
        self.assertIn('AIsystem___Melee_AI_On[GetPlayerId(GetOwningPlayer(hero))] == true', hero)
        body = re.search(r'function MeleeAIsystem_Start .*?endfunction', script, re.S).group()
        self.assertIn('AIsystem_SetAIplayer(Player(1), false)', body)
        self.assertIn('AIsystem_SetAIplayer(Player(2), true)', body)
        self.assertEqual(hashlib.sha256(kfai_map.SOURCE.read_bytes()).hexdigest(), kfai_map.SOURCE_SHA)
        self.assertEqual(catalog['opponent_fairness'], 'native_KFAI_unverified')


if __name__ == '__main__':
    unittest.main()
