import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace

import training
import training_control as control
from training import TrainingController
from undead.controller import Controller, ground_attack_range
from undead.version import DISPLAY_NAME
from undead.consumables import Consumables
from test_baseline import unit
import test_shared_battle_01181 as shared
from test_consumables import Game as ItemGame


class LichSafetyTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene(kind)
        lich=next(u for u in own if u.type=='Ulic');lich.hp=270
        dk=unit('Udea',90,owner=0,x=-200);dk.mana=74
        own.append(dk)
        foes[:]=[unit('ogru',91,x=120)]
        return b,g,own,foes,orders,events,effects,lich,dk

    def test_half_health_no_coil_mana_retreats_before_damage_and_in_both_modes(self):
        results=[]
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,lich,dk=self.scene(kind)
            pulls={};b.rear_backline(own,foes,10,pulls)
            self.assertIn(lich.handle,pulls)
            self.assertGreaterEqual(g.dist(pulls[lich.handle],foes[0])-ground_attack_range(foes[0].type),140)
            results.append(pulls)
        self.assertEqual(*results)
        self.assertIs(Controller.rear_backline,TrainingController.rear_backline)

    def test_healthy_or_mana_covered_lich_keeps_normal_battle_behavior(self):
        for hp,mana in ((301,74),(270,75),(600,0)):
            b,g,own,foes,orders,events,effects,lich,dk=self.scene()
            lich.hp=hp;dk.mana=mana
            pulls={};b.rear_backline(own,foes,10,pulls)
            self.assertNotIn(lich.handle,pulls)

    def test_known_invulnerability_leaves_before_expiry_even_with_dk_mana(self):
        b,g,own,foes,orders,events,effects,lich,dk=self.scene()
        dk.mana=200;effects[lich.handle]=['Bvul']
        b.consumables.invulnerable_until[lich.handle]=17
        pulls={};b.rear_backline(own,foes,10,pulls)
        self.assertFalse(pulls)
        b.rear_backline(own,foes,14,pulls)
        self.assertIn(lich.handle,pulls)
        self.assertGreater(17-14,0)

    def test_unknown_invulnerability_age_never_assumes_fresh_protection(self):
        b,g,own,foes,orders,events,effects,lich,dk=self.scene()
        dk.mana=200;effects[lich.handle]=['Bvul']
        pulls={};b.rear_backline(own,foes,10,pulls)
        self.assertIn(lich.handle,pulls)

    def test_retreat_avoids_every_weapon_and_blocked_paths(self):
        b,g,own,foes,orders,events,effects,lich,dk=self.scene()
        foes.append(unit('otbk',92,x=-200))
        pulls={};b.rear_backline(own,foes,10,pulls)
        for e in foes:
            self.assertGreaterEqual(g.dist(pulls[lich.handle],e)-ground_attack_range(e.type),140)
        g.path_distance=lambda *a:None
        pulls={};b.rear_backline(own,foes,11,pulls)
        self.assertEqual(pulls[lich.handle],(lich.x,lich.y))

    def test_safe_lich_keeps_firing_but_does_not_chase_or_accept_generic_move(self):
        b,g,own,foes,orders,events,effects,lich,dk=self.scene()
        pulls={};b.rear_backline(own,foes,10,pulls)
        lich.x,lich.y=pulls[lich.handle]
        b.rear_backline(own,foes,11,pulls)
        self.assertTrue(any(o[0]=='attack' and o[1]==lich.handle for o in orders))
        orders.clear();b.go_raw([lich],pulls[lich.handle],11)
        self.assertFalse(orders)
        foes[0].x=1600
        b.rear_backline(own,foes,12,pulls)
        self.assertTrue(any(o[0]=='hold' and o[1]==lich.handle for o in orders))
        self.assertFalse(any(o[0] in {'attack','move','attack_move'} for o in orders))

    def test_exclusive_tasks_and_cast_lock_remain_protected(self):
        for exclusive in ('blocked','shopping','teleport','cast'):
            b,g,own,foes,orders,events,effects,lich,dk=self.scene()
            blocked=set()
            if exclusive=='blocked':blocked.add(lich.handle)
            if exclusive=='shopping':b.shopping.add(lich.handle)
            if exclusive=='teleport':b.teleport=True
            if exclusive=='cast':b.cast_until[lich.handle]=12
            pulls={};b.rear_backline(own,foes,10,pulls,blocked)
            if exclusive=='cast':b.go_raw([lich],pulls[lich.handle],10)
            else:self.assertNotIn(lich.handle,pulls)
            self.assertFalse(orders)

    def test_guard_releases_after_health_recovers_or_threats_disappear(self):
        b,g,own,foes,orders,events,effects,lich,dk=self.scene()
        b.rear_backline(own,foes,10,{})
        lich.hp=400
        b.rear_backline(own,foes,11,{})
        self.assertNotIn(lich.handle,b.backline_guards)
        lich.hp=100;b.rear_backline(own,foes,12,{})
        b.rear_backline(own,[],13,{})
        self.assertNotIn(lich.handle,b.backline_guards)

    def test_invulnerability_timer_requires_observed_buff_and_does_not_slide(self):
        for code,duration in (('pnvl',7),('pnvu',15)):
            g=ItemGame();c=Consumables(lambda *a,**kw:None)
            lich=g.heroes[1];g.heroes[0].mana=0
            g.bags[lich.handle][0]=code;foes=[unit('ogru',99,x=100)]
            c.tick(g,g.army,foes,10,{})
            self.assertNotIn(lich.handle,c.invulnerable_until)
            g.bs[lich.handle]=['Bvul'];c.observe(g,10.2)
            self.assertEqual(c.invulnerable_until[lich.handle],10+duration)
            c.observe(g,12)
            self.assertEqual(c.invulnerable_until[lich.handle],10+duration)
            g.bs[lich.handle]=[];c.observe(g,13)
            self.assertNotIn(lich.handle,c.invulnerable_until)


