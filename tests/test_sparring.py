import contextlib
import hashlib
import struct
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock,patch

import sparring
import sparring_map
from human_practice import HumanPracticeSession
from undead.maps import resolve_map
from w3mpq import Mpq,decrypt


class ObserverMapTests(unittest.TestCase):
    def test_staging_preserves_bytes_and_refuses_overwriting_a_changed_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'scenario.w3x';source.write_bytes(b'original scenario')
            target=sparring_map.stage_map(source,root/'game')
            self.assertEqual(target.parent,root/'game'/'Maps'/'dayuan')
            self.assertEqual(target.read_bytes(),source.read_bytes())
            self.assertEqual(sparring_map.stage_map(source,root/'game'),target)
            target.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):sparring_map.stage_map(source,root/'game')
            self.assertEqual(target.read_bytes(),b'changed')
            self.assertEqual(source.read_bytes(),b'original scenario')

    def test_replacement_roundtrip_keeps_original_archive_members_unchanged(self):
        original,catalog=resolve_map('LR');blob=original.read_bytes();before=Mpq(blob)
        changed=sparring_map.replace_members(blob,{'war3map.j':b'new script'})
        after=Mpq(changed)
        self.assertEqual(after.read('war3map.j'),b'new script')
        self.assertEqual(before.hash,after.hash)
        # StormLib also updates archive bookkeeping; game resources must stay intact.
        mutable=[before._find(name) for name in ('war3map.j','(listfile)','(attributes)')]
        for index in range(len(before.block)//16):
            old=struct.unpack_from('<IIII',before.block,index*16)
            new=struct.unpack_from('<IIII',after.block,index*16)
            if old!=new:self.assertIn(old,mutable)
            else:
                self.assertEqual(blob[before.base+old[0]:before.base+old[0]+old[1]],
                                 changed[after.base+new[0]:after.base+new[0]+new[1]])
        for name in before.read('(listfile)').decode('utf-8').splitlines():
            if name not in ('war3map.j','(listfile)','(attributes)'):
                self.assertEqual(before.read(name),after.read(name),name)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),catalog['map_sha256'])

    def test_observer_scenario_has_fixed_bot_slots_and_does_not_change_camps_or_objects(self):
        from extract_map_pool import parse_w3i,placements
        path,catalog=sparring_map.prepare_map('LR')
        original=Path(catalog['source_map_path']);a,b=Mpq(original.read_bytes()),Mpq(path.read_bytes())
        metadata=parse_w3i(b.read('war3map.w3i'),{})
        header=path.read_bytes();pos=header.index(b'\0',8)+1
        self.assertEqual(struct.unpack_from('<II',header,pos),(metadata['flags'],len(metadata['players'])))
        self.assertEqual([(r['id'],r['type'],r['race']) for r in metadata['players']],[(0,1,1),(1,2,3),(2,2,1)])
        old,new=a.read('war3map.j').decode('utf8'),b.read('war3map.j').decode('utf8')
        for fn in ('CreateNeutralHostile','CreateNeutralPassive','CreateNeutralPassiveBuildings'):
            self.assertEqual(placements(old,fn),placements(new,fn))
        for name in ('war3map.w3e','war3map.doo','war3mapUnits.doo','war3map.w3u','war3map.w3t','war3map.w3a'):
            self.assertEqual(a.read(name),b.read(name),name)
        self.assertIn('SetPlayerState(Player(0), PLAYER_STATE_OBSERVER, 1)',new)
        self.assertNotIn('call MeleeStartingAI()',new)
        self.assertNotIn('call MeleeStartingUnits()',new)
        self.assertNotIn('exec-lua:war3map',new)
        self.assertNotIn('FogEnable(false)',new)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),catalog['source_map_sha256'])
        self.assertEqual(sparring_map.prepare_map('LR')[0],path)

    def test_unknown_map_and_script_shape_refused(self):
        with self.assertRaises(ValueError):sparring_map.prepare_map('TM')
        with self.assertRaises(ValueError):sparring_map.scenario_script('function main takes nothing returns nothing\nendfunction',[])


