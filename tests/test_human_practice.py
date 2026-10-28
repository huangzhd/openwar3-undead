import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace as N
from unittest.mock import patch

import human_practice as practice
import w3claim
import w3fast
import w3world
from undead.game_view import Game


class PracticeSetupTests(unittest.TestCase):
    def setup_game(self, *, active=(0, 1), local=0, controllers=(0, 1),
                   races=(2, 3), enemies=True, pause_error=False):
        paused=[];closed=[]
        handles={i:100+i for i in range(12)}
        def pause(player, value):
            if pause_error:raise RuntimeError('pause failed')
            paused.append((player, value))
        def enemy(a,b):
            return enemies if isinstance(enemies,bool) else enemies[0 if (a,b)==(100,101) else 1]
        jass=N(Player=lambda slot:handles[slot],
               GetPlayerSlotState=lambda player:int(player-100 in active),
               GetPlayerController=lambda player:controllers[player-100],
               GetPlayerRace=lambda player:races[player-100],
               IsPlayerEnemy=enemy,
               IsPlayerAlly=lambda a,b:not enemy(a,b),
               PauseCompAI=pause)
        setup=N(world=N(read=lambda:N(in_game=True,me=local)),jass=jass)
        @contextmanager
        def connect(*args, **kwargs):
            try:yield setup
            finally:closed.append(True)
        return connect,paused,closed

    def test_human_orc_and_computer_undead_pause_only_p1_then_publish_identity(self):
        connect,paused,closed=self.setup_game()
        session=practice.HumanPracticeSession(2,'LR')
        with patch.object(practice,'Game',side_effect=connect):
            session.prepare_players(123)
        self.assertEqual(paused,[(101,True)])
        self.assertTrue(closed)
        self.assertEqual(session.settings['verified_players'],[
            dict(slot=0,controller=0,race=2),dict(slot=1,controller=1,race=3)])
        self.assertEqual(session.settings['controlled_player'],1)
        self.assertEqual(session.settings['human_player'],0)
        self.assertTrue(session.settings['native_ai_paused'])
        self.assertTrue(session.settings['fair'])

    def test_second_human_wrong_race_extra_player_and_nonlocal_p0_refuse_before_pause(self):
        cases=[dict(controllers=(0,0)),dict(controllers=(1,1)),dict(races=(1,3)),
               dict(races=(2,2)),dict(active=(0,1,2)),dict(active=(0,)),dict(local=1)]
        for settings in cases:
            with self.subTest(settings=settings):
                connect,paused,closed=self.setup_game(**settings)
                session=practice.HumanPracticeSession(2,'LR')
                with patch.object(practice,'Game',side_effect=connect),self.assertRaises(RuntimeError):
                    session.prepare_players(123)
                self.assertEqual(paused,[])
                self.assertNotIn('native_ai_paused',session.settings)
                self.assertTrue(closed)

    def test_allied_slots_are_not_a_practice_opponent(self):
        for enemies in ((False,False),(False,True),(True,False)):
            with self.subTest(enemies=enemies):
                connect,paused,closed=self.setup_game(enemies=enemies)
                session=practice.HumanPracticeSession(2,'LR')
                with patch.object(practice,'Game',side_effect=connect),self.assertRaises(RuntimeError):
                    session.prepare_players(123)
                self.assertEqual(paused,[])
                self.assertNotIn('native_ai_paused',session.settings)
                self.assertTrue(closed)

    def test_failed_pause_never_marks_takeover_ready_and_releases_setup_client(self):
        connect,paused,closed=self.setup_game(pause_error=True)
        session=practice.HumanPracticeSession(2,'LR')
        with patch.object(practice,'Game',side_effect=connect),self.assertRaisesRegex(RuntimeError,'pause failed'):
            session.prepare_players(123)
        self.assertEqual(paused,[])
        self.assertNotIn('native_ai_paused',session.settings)
        self.assertNotIn('controlled_player',session.settings)
        self.assertTrue(closed)


