import hashlib
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import psutil
import attachment_setup as setup
import attach_match as attach
from tests.test_attach_0155 import FakeGame


class MapIdentityTests(unittest.TestCase):
    def identify(self, mode='known'):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'kk-hashed-name.w3x';path.write_bytes(b'known map')
            catalog=dict(alias='TH',name='Known',map_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         starts=[dict(x=-1,y=1),dict(x=1,y=1)],camps=[dict(id='th-camp')],critters=[],neutral_buildings=[])
            if mode=='changed':path.write_bytes(b'modified map')
            files=[N(path=str(path))]
            if mode=='ambiguous':files.append(N(path=str(Path(directory)/'other.w3x')))
            if mode=='missing':files=[]
            process=N(open_files=lambda:files)
            live=N(starts=[(-1,1),(1,1),(0,0)] if mode!='wrong_starts' else [(-9,9),(9,9)])
            with patch.object(setup.psutil,'Process',return_value=process),patch('openwar3.mapdata.running_map_path',return_value=None),patch('undead.maps.pool',return_value={'TH':catalog}),patch('undead.maps.profiles',return_value={'local':{'maps':{}}}):
                return setup.identify_map(123,live)

    def test_actual_open_map_hash_and_live_starts_bind_despite_hashed_filename(self):
        catalog,info=self.identify()
        self.assertEqual(info['status'],'verified')
        bot=N(creeping=N(),start_search=N(),critter_search=N())
        setup.bind_map(bot,catalog)
        self.assertEqual(bot.creeping.catalog[0]['id'],'th-camp')
        self.assertEqual(bot.start_search.camps,bot.creeping.catalog)

    def test_unknown_modified_ambiguous_or_missing_map_never_uses_default(self):
        for mode,reason in [('changed','unknown_map_fingerprint'),('wrong_starts','live_starts_mismatch'),
                            ('ambiguous','ambiguous_map_files'),('missing','map_file_unavailable')]:
            catalog,info=self.identify(mode)
            self.assertIsNone(catalog,mode);self.assertEqual(info['reason'],reason)
            bot=N(creeping=N(catalog=[1],map_alias='old'),start_search=N(camps=[1]),critter_search=N(spawns=[1]),tavern_sites=[1])
            setup.bind_map(bot,catalog)
            self.assertFalse(bot.start_search.camps or bot.creeping.catalog or bot.critter_search.spawns or bot.tavern_sites)
            self.assertIsNone(bot.creeping.map_alias)

    def test_permission_error_reports_unknown_without_scanning_unrelated_maps(self):
        with patch.object(setup.psutil,'Process',side_effect=psutil.AccessDenied(123)):
            catalog,info=setup.identify_map(123,None)
        self.assertIsNone(catalog);self.assertEqual(info['reason'],'map_read_failed')

    def test_binding_activates_existing_map_route_and_tavern_without_hidden_state(self):
        from undead.maps import pool
        from undead.creeping import Creeping
        catalog=pool()['TH']
        bot=N(creeping=Creeping(lambda *a,**k:None,camps=[]),start_search=N(),critter_search=N())
        home=N(x=catalog['starts'][0]['x'],y=catalog['starts'][0]['y'])
        bot.creeping.map_alias='TH'
        self.assertFalse(bot.creeping.th_route(home))
        setup.bind_map(bot,catalog)
        route=bot.creeping.th_route(home)
        self.assertTrue(route)
        self.assertTrue(set(route)<={c['id'] for c in bot.creeping.catalog})
        self.assertEqual(bot.critter_search.spawns,catalog['critters'])
        self.assertTrue(bot.tavern_sites)


