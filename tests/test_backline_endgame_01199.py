import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
from unittest.mock import patch

import training_control as panel
import test_lich_safety_panel_01198 as prior
import test_debug_console as console_tests
import test_rod_escape_0168 as rod_tests
import test_training_orc_focus_01180 as arena
from training import TrainingController
from undead.controller import Controller
from undead.debug_console import ActionMeter
from undead.policy import Action
from test_baseline import unit


class SharedBacklineTests(unittest.TestCase):
    def test_dark_ranger_and_lich_are_independently_guarded_in_both_modes(self):
        outputs=[]
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,lich,dk=prior.LichSafetyTests().scene(kind)
            dark=next(u for u in own if u.type=='Nbrn');dark.hp=270
            pulls={};b.rear_backline(own,foes,10,pulls)
            self.assertIn(dark.handle,pulls);self.assertIn(lich.handle,pulls)
            dark.x,dark.y=pulls[dark.handle]
            b.rear_backline(own,foes,11,pulls)
            self.assertTrue(any(o[0]=='attack' and o[1]==dark.handle for o in orders))
            self.assertIn(dark.handle,b.backline_guards)
            outputs.append((pulls,orders))
        self.assertEqual(*outputs)

    def test_dark_ranger_releases_when_dk_can_heal_and_does_not_share_lich_state(self):
        b,g,own,foes,orders,events,effects,lich,dk=prior.LichSafetyTests().scene()
        dark=next(u for u in own if u.type=='Nbrn');dark.hp=270
        b.rear_backline(own,foes,10,{})
        dark.hp=600
        b.rear_backline(own,foes,11,{})
        self.assertNotIn(dark.handle,b.backline_guards)
        self.assertIn(lich.handle,b.backline_guards)
        dark.hp=270;b.rear_backline(own,foes,12,{})
        dk.mana=100;b.rescue_coil_ready=lambda *a:True
        b.rear_backline(own,foes,13,{})
        self.assertNotIn(dark.handle,b.backline_guards)


class EndgameTests(unittest.TestCase):
    def scene(self):
        b,g,own,foes,orders,events,effects=arena.TrainingOrcFocusTests().scene()
        b.update_training_phase(1,50,False)
        b.update_training_phase(20,13,True)
        return b,g,own,foes,orders,events,effects

    def test_initial_wait_ignores_countdown_resources_and_late_count_unlocks(self):
        b,g,own,foes,orders,events,effects=self.scene()
        self.assertFalse(b.training_endgame)
        self.assertEqual(b.training_peak_enemies,13)
        b.blight_waiting=True
        b.update_training_phase(70,4,True)
        self.assertTrue(b.training_endgame)
        self.assertFalse(b.wait_for_enemy_opening);self.assertFalse(b.blight_waiting)
        self.assertFalse(b.hold_blight_opening(own,71))
        b.update_training_phase(90,5,True)
        self.assertTrue(b.training_endgame) # Summons do not restore opening wait.
        self.assertFalse(hasattr(Controller,'pursue_survivors'))

    def test_lost_vision_is_not_evidence_of_enemy_deaths(self):
        b,g,own,foes,orders,events,effects=self.scene()
        b.update_training_phase(30,None,True)
        b.search_target(own,[],31)
        self.assertFalse(b.training_endgame)

    def test_visible_last_hero_is_pursued_and_unseen_survivor_searches_last_location(self):
        b,g,own,foes,orders,events,effects=self.scene()
        b.update_training_phase(70,2,True)
        target=foes[-1];target.x=1600
        b.search_target(own,[target],70)
        b.pursue_survivors(own,[target],70)
        self.assertTrue(any(o[0]=='attack_move' for o in orders))
        self.assertTrue(all(o[2][0]<=400 for o in orders if o[0]=='attack_move'))
        orders.clear();point=b.search_target(own,[],72)
        self.assertEqual(point,(target.x,target.y))
        b.pursue_survivors(own,[],72,search_point=point)
        self.assertTrue(any(o[0]=='attack_move' for o in orders))

    def test_pursuit_preserves_safety_spells_attacks_and_paths(self):
        for block in ('pulling','cast','guarded','shield','path','attacking','teleport','opening'):
            b,g,own,foes,orders,events,effects=self.scene()
            b.update_training_phase(70,2,True);hero=own[6];enemy=foes[-1];enemy.x=1500
            blocked=set()
            if block=='pulling':b.micro.pulling.add(hero.handle)
            if block=='cast':b.cast_until[hero.handle]=80
            if block=='guarded':b.backline_guards.add(hero.handle)
            if block=='shield':blocked.add(hero.handle)
            if block=='path':g.path_distance=lambda *a:None
            if block=='attacking':enemy.x=300
            if block=='teleport':b.teleport=True
            if block=='opening':b.training_endgame=False
            b.pursue_survivors([hero],[enemy],70,blocked)
            self.assertFalse(orders,block)

    def test_pursuit_follows_walkable_detour_instead_of_a_straight_line_into_trees(self):
        b,g,own,foes,orders,events,effects=self.scene()
        b.update_training_phase(70,2,True)
        hero=own[0];hero.type='uske';target=foes[-1];target.x=200
        g.walk_path=lambda a,z:[a,(0,300),(200,300),z]
        b.pursue_survivors([hero],[target],70)
        self.assertEqual(orders[0],('attack_move',hero.handle,(100.,300.)))