class PracticeIdentityTests(unittest.TestCase):
    def unit(self, owner, code, addr, visible):
        return N(owner=owner,type=code,addr=addr,handle_lo=addr,handle_hi=7,
                 handle=(addr,7),alive=True,x=0,y=0,visible_to=lambda p:p in visible)

    @contextmanager
    def game(self):
        mine=self.unit(1,'uaco',101,{1})
        hidden=self.unit(0,'opeo',201,{0})
        visible=self.unit(0,'ogru',202,{0,1})
        raw=w3world.WorldState(1,0,5.,1,0,True,100,50,0,0,0,
            [w3world.Player(0,9999,999,90,100,10,20,2,True),
             w3world.Player(1,125,40,8,12,30,40,3,True)],
            [mine,hidden,visible],[],by_handle={u.handle:u for u in (mine,hidden,visible)})
        submissions=[];lanes=[];leased=[]
        def lane(pid, role=w3fast.ROLE_DEV, player=0):
            def commands(calls,*args,**kwargs):
                submissions.extend((role,player,call) for call in calls)
                return [w3fast.Receipt(call.op,0,1,None,0,0,(0,)*8) for call in calls]
            result=N(commands=commands,close=lambda:None,role=role,player=player)
            lanes.append(result)
            return result
        world=N(read=lambda:raw,close=lambda:None)
        claims=N(take=lambda addr,*args,**kwargs:leased.append(addr) or True)
        with patch.dict(os.environ),patch.object(w3world,'World',return_value=world), \
             patch.object(w3fast,'FastLane',side_effect=lane),patch.object(w3claim,'Claims',return_value=claims):
            g=Game(pid=123,player=1,fair=True)
            try:yield g,raw,mine,hidden,visible,submissions,leased
            finally:g.close()

    def test_real_sdk_view_uses_p1_resources_and_only_p1_visible_units_without_mutating_p0(self):
        with self.game() as (g,raw,mine,hidden,visible,sent,leased):
            view=g.snapshot(max_age=0)
            self.assertEqual(g.me(),1)
            self.assertEqual((view.gold,view.lumber,view.food_used,view.food_cap),(125,40,8,12))
            self.assertEqual(g.resources(),dict(gold=125,lumber=40,food_used=8,food_cap=12,
                                                gold_gathered=30,lumber_gathered=40))
            self.assertEqual(g.my_units(),[mine])
            self.assertEqual(g.enemies(),[visible])
            self.assertNotIn(hidden.handle,view.by_handle)
            self.assertEqual((raw.me,raw.gold),(0,9999))
            self.assertIn(hidden,raw.units)
            self.assertEqual(sent,[])

    def test_missing_p1_resource_data_never_borrows_human_money(self):
        with self.game() as (g,raw,*_):
            raw.players[1].known=False
            view=g.snapshot(max_age=0)
            self.assertFalse(view.resources_known)
            self.assertIsNone(view.gold)
            self.assertIsNone(g.resources())
            self.assertEqual(raw.gold,9999)

    def test_real_sdk_order_for_own_workers_uses_p1_lane_and_never_targets_human_as_actor(self):
        with self.game() as (g,raw,mine,hidden,visible,sent,leased):
            receipts=g.move(g.my_workers(),512,256)
            self.assertTrue(all(receipt.ok for receipt in receipts))
            self.assertEqual(leased,[mine.addr])
            self.assertTrue(sent)
            for role,player,call in sent:
                self.assertEqual((role,player),(w3fast.ROLE_PLAYER,1))
                self.assertEqual(call.op,w3fast.OP['point'])
                self.assertEqual(call.args[:3],[mine.addr,mine.handle_lo,mine.handle_hi])
                self.assertNotIn(call.args[0],(hidden.addr,visible.addr))


if __name__=='__main__':unittest.main()
