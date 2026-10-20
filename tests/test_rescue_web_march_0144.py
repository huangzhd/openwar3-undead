import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_strategy_0140 as strategy
import test_combat_focus as focus
import test_march_recovery as march
from undead.targeting import in_weapon_range
from undead.policy import Action

class EmergencyHandoffTests(unittest.TestCase):
    def make(self,code='Ulic'):
        g,b,d,allies,orders,e=strategy.Strategy0140Tests().portal()
        h=unit(code,81,100,90);h.owner=0;d.hp=500
        army=[d,h,*allies];bags={u.handle:([None]*6) for u in army};bags[d.handle][0]='stwp'
        g.inventory=lambda u:bags[u.handle]
        g.current_target=lambda u:h if u is e else None
        given=[];g.give_item=lambda a,slot,z:given.append((a.handle,slot,z.handle)) or True
        events=[];b.log=lambda ev,**kw:events.append(dict(event=ev,**kw))
        return g,b,d,h,army,bags,orders,given,events,e

    def test_handoff_waits_for_both_bags_then_dying_hero_casts(self):
        for code in ('Ulic','Nngs'):
            g,b,d,h,army,bags,orders,given,events,e=self.make(code)
            self.assertTrue(b.emergency_portal(army,100));self.assertFalse(orders)
            self.assertEqual(given[0][2],h.handle)
            b.emergency_portal(army,100.5);self.assertFalse(orders)
            bags[d.handle][0]=None;bags[h.handle][2]='stwp'
            self.assertTrue(b.emergency_portal(army,101));self.assertEqual(orders[0][1],h.handle)
            self.assertEqual(b.teleport['hero'],h.handle)

    def test_recipient_already_has_tp_uses_own_without_handoff(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        bags[d.handle][0]=None;bags[h.handle][0]='stwp'
        b.emergency_portal(army,100)
        self.assertEqual(orders[0][1],h.handle);self.assertFalse(given)

    def test_full_unknown_far_or_protected_recipient_falls_back(self):
        for reason in ('full','unknown','far','blocked_route','cast'):
            g,b,d,h,army,bags,orders,given,events,e=self.make()
            if reason=='full':bags[h.handle]=['rat6']*6
            if reason=='unknown':bags[h.handle]=None
            if reason=='far':h.x=e.x=800
            if reason=='blocked_route':g.path_distance=lambda a,z:None
            if reason=='cast':b.cast_until[h.handle]=102
            b.emergency_portal(army,100)
            self.assertEqual(orders[0][1],d.handle,reason);self.assertFalse(given,reason)

    def test_unconfirmed_transfer_expires_and_donor_casts_without_retry(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        b.emergency_portal(army,100);b.emergency_portal(army,101);self.assertFalse(orders)
        b.emergency_portal(army,102)
        self.assertEqual(orders[0][1],d.handle);self.assertEqual(len(given),1)

    def test_rejected_transfer_falls_back_and_cast_rejection_is_throttled(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        g.give_item=lambda *a:False;g.use_item=lambda u,*a,**kw:orders.append(u.handle) or False
        b.emergency_portal(army,100);b.emergency_portal(army,101)
        self.assertEqual(orders,[d.handle]);self.assertIsNone(b.portal_handoff)

    def test_confirmed_transfer_does_not_force_portal_after_danger_clears(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        b.emergency_portal(army,100);bags[d.handle][0]=None;bags[h.handle][0]='stwp';e.x=3000
        self.assertFalse(b.emergency_portal(army,101));self.assertFalse(orders)

    def test_one_free_slot_can_receive_emergency_tp_before_orb(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make();bags[h.handle]=['rat6']*5+[None]
        b.emergency_portal(army,100);self.assertEqual(given[0][2],h.handle)

    def escape(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        h.x=0;e.x=450;h.hp=125
        b.emergency_portal(army,100) # Not critical yet; record actual trajectory.
        h.x=-100;h.hp=110;b.portal_pulls[h.handle]=(-600,0)
        return g,b,d,h,army,bags,orders,given,events,e

    def test_reachable_escape_with_opening_gap_defers_tp_and_handoff(self):
        g,b,d,h,army,bags,orders,given,events,e=self.escape()
        # 100 units in .5s, 500 remaining would be too slow; shorten the safe route.
        b.portal_pulls[h.handle]=(-350,0);h.hp=119
        self.assertFalse(b.emergency_portal(army,100.5))
        self.assertFalse(orders);self.assertFalse(given)
        self.assertTrue(any(e['event']=='teleport_deferred_escape' for e in events))

    def test_escape_loss_budget_stall_root_or_unsafe_endpoint_do_not_defer(self):
        for reason in ('loss','stall','root','unsafe','unreachable'):
            g,b,d,h,army,bags,orders,given,events,e=self.escape();b.portal_pulls[h.handle]=(-350,0)
            if reason=='loss':h.hp=30
            if reason=='stall':h.x=0
            if reason=='root':g.buffs=lambda u:['BEer'] if u is h else []
            if reason=='unsafe':b.portal_pulls[h.handle]=(-50,0)
            if reason=='unreachable':g.path_distance=lambda a,z:None
            self.assertTrue(b.emergency_portal(army,100.5),reason)
            self.assertTrue(given or orders,reason)

    def test_escape_that_stops_making_progress_reverts_to_rescue(self):
        g,b,d,h,army,bags,orders,given,events,e=self.escape();b.portal_pulls[h.handle]=(-350,0);h.hp=119
        b.emergency_portal(army,100.5);self.assertFalse(given)
        b.emergency_portal(army,103);self.assertTrue(given)

    def test_legal_coil_precedes_handoff_and_waits_boundedly_for_effect(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is d else []
        casts=[];g.cast=lambda u,spell,target:casts.append((u.handle,spell,target.handle)) or True
        g.unit=lambda handle:next((u for u in army if u.handle==handle),None)
        b.emergency_portal(army,100)
        self.assertEqual(casts,[(d.handle,'deathcoil',h.handle)]);self.assertFalse(given);self.assertFalse(orders)
        d.mana=0;g.cooldown=lambda *a:5
        b.emergency_portal(army,100.5);self.assertFalse(given)
        b.emergency_portal(army,101.6);self.assertTrue(given)

    def test_unobserved_coil_cannot_restart_its_wait_forever(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is d else []
        casts=[];g.cast=lambda *a,**kw:casts.append('coil') or True
        g.unit=lambda handle:next((u for u in army if u.handle==handle),None)
        b.emergency_portal(army,100);b.emergency_portal(army,102)
        self.assertEqual(casts,['coil']);self.assertTrue(given)

    def test_disabled_unlearned_or_cooling_coil_does_not_block_rescue(self):
        for reason in ('silenced','unlearned','cooldown'):
            g,b,d,h,army,bags,orders,given,events,e=self.make()
            g.abilities=lambda u:[] if reason=='unlearned' else [dict(code='AUdc',level=1)]
            g.buffs=lambda u:['BNsi'] if reason=='silenced' and u is d else []
            g.cooldown=lambda *a:4 if reason=='cooldown' else 0
            g.cast=lambda *a,**kw:self.fail('Unavailable Coil must not cast')
            b.emergency_portal(army,100);self.assertTrue(given,reason)

    def test_coil_recovery_clears_emergency_without_spending_scroll(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make()
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is d else []
        g.cast=lambda *a,**kw:True;g.unit=lambda handle:next((u for u in army if u.handle==handle),None)
        b.emergency_portal(army,100);h.hp=280
        self.assertFalse(b.emergency_portal(army,101));self.assertFalse(given);self.assertFalse(orders)

    def test_no_mana_prefers_a_viable_pull_to_transferring_tp(self):
        g,b,d,h,army,bags,orders,given,events,e=self.escape();d.mana=0;h.hp=119;b.portal_pulls[h.handle]=(-350,0)
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is d else []
        g.cast=lambda *a,**kw:self.fail('No mana must not cast')
        self.assertFalse(b.emergency_portal(army,100.5));self.assertFalse(given);self.assertFalse(orders)

    def test_naga_cannot_be_healed_with_coil(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make('Nngs')
        g.abilities=lambda u:[dict(code='AUdc',level=1)] if u is d else []
        g.cast=lambda *a,**kw:self.fail('Living Naga is not a Coil healing target')
        b.emergency_portal(army,100);self.assertEqual(given[0][2],h.handle)

    def test_blocked_pull_at_current_position_is_not_an_escape(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make();h.x=0;e.x=490
        b.portal_pulls[h.handle]=(h.x,h.y)
        self.assertTrue(b.emergency_portal(army,100));self.assertTrue(given)

    def test_first_safe_retreat_is_allowed_before_motion_history_exists(self):
        g,b,d,h,army,bags,orders,given,events,e=self.make();h.x=0;e.x=490
        b.portal_pulls[h.handle]=(-160,0)
        self.assertFalse(b.emergency_portal(army,100));self.assertFalse(given)
        # Actual failure to open a gap ends this initial trial.
        self.assertTrue(b.emergency_portal(army,101));self.assertTrue(given)

    def test_retreat_executes_the_safe_escape_point_instead_of_another_route(self):
        g,b,d,h,army,bags,orders,given,events,e=self.escape();h.hp=119;b.portal_pulls[h.handle]=(-350,0)
        moved=[];b.go=lambda units,p,now:moved.extend((u.handle,p) for u in units)
        b.go_raw=lambda units,p,now:moved.extend((u.handle,p) for u in units)
        b.collective_retreat(army,100.5)
        self.assertIn((h.handle,(-350,0)),moved);self.assertNotIn((h.handle,(-5000,0)),moved)
        self.assertFalse(given);self.assertFalse(orders)

class WebFocusTests(unittest.TestCase):
    def make(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=focus.CombatFocusTests().make()
        chim=unit('echm',90,100,900);chim.owner=1;chim.has_detail=True;foes.append(chim)
        active=['Bweb'];b.g.buffs=lambda u:active if u is chim else []
        return b,f,d,s,h,e,own,foes,commands,targets,events,chim,active

    def test_webbed_air_overrides_hero_and_cheaper_ground_for_melee_and_fiend(self):
        b,f,d,s,h,e,own,foes,commands,targets,events,chim,active=self.make()
        b.fight(own,foes,10)
        self.assertIs(targets[f.handle],chim);self.assertIs(targets[d.handle],chim)
        self.assertTrue(in_weapon_range(b.g,d,chim))
        self.assertTrue(any(e['priority']==-2 for e in events if e['event']=='combat_focus'))

    def test_each_unit_prefers_a_webbed_air_target_within_its_own_range(self):
        b,f,d,s,h,e,own,foes,commands,targets,events,chim,active=self.make()
        chim.x=400;chim.hp=100
        other=unit('echm',91,100,900);other.owner=1;other.has_detail=True;foes.append(other)
        b.g.buffs=lambda u:['Bweb'] if u in (chim,other) else []
        b.fight(own,foes,10)
        self.assertIs(targets[f.handle],chim);self.assertIs(targets[d.handle],other)

    def test_expired_web_restores_hero_priority_and_melee_cannot_attack_air(self):
        b,f,d,s,h,e,own,foes,commands,targets,events,chim,active=self.make()
        b.fight(own,foes,10);active.clear();b.fight(own,foes,12)
        self.assertIs(targets[f.handle],h);self.assertIs(targets[d.handle],e)
        self.assertFalse(in_weapon_range(b.g,d,chim))

    def test_hidden_buff_or_unreachable_air_does_not_override(self):
        for reason in ('no_detail','out_of_range'):
            b,f,d,s,h,e,own,foes,commands,targets,events,chim,active=self.make()
            if reason=='no_detail':chim.has_detail=False
            else:chim.x=600
            b.fight(own,foes,10);self.assertIs(targets[f.handle],h)

    def test_ground_unit_with_web_code_does_not_take_air_priority(self):
        b,f,d,s,h,e,own,foes,commands,targets,events,chim,active=self.make();chim.type='ogru'
        b.fight(own,foes,10);self.assertIs(targets[f.handle],h)

class RouteRejoinTests(unittest.TestCase):
    def test_returning_unit_does_not_rebuild_leaders_path_behind_them(self):
        bot,orders=march.MarchRecoveryTests().controller()
        leader=unit('Ulic',1,1600);fiend=unit('ucry',2,1650);dk=unit('Udea',3,1400)
        f=bot.formation;f.route=[(0,0),(1000,0),(3000,0)];f.objective=(3000,0);f.last_progress=0
        f.cursors={leader.handle:2,fiend.handle:2,dk.handle:0};f.catching_up={dk.handle}
        # Rebuilding from the anchor would introduce this unnecessary backwards turn.
        bot.g.walk_path=lambda a,b:[(1200,0),b]
        bot.go([leader,fiend,dk],(3000,0),2,True)
        self.assertTrue(all(point[0]>=u.x for u,point,_ in orders))
        self.assertEqual(f.route,[(0,0),(1000,0),(3000,0)])

    def test_changed_destination_recomputes_dk_lead_without_turning_main_back(self):
        bot,orders=march.MarchRecoveryTests().controller();d=unit('Udea',1,0);a=unit('ucry',2,1000);z=unit('ucry',3,1050)
        f=bot.formation;f.catching_up={d.handle};f.route=[(6000,0)];f.objective=(6000,0)
        bot.go([d,a,z],(-6000,0),2,True)
        # Changing direction makes DK the forward outlier. He now returns
        # to the moving main body; the fiends follow the new destination.
        self.assertIn(d.handle,f.catching_up)
        self.assertTrue(all(point==(-6000,0) and attack for u,point,attack in orders if u is not d))
        self.assertTrue(any(u is d and point==(1000,0) and not attack for u,point,attack in orders))

if __name__=='__main__':unittest.main()
