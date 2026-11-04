import hashlib
import re
import unittest

import kfai_map
import sparring_map
from extract_map_pool import parse_w3i, placements
from w3mpq import Mpq


class KfaiMapTests(unittest.TestCase):
    def test_actor_user_option_preserves_default_and_scopes_empty_slot_setup(self):
        from undead.maps import resolve_map
        path,catalog=resolve_map('LR')
        archive=Mpq(path.read_bytes())
        starts=sorted(catalog['starts'],key=lambda row:row['slot'])
        original=archive.read('war3map.j').decode('utf-8')
        default=sparring_map.scenario_script(original,starts)
        self.assertEqual(default,sparring_map.scenario_script(original,starts,actor_user=False))
        user=sparring_map.scenario_script(original,starts,actor_user=True)
        self.assertEqual(default.count(b'Player(1), MAP_CONTROL_COMPUTER'),2)
        setup=re.search(rb'    if \(GetPlayerSlotState\(Player\(1\)\) != PLAYER_SLOT_STATE_PLAYING\) then\n.*?\n    endif\n',user,re.S)
        self.assertIsNotNone(setup)
        self.assertEqual(user[:setup.start()]+user[setup.end():],
                         default.replace(b'Player(1), MAP_CONTROL_COMPUTER',b'Player(1), MAP_CONTROL_USER'))
        metadata=archive.read('war3map.w3i')
        default_meta=sparring_map.lobby_metadata(metadata,starts)
        self.assertEqual(default_meta,sparring_map.lobby_metadata(metadata,starts,actor_user=False))
        user_meta=sparring_map.lobby_metadata(metadata,starts,actor_user=True)
        self.assertEqual(len(default_meta),len(user_meta))
        self.assertEqual([(a,b) for a,b in zip(default_meta,user_meta) if a!=b],[(2,1)])
        self.assertEqual([(p['id'],p['type'],p['race']) for p in parse_w3i(user_meta,{})['players']],
                         [(0,1,1),(1,1,3),(2,2,1)])

    def test_empty_actor_uses_version_resources_and_cleanup_without_extra_hero_grants(self):
        path,_=kfai_map.prepare_map()
        script=Mpq(path.read_bytes()).read('war3map.j').decode('utf-8')
        body=re.search(r'function Trig________________uActions .*?endfunction',script,re.S).group()
        setup=re.search(r'    if \(GetPlayerSlotState\(Player\(1\)\) != PLAYER_SLOT_STATE_PLAYING\) then\n(.*?)\n    endif',body,re.S).group(1)
        version=re.search(r'if \(VersionGet\(\) == VERSION_REIGN_OF_CHAOS\) then\n(.*?)        else\n(.*?)        endif',setup,re.S)
        for branch,suffix in zip(version.groups(),('V0','V1')):
            assignments=re.findall(r'SetPlayerState\(Player\((\d+)\), PLAYER_STATE_RESOURCE_(\w+), (\w+)\)',branch)
            self.assertEqual(assignments,[('1','GOLD','bj_MELEE_STARTING_GOLD_'+suffix),
                                          ('1','LUMBER','bj_MELEE_STARTING_LUMBER_'+suffix)])
        self.assertIn('MeleeClearNearbyUnits(GetStartLocationX(GetPlayerStartLocation(Player(1))), GetStartLocationY(GetPlayerStartLocation(Player(1))), bj_MELEE_CLEAR_UNITS_RADIUS)',setup)
        self.assertLess(body.index('MeleeClearExcessUnits()'),body.index('GetPlayerSlotState(Player(1))'))
        self.assertLess(body.index('MeleeClearNearbyUnits('),body.index('MeleeStartingUnitsUndead('))
        for call in ('MeleeStartingHeroLimit()', 'MeleeGrantHeroItems()',
                     'MeleeStartingUnitsUndead(Player(1), GetStartLocationLoc(1), true, true, false)'):
            self.assertEqual(body.count('call '+call),1)
        self.assertNotIn('UnitAddItemById(',body)
        self.assertNotIn('PLAYER_STATE_RESOURCE_HERO_TOKENS',body)

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
        self.assertEqual([(p['id'],p['type'],p['race']) for p in meta['players']], [(0,1,1),(1,1,3),(2,2,1)])
        for slot,controller in ((0,'USER'),(1,'USER'),(2,'COMPUTER')):
            self.assertIn(f'SetPlayerController(Player({slot}), MAP_CONTROL_{controller})',script)
            self.assertIn(f'SetPlayerSlotAvailable(Player({slot}), MAP_CONTROL_{controller})',script)
        self.assertIn('SetPlayerState(Player(0), PLAYER_STATE_OBSERVER, 1)',script)
        for a,b in ((1,2),(2,1)):
            self.assertIn(f'SetPlayerAlliance(Player({a}), Player({b}), ALLIANCE_PASSIVE, false)',script)
            self.assertIn(f'SetPlayerAlliance(Player({a}), Player({b}), ALLIANCE_SHARED_VISION, false)',script)
        self.assertNotIn('call MeleeStartingAI()', script)
        self.assertEqual(script.count('call StartMeleeAI(Player(2), "human.ai")'), 1)
        hero = re.search(r'function AIsystem___RegisterAICenter .*?endfunction', script, re.S).group()
        self.assertIn('AIsystem___Melee_AI_On[GetPlayerId(GetOwningPlayer(hero))] == true', hero)
        self.assertIn('GetPlayerController(GetOwningPlayer(hero)) == MAP_CONTROL_COMPUTER',hero)
        body = re.search(r'function MeleeAIsystem_Start .*?endfunction', script, re.S).group()
        self.assertIn('AIsystem_SetAIplayer(Player(1), false)', body)
        self.assertNotIn('AIsystem_SetAIplayer(Player(1), true)',body)
        self.assertIn('AIsystem_SetAIplayer(Player(2), true)', body)
        self.assertEqual(hashlib.sha256(kfai_map.SOURCE.read_bytes()).hexdigest(), kfai_map.SOURCE_SHA)
        self.assertEqual(catalog['opponent_fairness'], 'native_KFAI_unverified')


if __name__ == '__main__':
    unittest.main()
