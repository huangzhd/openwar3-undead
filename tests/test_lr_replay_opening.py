import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_foundation_owner_01124 as foundation
import test_critter_search as critters
import test_scout_opening as scout_fixture
from undead.replay_opening import LR_NE_BUILDINGS,LR_NE_APPROACH,REFERENCE_SHA256,fixed_slot
from undead.replay_opening import LR_SW_BUILDINGS,LR_SW_APPROACH,SW_REFERENCE_SHA256


class LRReferenceTests(unittest.TestCase):
    def scene(self,southwest=False):
        l,g,h,w,bs,ws,orders,events,order=foundation.FoundationTests().scene()
        h.x,h.y=3840,3328;l.map_alias='LR'
        if southwest:h.x,h.y=-3904,-3968
        g.can_afford=lambda code:True
        g.build=lambda worker,code,x,y:orders.append((code,x,y)) or True
        return l,g,h,w,bs,orders,events,order

    def test_all_five_commands_match_recording_and_keep_fixed_template(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/lr_ne_reference_opening.json').read_text(encoding='utf-8'))
        self.assertEqual(fixture['replay_sha256'],REFERENCE_SHA256)
        self.assertEqual({r['code']:tuple(r['point']) for r in fixture['build_orders']},LR_NE_BUILDINGS)
        l,g,h,w,bs,orders,events,order=self.scene()
        for i,(code,point) in enumerate(LR_NE_BUILDINGS.items()):
            now=i*20+5
            self.assertEqual(l.build(g,w,code,h,now),point)
            self.assertEqual(orders[-1],(code,*point))
            self.assertEqual(l.build(g,w,code,h,now+1),point)
            self.assertEqual(len(orders),i+1)
            foundation=unit(code,100+i,point[0]);foundation.y=point[1];bs.append(foundation)
            l.observe(g,now+2)
            self.assertNotIn(code,l.pending)

    def test_rejected_command_and_lost_order_retry_same_place_after_three_seconds(self):
        l,g,h,w,bs,orders,events,order=self.scene();point=LR_NE_BUILDINGS['ugrv']
        g.build=lambda worker,code,x,y:orders.append((code,x,y)) and False
        self.assertIsNone(l.build(g,w,'ugrv',h,80))
        self.assertIsNone(l.build(g,w,'ugrv',h,81));self.assertEqual(len(orders),1)
        g.build=lambda worker,code,x,y:orders.append((code,x,y)) or True
        self.assertEqual(l.build(g,w,'ugrv',h,83),point)
        l.observe(g,86);self.assertNotIn('ugrv',l.pending)
        self.assertEqual(len(orders),2)
        self.assertEqual(l.build(g,w,'ugrv',h,89),point)
        self.assertEqual(set(orders),{('ugrv',*point)})

    def test_southwest_has_its_own_five_locations_and_discards_early_altar_attempts(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/lr_sw_reference_opening.json').read_text(encoding='utf-8'))
        self.assertEqual(fixture['replay_sha256'],SW_REFERENCE_SHA256)
        self.assertEqual({r['code']:tuple(r['point']) for r in fixture['build_orders']},LR_SW_BUILDINGS)
        l,g,h,w,bs,orders,events,order=self.scene(True)
        for i,(code,point) in enumerate(LR_SW_BUILDINGS.items()):
            self.assertEqual(l.build(g,w,code,h,i*20+5),point)
            foundation=unit(code,100+i,point[0]);foundation.y=point[1];bs.append(foundation)
            l.observe(g,i*20+7)
        self.assertNotIn(('uaod',-3552,-3296),orders)
        self.assertEqual(len(orders),5)

    def test_occupied_or_unbuildable_slot_never_silently_relocates(self):
        for obstacle in ('building','terrain','tree'):
            l,g,h,w,bs,orders,events,order=self.scene();x,y=LR_NE_BUILDINGS['utom']
            if obstacle=='building':
                b=unit('uslh',77,x);b.y=y;bs.append(b)
            elif obstacle=='terrain':g.map=lambda:N(buildable=lambda x,y:False)
            else:
                g.trees=lambda *a,**kw:[N(x=x,y=y)];g.visible=lambda *a:True
            self.assertIsNone(l.build(g,w,'utom',h,60));self.assertFalse(orders)

    def test_other_spawn_map_and_additional_tower_are_not_this_template(self):
        l,g,h,w,bs,orders,events,order=self.scene()
        self.assertIsNone(fixed_slot('NI',h,'uaod',bs))
        self.assertIsNone(fixed_slot('LR',N(x=0,y=0),'uaod',bs))
        tower=unit('uzg1',88,4192);tower.y=3424;bs.append(tower)
        self.assertIsNone(fixed_slot('LR',h,'uzig',bs))

    def route_scene(self):
        s,g,u,h,v,e,q=critters.CritterSearchTests().make()
        s.map_alias='LR';h.x,h.y=3840,3328;u.x,u.y=4352,3136
        # Seeing a waypoint does not mean the worker has reached that waypoint.
        g.visible=lambda *p:True
        return s,g,u,h,v,e,q

    def test_replay_approach_uses_reached_points_not_global_visibility(self):
        s,g,u,h,v,e,q=self.route_scene()
        self.assertEqual(s.choose(g,u,h,60),LR_NE_APPROACH[0])
        u.x,u.y=LR_NE_APPROACH[0]
        self.assertEqual(s.choose(g,u,h,61),LR_NE_APPROACH[1])
        u.x,u.y=LR_NE_APPROACH[1];s.choose(g,u,h,62)
        self.assertTrue(s.reference_done)

    def test_approach_stall_or_unsafe_path_falls_back_without_claiming_kill(self):
        for unsafe in (False,True):
            s,g,u,h,v,e,q=self.route_scene()
            safe=lambda a,b:not unsafe
            s.choose(g,u,h,60,safe_route=safe)
            s.choose(g,u,h,69,safe_route=safe)
            self.assertTrue(s.reference_done)
            self.assertIsNone(s.hunt)
            self.assertTrue(any(r['event']=='scout_reference_deferred' for r in e))

    def test_approach_not_mirrored_and_deadline_remains_bounded(self):
        s,g,u,h,v,e,q=self.route_scene();h.x,h.y=0,0
        self.assertFalse(s.reference_active(h))
        h.x,h.y=3840,3328
        self.assertIsNone(s.choose(g,u,h,150));self.assertIsNone(s.reference_job)

    def test_southwest_uses_its_recorded_route(self):
        s,g,u,h,v,e,q=self.route_scene();h.x,h.y=-3904,-3968;u.x,u.y=-4416,-3776
        self.assertEqual(s.choose(g,u,h,60),LR_SW_APPROACH[0])
        u.x,u.y=LR_SW_APPROACH[0]
        self.assertEqual(s.choose(g,u,h,61),LR_SW_APPROACH[1])

    def test_reference_hunt_ignores_hidden_targets_and_neutral_guard(self):
        s,g,u,h,v,e,q=self.route_scene();animal=unit('npig',71,1400,15)
        animal.y=3500;animal.owner=15;animal.visible_to=lambda me:False;v.append(animal)
        g.me=lambda:1;g.creeps=lambda:[]
        self.assertIsNone(s.target(g,u,h,65))
        animal.visible_to=lambda me:True;guard=unit('nogr',72,1400);guard.y=3500
        g.creeps=lambda:[guard]
        self.assertIsNone(s.target(g,u,h,66))
        g.creeps=lambda:[]
        self.assertIs(s.target(g,u,h,67),animal)

    def test_controller_attacks_visible_critter_and_preserves_pursuit(self):
        b,g,dk,animal,own,all_units,orders,events,inv,cool=scout_fixture.ScoutCorpseTests().make()
        b.creeping.map_alias='LR';b.home=N(x=3840,y=3328);b.enemy_main=(-3904,-3968)
        b.scout_critter=None;animal.type='npig';animal.hp=15;animal.alive=True
        animal.x,animal.y=1416,3507;own[1].x,own[1].y=1300,3500
        current=[None];g.current_target=lambda u:current[0]
        g.attack=lambda u,t,force=False:orders.append(('reference_attack',u.handle,t.handle)) or True
        b.scout(74)
        self.assertEqual(orders[-1],('reference_attack',own[1].handle,animal.handle))
        self.assertIsNone(b.scout_corpse)
        current[0]=animal;before=len(orders);b.scout(75)
        self.assertEqual(len(orders),before)

    def test_pending_foundation_reserves_worker_without_duplicate_or_relocation(self):
        l,g,h,w,bs,orders,events,order=self.scene(True)
        first=l.build(g,w,'utom',h,60);order[0]=int.from_bytes(b'utom','big')
        w.x,w.y=first[0]+300,first[1];l.observe(g,61)
        self.assertEqual(l.reserved,{w.handle})
        self.assertEqual(l.build(g,w,'utom',h,61),first)
        self.assertEqual(len(orders),1)


if __name__=='__main__':unittest.main()