class OpponentTests(unittest.TestCase):
    def identify(self,race=2,active=(4,8),enemy=True,fail=False):
        closed=[]
        def getrace(p):
            if fail:raise RuntimeError('query timeout')
            return race
        # No unit, inventory or resource API: accidental private reads fail.
        j=N(Player=lambda i:i,GetPlayerSlotState=lambda i:1 if i in active else 0,
            IsPlayerEnemy=lambda p,me:enemy,GetPlayerRace=getrace,GetPlayerController=lambda p:1)
        with patch('undead.game_view.Game',return_value=N(jass=j,close=lambda:closed.append(True))):
            try:return setup.identify_opponent(123,4)
            finally:self.assertEqual(closed,[True])

    def test_detects_four_races_with_nonzero_nonadjacent_slots(self):
        for race in range(1,5):
            row=self.identify(race)
            self.assertEqual(row['race'],race);self.assertEqual(row['slot'],8)

    def test_unknown_race_does_not_guess_and_allies_or_extra_players_rejected(self):
        self.assertEqual(self.identify(0)['race'],0)
        unknown=self.identify(fail=True)
        self.assertEqual(unknown['status'],'verified');self.assertEqual(unknown['race'],0)
        for kwargs in ({'active':(4,8,9)},{'active':(0,8)},{'enemy':False}):
            with self.assertRaises(setup.UnsupportedMatch):self.identify(**kwargs)


class SetupLifecycleTests(unittest.TestCase):
    def run_case(self,opponent,map_catalog=None,requested_race=3):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'undead').mkdir();(root/'data').mkdir()
            for name in ('attach_match.py','attachment_setup.py','kk_control.py','bridge_diagnostics.py','bot.py','data/kk_map_pool.json','data/machine_profiles.json'):
                (root/name).write_text('# fixture')
            g=FakeGame();metadata=dict(ready=True,process={'pid':123},player=4,epoch=7,clock=100)
            loops=[]
            def loop(game,meta,race,log):
                loops.append((race,game.attachment_catalog))
                return N(paused=True,step=lambda action:'released_by_user')
            with patch.object(attach,'ROOT',root),patch.object(attach,'STATE',root/'state.json'),patch.object(attach,'COMMAND',root/'command.json'),patch.object(attach,'RunnerLock',return_value=nullcontext()),patch.object(attach,'probe',return_value=metadata),patch.object(attach,'still_same',return_value=True),patch('undead.game_view.Game',return_value=g),patch.object(setup,'identify_map',return_value=(map_catalog,dict(status='verified' if map_catalog else 'unidentified'))),patch.object(setup,'identify_opponent',return_value=opponent),patch.object(attach,'Attachment',side_effect=loop):
                result=attach.run_attachment(123,enemy_race=requested_race)
            state=json.loads((root/'state.json').read_text())
            self.assertTrue(g.closed)
            return result,state,loops

    def test_verified_current_race_overrides_old_manual_setting_and_passes_map(self):
        catalog={'alias':'LR'}
        result,state,loops=self.run_case(dict(status='verified',race=4,race_basis='player_setup'),catalog)
        self.assertEqual(loops,[(4,catalog)])
        self.assertEqual(result['opponent']['race'],4)
        self.assertTrue(state['closed'])
        from undead.version import VERSION
        self.assertEqual(result['version'],VERSION)

    def test_unverified_player_slots_never_start_controller(self):
        result,state,loops=self.run_case(dict(status='unavailable',race=0,error='timeout'))
        self.assertFalse(loops)
        self.assertEqual(result['result'],'error')
        self.assertTrue(state['paused'] and state['closed'])

    def test_unknown_setup_race_reaches_visible_detection_and_survives_pause(self):
        result,state,loops=self.run_case(dict(status='verified',race=0,race_basis='await_visible_enemy'),requested_race=0)
        self.assertEqual(loops,[(0,None)])
        from undead.controller import Controller
        bot=N(enemy_race=0,g=N(me=lambda:4),tavern_mission=None,economy=N(ever_heroes=set()),
              log=lambda *a,**k:None)
        foe=N(type='ewsp',owner=8,alive=True,visible_to=lambda player:False)
        Controller.observe_race(bot,[foe],1)
        self.assertEqual(bot.enemy_race,0)
        foe.visible_to=lambda player:True
        Controller.observe_race(bot,[foe],2)
        self.assertEqual(bot.enemy_race,4)
        self.assertEqual(bot.third_hero,'Nngs')
        g=FakeGame();made=[]
        def factory(game,log,race):
            made.append(race)
            return N(enemy_race=race,economy=N(ever_heroes=set()),intent='test',
                     observe_events=lambda e:None,tick=lambda:None)
        loop=attach.Attachment(g,dict(epoch=7,player=4,clock=100),0,lambda *a,**k:None,factory)
        loop.step('resume',0);loop.bot.enemy_race=4
        loop.step('pause',1);loop.step('resume',2)
        self.assertEqual(made,[0,4])
