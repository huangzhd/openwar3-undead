import unittest
from unittest.mock import Mock
from test_baseline import unit
import test_tc_pressure_01186 as pressure_tests
import test_equipment as equipment_tests
from undead.controller import Controller
from training import TrainingController
from undead.destroyer import dispel_plan


class BansheeLinkDustTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=pressure_tests.TcFirstTests().scene(kind)
        g.current_target=lambda u:None
        banshees=[unit('uban',60+i,owner=0,x=-200) for i in range(6)]
        for u in banshees:
            u.hp=u.hp_max=325;u.mana=200;u.mana_max=400;u.has_detail=True
        own.extend(banshees)
        previous=g.abilities
        g.abilities=lambda u:[dict(code=c,level=1) for c in ('Acrs','Aams')] if u.type=='uban' else previous(u)
        g.use_item=lambda u,slot,**kw:orders.append(('use',u.handle,slot,kw)) or True
        b.hero_pressure.prefer_key_heroes=True
        return b,g,own,foes,orders,events,effects,dk,tc,banshees

    def test_shields_prioritize_all_heroes_deduplicate_then_cover_all_fiends(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            for e in foes:e.x=2000
            targets=[u for u in own if u.is_hero or u.type=='ucry']
            for now in (1,2,3):
                b.banshee_support.tick(b,own,foes,now,True)
                shells=[o for o in orders if o[0]=='cast' and o[2]=='antimagicshell']
                for o in shells:effects[o[3]['target'].handle]=['Bams']
            self.assertEqual(len(shells),len(targets))
            self.assertEqual(len({o[3]['target'].handle for o in shells}),len(targets))
            self.assertTrue(all(o[3]['target'].is_hero for o in shells[:3]))
            self.assertTrue(any(e=='banshee_shell_observed' for e,_ in events))

    def test_accepted_shell_without_buff_is_not_confirmed_and_stops_after_three(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        own[:]=[dk,banshees[0]]
        for now in range(1,21):b.banshee_support.tick(b,own,[],now,True)
        self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2]=='antimagicshell']),3)
        self.assertFalse(any(e=='banshee_shell_observed' for e,_ in events))

    def test_shell_requires_skill_mana_cooldown_detail_and_safe_caster(self):
        for why in ('skill','mana','cooldown','unknown_cd','silence','blocked','casting','target_detail','retreat'):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene();u=banshees[0];own[:]=[dk,u];blocked=set()
            if why=='skill':g.abilities=lambda u:[]
            if why=='mana':u.mana=49
            if why=='cooldown':g.cooldown=lambda *a:5
            if why=='unknown_cd':g.cooldown=lambda *a:None
            if why=='silence':effects[u.handle]=['BNsi']
            if why=='blocked':blocked.add(u.handle)
            if why=='casting':b.cast_until[u.handle]=20
            if why=='target_detail':dk.has_detail=False
            if why=='retreat':b.action=type(b.action).RETREAT
            b.banshee_support.tick(b,own,[],10,True,blocked)
            self.assertFalse(any(o[0]=='cast' and o[2]=='antimagicshell' for o in orders),why)

    def test_combat_enables_curse_once_without_repeated_spells_or_formation_moves(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            for now in (10,11,13):b.banshee_support.tick(b,own,foes,now,False)
            self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2]=='curseon']),6)
            self.assertFalse(any(o[0]=='move' or o[0]=='cast' and o[2]=='antimagicshell' for o in orders))

    def test_banshees_and_statues_start_behind_ranged_heroes_only_before_contact(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            for e in foes:e.x=2000
            b.prepare_battle(1,own,(2000,0),foes=foes)
            for u in own:
                if u.type in {'uban','uobs'}:
                    self.assertLess(b.prep_points[u.handle][0],b.prep_points[own[6].handle][0]-80)
            for e in foes:e.x=400
            b.battle_actions(own,foes,10,{})
            orders.clear();b.prepare_battle(11,own,(2000,0),foes=foes)
            self.assertFalse(orders)
            for e in foes:e.x=1500
            orders.clear();b.prepare_battle(12,own,(2000,0),foes=foes)
            self.assertFalse(orders) # No reset merely because the enemy backed off.

    def test_fight_never_calls_fan_or_cancels_existing_in_range_fire(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            b.battle_formation.step=Mock(side_effect=AssertionError('combat fan must never run'))
            for u in own:u.mana=0
            g.current_target=lambda u:tc if u.owner==0 else None
            b.engage_battle(own,foes,10)
            self.assertFalse(any(o[0]=='move' for o in orders))
            self.assertFalse(b.battle_formation.step.called)
            self.assertFalse(any(o[1] in {u.handle for u in banshees} for o in orders))

    def test_banshees_do_not_join_arena_chase(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(TrainingController)
        b.training_endgame=True
        for e in foes:e.x=1800
        b.pursue_survivors(banshees,foes,10)
        self.assertFalse(orders)

    def test_wounded_banshee_pulls_even_when_dk_has_mana_then_rejoins_curse_owner(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            u=banshees[0];u.hp=80;u.x=0
            pulls=b.micro.plan(own,foes,10,lambda e:u.handle,g.path_distance,
                               lambda *p:True,(-2000,0),lambda _:600,coil_ready=True,aggressive_battle=True)
            self.assertIn(u.handle,pulls)
            u.x=-1600;g.current_target=lambda _:None
            b.rejoin_battle_units(own,foes,14,pulls);b.rejoin_battle_units(own,foes,17,pulls)
            self.assertGreater(pulls[u.handle][0],-1300)
            u.x,u.y=pulls[u.handle]
            orders.clear();b.rejoin_battle_units(own,foes,18,pulls)
            self.assertNotIn(u.handle,pulls)
            self.assertFalse(any(o[1]==u.handle for o in orders))
            b.banshee_support.tick(b,own,foes,19,False,set(pulls))
            self.assertTrue(any(o[:3]==('cast',u.handle,'curseon') for o in orders))

    def test_curse_rejected_toggle_has_finite_attempts(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        def reject(u,spell,**kw):orders.append(('cast',u.handle,spell,kw));return False
        g.cast=reject
        for t in range(10,30):b.banshee_support.tick(b,own,foes,t,False)
        self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2]=='curseon']),18)

    def test_support_follow_rejects_paths_crossing_enemy_fire(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene();u=banshees[0]
        u.x=-1500
        g.walk_path=lambda a,p:[a,(400,0),p]
        b.banshee_support.tick(b,own,foes,10,False)
        self.assertFalse(any(o[0]=='move' and o[1]==u.handle for o in orders))

    def test_destroyer_attack_never_bypasses_visible_aa_safety(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        d=own[8];d.x=0;tc.type='ogru'
        b.attack_destroyers(own,foes,10)
        self.assertFalse(any(o[0]=='attack' and o[1]==d.handle for o in orders))

    def test_link_cast_confirms_before_escape_then_repeats_after_cooldown(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            d=own[8];d.x=0;foes[:]=foes[:2]
            for e in foes:effects[e.handle]=['Bspl']
            own[:]=[own[0],d]
            pulls={};b.battle_actions(own,foes,10,pulls)
            self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2]=='devourmagic']),1)
            b.go_raw([d],pulls[d.handle],10)
            self.assertFalse(any(o[0]=='move' for o in orders))
            g.cooldown=lambda u,c:6.8 if c=='Advm' else 0
            b.battle_actions(own,foes,10.2,pulls);b.go_raw([d],pulls[d.handle],10.2)
            self.assertTrue(any(o[0]=='move' and o[1]==d.handle for o in orders))
            d.x,d.y=pulls[d.handle];g.cooldown=lambda *a:0
            orders.clear();b.battle_actions(own,foes,18,{})
            self.assertTrue(any(o[0]=='cast' and o[2]=='devourmagic' for o in orders))
            self.assertFalse(any(o[0]=='attack' and o[1]==d.handle for o in orders))

    def test_link_cluster_priority_and_shared_coverage_avoid_duplicate_dispels(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        for e in foes[:2]:effects[e.handle]=['Bspl']
        effects[tc.handle]=['Broa'];tc.x=-700;foes[:]=foes[:2]+[tc]
        d=own[8];d.x=0
        other=unit('ubsp',81,owner=0);other.hp=other.hp_max=900;other.mana=0;other.has_detail=True;own.append(other)
        b.destroyer.tick(b,own,foes,10)
        first=next(data for e,data in events if e=='destroyer_dispel_attempt')
        self.assertEqual(first['reason'],'spirit_link')
        self.assertEqual(first['covered_count'],2)
        covered=[set(data['covered_handles']) for e,data in events if e=='destroyer_dispel_attempt']
        if len(covered)>1:self.assertFalse(covered[0]&covered[1])

    def test_safe_destroyer_does_not_move_for_ideal_backline_or_chase_attacks(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        d=own[8];d.x=-200;foes[:]=[tc];tc.type='ogru';tc.x=200
        pulls={};b.rear_destroyers(own,foes,10,pulls,None);b.attack_destroyers(own,foes,10,set(pulls))
        self.assertFalse(pulls)
        self.assertTrue(any(o[0]=='attack' and o[1]==d.handle for o in orders))
        orders.clear();tc.x=1000;b.attack_destroyers(own,foes,12)
        self.assertFalse(orders)

    def test_dust_uses_last_visible_position_not_hidden_coordinates_and_is_bounded(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            tc.type='Obla';tc.x=300
            g.inventory=lambda u:['dust'] if u is dk else []
            b.battle_detection.tick(b,own,[tc],10)
            self.assertFalse(any(o[0]=='use' for o in orders))
            tc.visible_to=lambda _:False;tc.x=99999
            b.battle_detection.tick(b,own,[tc],11)
            b.battle_detection.tick(b,own,[tc],12)
            self.assertEqual(len([o for o in orders if o[0]=='use']),1)
            event=next(data for e,data in events if e=='battle_dust_attempt')
            self.assertEqual(event['last_visible_point'],(300,0))
            self.assertEqual(event['reason'],'recent_visibility_loss')

    def test_dust_skips_unknown_hidden_dead_stale_distant_or_protected_cases(self):
        for why in ('never_seen','stale','far','dead','blocked','no_item','cooldown','unknown_cd','hex','casting','detected'):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
            tc.type='Obla';tc.x=300;g.inventory=lambda u:['dust'] if u is dk else []
            if why=='far':tc.x=2000
            if why!='never_seen':b.battle_detection.tick(b,own,[tc],10)
            if why=='dead':
                tc.hp=0;tc.alive=False;b.battle_detection.tick(b,own,[tc],10.5)
            if why=='no_item':g.inventory=lambda u:[]
            if why=='cooldown':g.cooldown=lambda *a:5
            if why=='unknown_cd':g.cooldown=lambda *a:None
            if why=='hex':effects[dk.handle]=['BOhx']
            if why=='casting':b.cast_until[dk.handle]=30
            visible=[]
            if why=='detected':effects[tc.handle]=['BOwk','Bdet'];visible=[tc]
            b.battle_detection.tick(b,own,visible,15 if why=='stale' else 11,{dk.handle} if why=='blocked' else ())
            self.assertFalse(any(o[0]=='use' for o in orders),why)

    def test_visible_windwalk_detection_requires_actual_bdet_for_reveal_evidence(self):
        b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene()
        tc.type='Obla';effects[tc.handle]=['BOwk'];g.inventory=lambda u:['dust'] if u is dk else []
        b.battle_detection.tick(b,own,[tc],10)
        effects[tc.handle]=['BOwk','Bdet'];b.battle_detection.tick(b,own,[tc],10.5)
        self.assertTrue(any(e=='battle_dust_observed' and d['revealed'] for e,d in events))

    def test_dust_does_not_take_dk_away_from_immediate_hero_healing(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,banshees=self.scene(kind)
            tc.type='Obla';g.inventory=lambda u:['dust'] if u is dk else []
            b.battle_detection.tick(b,own,foes,10)
            foes.remove(tc);own[6].hp=100
            b.battle_actions(own,foes,11,{})
            self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target'] is own[6] for o in orders))
            self.assertFalse(any(o[0]=='use' for o in orders))

    def test_prebattle_training_transfers_dk_gloves_and_circlet_with_real_inventory_confirmation(self):
        fixture=equipment_tests.EquipmentTests();g,eq,events=fixture.setup_game()
        g.inv[g.dk.handle]=['dust','gcel','cnob',None,None,None]
        g.inv[g.lich.handle]=['ocor',None,None,None,None,None]
        b=TrainingController(None,lambda *a,**kw:None,2);b.g=g;b.equipment=eq
        g.my_units=lambda:g.heroes;g.enemies=lambda:[]
        b.collect_start_potion=Mock(return_value=set());b.prepare_battle=Mock()
        for now in (1,4,7):
            b.prepare(now)
            if g.transfers and eq.pending:fixture.observed_transfer(g)
        self.assertIn('gcel',g.inv[g.lich.handle]);self.assertIn('cnob',g.inv[g.lich.handle])
        self.assertIn('dust',g.inv[g.dk.handle])
        self.assertTrue(any(e=='equipment_transfer_confirmed' for e,_ in events))

    def test_combat_does_not_transfer_equipment(self):
        fixture=equipment_tests.EquipmentTests();g,eq,events=fixture.setup_game()
        g.inv[g.dk.handle]=['gcel','cnob',None,None,None,None]
        enemy=unit('Obla',90,x=g.dk.x+100)
        self.assertFalse(eq.tick(g,g.heroes,[enemy],10,{}))
        self.assertFalse(g.transfers)


if __name__=='__main__':unittest.main()