class ApmSummaryTests(unittest.TestCase):
    def test_older_snapshot_does_not_reset_actions_and_average_is_whole_round(self):
        fixture=console_tests.MeterTests();g=fixture.game();meter=ActionMeter(g)
        fixture.now=10;g.lane.commands([N(op=1)]*10)
        data=meter.summary(9.8)
        self.assertEqual(data['accepted_actions'],10)
        self.assertEqual(data['average_apm'],60)
        fixture.now=120;g.lane.commands([N(op=2)]*2)
        data=meter.summary(119.7)
        self.assertEqual(data['accepted_actions'],12)
        self.assertEqual(data['average_apm'],6)
        self.assertEqual(data['apm'],2)
        self.assertEqual(data['apm_game_seconds'],120)
        meter.close()

    def test_last_result_and_average_survive_restart_and_new_session(self):
        with TemporaryDirectory() as d,patch.object(panel,'STATUS',Path(d)/'s.json'),patch.object(panel,'COMMAND',Path(d)/'c.json'):
            selected=dict(matchup='orc',level=4,mode='easy')
            sid=panel.begin(selected)
            result=dict(result='win',selection=selected,average_apm=123.4,apm_basis='accepted_unit_commands_game_time_v2')
            panel.status(sid,phase='finished',last_round=panel.round_summary(result))
            self.assertIn('胜利',panel.previous_text(panel.read_json(panel.STATUS)))
            self.assertIn('123.4',panel.previous_text(panel.read_json(panel.STATUS)))
            panel.begin(dict(matchup='human',level=1,mode='hard'))
            state=panel.read_json(panel.STATUS)
            self.assertIn('兽族 第4关',panel.previous_text(state))
            self.assertIn('123.4',panel.previous_text(state))

    def test_legacy_zero_counter_is_not_presented_as_reliable_average(self):
        state=dict(phase='finished',result='win',accepted_actions=3,game_seconds=135.53,
                   selection=dict(matchup='orc',level=4,mode='easy'))
        self.assertIn('胜利',panel.previous_text(state))
        self.assertIn('未记录',panel.previous_text(state))
        self.assertIsNone(panel.round_summary(dict(result='error'))['average_apm'])


class OpportunisticRodTests(unittest.TestCase):
    def test_dk_uses_rod_despite_four_skeletons_in_shared_battle(self):
        for kind in (Controller,TrainingController):
            b,dk,corpse,live,orders,events,cd=rod_tests.RodTests().make()
            b=kind(b.g,b.log,2)
            b.g.inventory=lambda u:['rnec']
            live.extend(unit('uske',40+i,owner=0,x=100) for i in range(6))
            b.observe_rod_corpses([corpse],100)
            self.assertTrue(b.battle_rod([dk],100))
            self.assertEqual(orders,['rod'])
            self.assertFalse(b.battle_rod([dk],100.2))

    def test_rod_respects_no_corpse_cooldown_rescue_cast_and_exclusive_tasks(self):
        for reason in ('corpse','cooldown','cast','pulling','blocked','shopping','retreat','controlled'):
            b,dk,corpse,live,orders,events,cd=rod_tests.RodTests().make()
            b.g.inventory=lambda u:['rnec'];blocked=set()
            if reason!='corpse':b.observe_rod_corpses([corpse],100)
            if reason=='cooldown':cd[0]=1
            if reason=='cast':b.cast_until[dk.handle]=101.2
            if reason=='pulling':b.micro.pulling.add(dk.handle)
            if reason=='blocked':blocked.add(dk.handle)
            if reason=='shopping':b.shopping.add(dk.handle)
            if reason=='retreat':b.action=Action.RETREAT
            if reason=='controlled':dk.has_detail=True;b.g.buffs=lambda u:['BOhx']
            self.assertFalse(b.battle_rod([dk],100,blocked),reason)
            self.assertFalse(orders)


if __name__=='__main__':unittest.main()