class PanelTests(unittest.TestCase):
    def test_runner_changes_race_only_after_cleanup_and_resets_round_metrics(self):
        for cleaned in (True,False):
            with TemporaryDirectory() as folder, patch.object(control,'STATUS',Path(folder)/'s.json'), patch.object(control,'COMMAND',Path(folder)/'c.json'), patch.object(control,'launch',return_value=None):
                calls=[]
                def run(args,sid,attempt):
                    state=control.read_json(control.STATUS)
                    self.assertIsNone(state['apm'])
                    calls.append((args.matchup,args.level,args.mode,attempt))
                    if attempt==1:
                        control.status(sid,apm=999)
                        return dict(result='selection_requested',cleanup_confirmed=cleaned,
                                    next_selection=dict(matchup='human',level=7,mode='hard'),artifact_dir=folder)
                    return dict(result='win',cleanup_confirmed=True,artifact_dir=folder)
                args=SimpleNamespace(probe=False,matchup='orc',level=4,mode='easy',speed=100,seconds=180,wall_seconds=240)
                with patch.object(training,'run',side_effect=run):training.play(args)
                self.assertEqual(len(calls),2 if cleaned else 1)
                if cleaned:self.assertEqual(calls[-1],('human',7,'hard',2))

    def test_cross_race_selection_is_validated_and_session_scoped(self):
        with TemporaryDirectory() as folder, patch.object(control,'STATUS',Path(folder)/'s.json'), patch.object(control,'COMMAND',Path(folder)/'c.json'):
            sid=control.begin(dict(matchup='orc',level=4,mode='easy'))
            control.status(sid,phase='running')
            for race in ('human','orc','undead','nightelf'):
                selection=dict(matchup=race,level=10,mode='hard')
                self.assertTrue(control.post(sid,'switch',selection))
                self.assertEqual(control.take(sid)['selection'],selection)
            self.assertFalse(control.post('wrong','switch',selection))
            self.assertFalse(control.post(sid,'switch',dict(matchup='random',level=1,mode='easy')))
            control.atomic_json(control.COMMAND,dict(session_id=sid,action='switch',selection={'matchup':'bad'}))
            self.assertIsNone(control.take(sid))

    def test_metrics_use_running_version_and_hide_stale_or_finished_apm(self):
        state=dict(phase='running',bot_name='dayuan V1.74',apm=123,metrics_updated=100)
        self.assertEqual(control.metrics_text(state,102),'dayuan V1.74   ·   APM 123')
        self.assertIn('APM —',control.metrics_text(state,106))
        state['phase']='finished'
        self.assertEqual(control.metrics_text(state,102),DISPLAY_NAME+'   ·   APM —')
        self.assertIn('APM —',control.metrics_text({},102))

    def test_restart_resets_metrics(self):
        with TemporaryDirectory() as folder, patch.object(control,'STATUS',Path(folder)/'s.json'), patch.object(control,'COMMAND',Path(folder)/'c.json'):
            selection=dict(matchup='human',level=1,mode='easy')
            old=control.begin(selection);control.status(old,phase='running',apm=999)
            new=control.begin(selection)
            self.assertNotEqual(old,new)
            self.assertIsNone(control.read_json(control.STATUS)['apm'])
            self.assertEqual(control.read_json(control.STATUS)['bot_name'],DISPLAY_NAME)


if __name__=='__main__':unittest.main()
