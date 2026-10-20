import json
import unittest
from pathlib import Path
import test_combat_focus as focus
import test_th_route_01152 as th
from test_micro_loot import unit,dist
import test_march_recovery as march
from undead.policy import Action


class EfficientMarchTests(unittest.TestCase):
    def test_march_and_arrival_leave_nearby_attacks_running(self):
        for attack in (True,False):
            b,orders=march.MarchRecoveryTests().controller()
            army=[unit('Udea',1,0),unit('ucry',2,20)]
            foe=unit('ogru',9,60);foe.owner=1
            b.g.me=lambda:0;b.g.current_target=lambda u:foe
            holds=[];b.g.hold=lambda u:holds.append(u.handle)
            for now in (0,2,6):
                b.go(army,(0,0),now,attack=attack)
            self.assertFalse(holds)
            self.assertFalse(orders)

    def test_arrival_without_target_does_not_issue_hold(self):
        b,orders=march.MarchRecoveryTests().controller()
        holds=[];b.g.hold=lambda u:holds.append(u.handle)
        army=[unit('Udea',1,0),unit('ucry',2,20)]
        b.go(army,(0,0),0,attack=True)
        self.assertFalse(holds)
        self.assertTrue(all(attack for _,_,attack in orders))

    def test_severe_separation_and_retreat_override_local_attack(self):
        for retreat in (False,True):
            b,orders=march.MarchRecoveryTests().controller()
            dk=unit('Udea',1,1200);army=[dk,unit('ucry',2,0),unit('ucry',3,20)]
            foe=unit('ogru',9,1240);foe.owner=1
            b.g.me=lambda:0;b.g.current_target=lambda u:foe if u is dk else None
            if retreat:b.action=Action.RETREAT
            b.go(army,(-6000,0) if retreat else (6000,0),0,attack=not retreat)
            self.assertTrue(any(u is dk and not attack for u,_,attack in orders))
            if retreat:self.assertTrue(all(p==(-6000,0) for _,p,_ in orders))
            else:self.assertTrue(all(p==(6000,0) and attack for u,p,attack in orders if u is not dk))

    def test_moderately_spread_fiend_stays_in_attack_army(self):
        b,orders=march.MarchRecoveryTests().controller()
        army=[unit('Udea',1,0),unit('Ulic',2,20),unit('ucry',3,800)]
        self.assertEqual(b.regroup_isolated_fiends(army,1),army)
        self.assertFalse(orders)

    def test_leading_dk_returns_by_move_while_main_attacks_forward(self):
        b,orders=march.MarchRecoveryTests().controller()
        dk=unit('Udea',1,1000)
        army=[dk,unit('Ulic',2,0),unit('ucry',3,30)]
        b.go(army,(6000,0),0,attack=True)
        self.assertEqual(orders[0][1:],((30,0),False))
        self.assertTrue(all(p==(6000,0) and attack for _,p,attack in orders[1:]))
        dk.x=400;orders.clear()
        b.go(army,(6000,0),2,attack=True)
        self.assertTrue(all(p==(6000,0) and attack for _,p,attack in orders))

    def test_moderate_spread_and_lagging_dk_do_not_pull_lich_back(self):
        b,orders=march.MarchRecoveryTests().controller()
        army=[unit('Udea',1,0),unit('Ulic',2,650),unit('ucry',3,600)]
        b.go(army,(6000,0),0,attack=True)
        self.assertTrue(all(p==(6000,0) and attack for _,p,attack in orders))

    def test_forest_split_preserves_main_route_over_multiple_ticks(self):
        b,orders=march.MarchRecoveryTests().controller()
        dk=unit('Udea',1,200);main=[unit('Ulic',2,0),unit('ucry',3,30)]
        b.g.path_distance=lambda a,z:2000 if (a[0] if isinstance(a,tuple) else a.x)==dk.x else dist(a,z)
        for now in (0,2,4,8,16,32):
            orders.clear();b.go([dk,*main],(6000,0),now,attack=True)
            self.assertFalse(orders[0][2])
            self.assertTrue(all(p==(6000,0) and attack for _,p,attack in orders[1:]))
            self.assertEqual(b.formation.stage,'advance')
            for u in main:u.x+=150


class LastCreepTests(unittest.TestCase):
    def scene(self):
        b,*rest=focus.CombatFocusTests().make()
        own=rest[5];orders=rest[7];targets=rest[8]
        f=json.loads((Path(__file__).parent/'fixtures/th_203239_last_creep.json').read_text(encoding='utf-8'))['frame']
        own.clear()
        for r in f['army']:
            u=unit(r['type'],r['handle'][0],r['x'],r['hp'])
            u.handle=tuple(r['handle']);u.y=r['y'];u.hp_max=r['hp_max'];u.owner=0;u.mana=0
            own.append(u)
        r=f['enemies'][0];e=unit(r['type'],r['handle'][0],r['x'],r['hp'])
        e.handle=tuple(r['handle']);e.y=r['y'];e.owner=12
        _,_,_,c=th.THRouteTests().scene()
        b.creeping.catalog=c.catalog;b.creeping.map_alias='TH'
        b.creeping.active=next(p for p in c.catalog if p['id']=='th-10')
        b.creeping.observe_drop_carriers(b.g,[e])
        b.g.creeps=lambda:[e];b.g.path_distance=dist;b.g.walk_path=lambda a,z:[z]
        b.action=Action.CREEP
        # Prior skeleton command exists in the sample's fight; don't initiate a new pull.
        targets[own[-1].handle]=e;targets[e.handle]=own[-1]
        return b,own,e,orders,targets

    def test_actual_last_creep_positions_order_dk_and_both_fiends_to_finish(self):
        b,own,e,orders,targets=self.scene()
        self.assertFalse(b.creeping.carries_drop(e))
        self.assertGreater(dist(own[1],e),650)
        self.assertTrue(b.fight(own,[e],327.675))
        self.assertTrue(all(targets.get(u.handle) is e for u in own))
        self.assertTrue(all(('attack',u.handle,e.handle) in orders for u in own[:3]))

    def test_other_camp_and_far_target_do_not_extend_engagement(self):
        for case in ('other_camp','far'):
            b,own,e,orders,targets=self.scene()
            if case=='other_camp':b.creeping.drop_camps[e.handle]=-1
            else:e.x+=1000
            self.assertFalse(b.fight(own,[e],327.675))
            self.assertFalse(orders)

    def test_out_of_combat_range_keeps_creep_march_moving(self):
        b,own,e,orders,targets=self.scene()
        e.x+=300
        b.home=unit('unpl',50,-3904);b.home.y=2880
        b.creeping.choose=lambda *args:((e.x,e.y),[e])
        b.creeping.cleared={'th-8','th-2'}
        b.ni_rod_stop.tick=lambda *args:False
        b.ch_resummon.tick=lambda *args:False
        moves=[];b.go=lambda army,p,now,attack=False:moves.append(p)
        b.go_raw=lambda *args:None
        b.creep(own,(own[0].x,own[0].y),327.675)
        self.assertEqual(moves,[(e.x,e.y)])


if __name__=='__main__':unittest.main()