class SparringSessionTests(unittest.TestCase):
    def setup_connection(self,observer=True,owned_observer=False,shared=False,native=False):
        paused=[]
        j=N(Player=lambda i:i,GetPlayerSlotState=lambda i:int(i in (0,1,2)),
            GetPlayerController=lambda i:int(i!=0 and not (native and i==1)),GetPlayerRace=lambda i:3 if i==1 else 1,
            IsPlayerObserver=lambda i:observer if i==0 else False,
            IsPlayerEnemy=lambda a,b:{a,b}=={1,2},GetPlayerAlliance=lambda a,b,k:shared,
            PauseCompAI=lambda i,v:paused.append((i,v)))
        raw=N(in_game=True,me=0,units=[N(alive=True,owner=0)] if owned_observer else [])
        @contextlib.contextmanager
        def connect(**kw):
            import w3claim
            self.assertIn(kw.get('owner','bot'),w3claim.MODULES)
            import w3fast
            yield N(world=N(read=lambda:raw),jass=j,_w3fast=w3fast,
                    lane=N(commands=lambda calls:[N(ok=True) for _ in calls]))
        return connect,paused

    def test_setup_pauses_only_competing_players_and_requires_observer(self):
        connect,paused=self.setup_connection()
        session=sparring.SparringSession('human-rifle')
        with patch.object(sparring,'Game',side_effect=connect):session.prepare_players(123)
        self.assertEqual(paused,[(1,True),(2,True)])
        self.assertEqual(session.settings['observer_player'],0)
        self.assertFalse(session.settings['background_supported'])
        for options in (dict(observer=False),dict(owned_observer=True),dict(shared=True)):
            connect,paused=self.setup_connection(**options)
            with patch.object(sparring,'Game',side_effect=connect),self.assertRaises(RuntimeError):session.prepare_players(123)
            self.assertFalse(paused)

    def test_native_kfai_keeps_opponent_running_and_only_observes_it(self):
        connect,paused=self.setup_connection()
        session=sparring.SparringSession('kfai-human')
        with patch.object(sparring,'Game',side_effect=connect):session.prepare_players(123)
        self.assertEqual(paused,[(1,True)])
        self.assertEqual(session.settings['opponent_fairness'],'native_KFAI_unverified')
        snap=N(resources_known=True,epoch=73,me=2,in_game=True,clock=40)
        session.opponent_game=N(snapshot=lambda **kw:snap,resources=lambda:dict(lumber_gathered=20),
                                my_units=lambda:[N(type='hpea')])
        session.opponent_log=Mock();session.opponent_summary_at=-100
        self.assertTrue(session.tick_opponent(73))
        self.assertEqual(session.opponent_log.call_args.kwargs['resources']['lumber_gathered'],20)

    def test_epoch_and_player_guard_prevent_orders_after_new_match(self):
        for override in ({'epoch':74},{'me':0},{'in_game':False}):
            session=sparring.SparringSession('human-rifle')
            snap=N(**dict(dict(resources_known=True,epoch=73,me=2,in_game=True),**override))
            session.opponent_game=N(snapshot=lambda **kw:snap);session.opponent=Mock()
            with self.assertRaises(RuntimeError):session.tick_opponent(73)
            session.opponent.tick.assert_not_called()

    def test_missing_resources_suppresses_both_bot_tick_then_times_out(self):
        session=sparring.SparringSession('human-rifle')
        session.opponent_game=N(snapshot=lambda **kw:N(resources_known=False));session.opponent=Mock()
        with patch.object(sparring.time,'monotonic',return_value=0):self.assertFalse(session.tick_opponent(73))
        with patch.object(sparring.time,'monotonic',return_value=11),self.assertRaises(RuntimeError):session.tick_opponent(73)
        session.opponent.tick.assert_not_called()

    def test_opponent_close_failure_still_cleans_up_owned_session(self):
        session=sparring.SparringSession('human-rifle')
        session.opponent_game=N(close=Mock(side_effect=RuntimeError('close failed')))
        with patch.object(HumanPracticeSession,'stop') as cleanup,self.assertRaises(RuntimeError):session.stop()
        cleanup.assert_called_once()
        self.assertIsNone(session.opponent_game)


class ObserverFairViewTests(unittest.TestCase):
    def test_observer_full_vision_never_becomes_either_bot_vision_or_resources(self):
        import os,w3world,w3fast,w3claim
        from undead.game_view import Game
        units=[]
        for owner,code in ((1,'uaco'),(2,'hpea')):
            units.append(N(owner=owner,type=code,addr=owner*100,handle=(owner*100,7),alive=True,
                           x=owner*2000,y=0,visible_to=lambda p,o=owner:p in (0,o)))
        raw=w3world.WorldState(1,0,5.,1,0,True,100,50,0,0,0,
             [w3world.Player(i,100+i,40+i,5,12,0,0,3 if i==1 else 1,True) for i in range(3)],
             units,[],by_handle={u.handle:u for u in units})
        with patch.dict(os.environ),patch.object(w3world,'World',side_effect=lambda pid:N(read=lambda:raw,close=lambda:None)), \
             patch.object(w3fast,'FastLane',side_effect=lambda *a,**kw:N(close=lambda:None)), \
             patch.object(w3claim,'Claims',return_value=N()):
            games=[Game(pid=123,player=i,fair=True) for i in (1,2)]
            try:
                for i,g in enumerate(games,1):
                    self.assertEqual(g.my_units(),[units[i-1]])
                    self.assertEqual(g.enemies(),[])
                    self.assertEqual(g.resources()['gold'],100+i)
                    self.assertEqual(raw.me,0)
            finally:
                for g in games:g.close()


if __name__=='__main__':unittest.main()
