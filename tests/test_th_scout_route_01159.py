import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit, dist
import test_scout_opening as opening
from undead.creeping import Creeping


class THScoutTests(unittest.TestCase):
    def scene(self, north=True):
        b,g,dk,old,own,units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        data=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['TH']
        b.home=N(x=-3904,y=2880) if north else N(x=2880,y=-3904)
        b.enemy_main=(2880,-3904) if north else (-3904,2880)
        scout=own[1];scout.x=b.home.x;scout.y=b.home.y
        units.remove(old);b.scout_critter=None
        b.creeping=Creeping(b.log,data['camps']);b.creeping.map_alias='TH'
        b.critter_search.spawns=data['critters']
        g.attack=lambda u,target,**kw:orders.append(('attack',[u.handle],[target.handle])) or True
        g.visible=lambda *p:False
        first=next(c for c in data['camps'] if c['id']==b.creeping.th_route(b.home)[0])
        spawn=min(data['critters'],key=lambda p:dist((first['x'],first['y']),(p['x'],p['y'])))
        return b,g,scout,units,orders,events,first,spawn

    def critter(self,units,x,y,i=10):
        c=unit('ncrb',i,x,15);c.y=y;c.hp_max=15;c.owner=15;c.alive=True
        c.visible_to=lambda me:True
        units.append(c)
        return c

    def test_both_spawns_go_to_42_critter_region_instead_of_home_region(self):
        for north in (True,False):
            b,g,s,units,orders,events,c,p=self.scene(north)
            b.scout(65)
            self.assertEqual(orders[-1],('move',[s.handle],(p['x'],p['y'])))
            self.assertEqual(b.critter_search.camp_focus,(c['x'],c['y']))
            self.assertTrue(all(dist(point,(c['x'],c['y']))<=1500 for point in b.critter_search.points))
            self.assertIsNone(b.scout_corpse) # Map placement is not death evidence.

    def test_ignores_old_route_visible_critter_and_uses_only_worker(self):
        b,g,s,units,orders,events,c,p=self.scene()
        old=self.critter(units,-2029,4308)
        near=self.critter(units,p['x'],p['y'],11)
        s.x=near.x-100;s.y=near.y
        b.scout(80)
        self.assertEqual(orders[-1],('attack',[s.handle],[near.handle]))
        self.assertNotEqual(b.scout_critter,old.handle)
        self.assertIsNone(b.scout_corpse)

    def test_confirmed_kill_releases_scout_and_preserves_corpse_for_dk(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);s.x=target.x-100;s.y=target.y
        b.scout(80)
        target.hp=0;target.alive=False
        b.scout(82)
        self.assertEqual(b.scout_corpse['point'],(target.x,target.y))
        self.assertEqual(orders[-1],('move',[s.handle],b.enemy_main))
        self.assertTrue(b.opening_corpse_pending(125))

    def test_hidden_target_is_not_attacked_and_lost_vision_is_not_a_corpse(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);target.visible_to=lambda me:False
        b.scout(80)
        self.assertFalse(any(o[0]=='attack' for o in orders))
        self.assertIsNone(b.scout_critter);self.assertIsNone(b.scout_corpse)

    def test_neutral_guard_and_blocked_route_do_not_force_attack(self):
        for blocked in (False,True):
            b,g,s,units,orders,events,c,p=self.scene()
            target=self.critter(units,p['x'],p['y']);s.x=target.x-100;s.y=target.y
            if blocked:g.path_distance=lambda *a:None
            else:
                guard=unit('ntrt',20,target.x+100);guard.y=target.y
                g.creeps=lambda:[guard]
            b.scout(80)
            self.assertFalse(any(o[0]=='attack' for o in orders))
            self.assertIsNone(b.scout_corpse)

    def test_empty_visible_region_and_deadline_continue_enemy_scouting(self):
        for expired in (False,True):
            b,g,s,units,orders,events,c,p=self.scene()
            if expired:
                b.scout(65)
                b.scout(150)
            else:
                g.visible=lambda *point:point!=b.enemy_main
                b.scout(80)
            self.assertEqual(orders[-1],('move',[s.handle],b.enemy_main))
            self.assertIsNone(b.scout_corpse)

    def test_non_th_keeps_generic_search(self):
        b,g,s,units,orders,events,c,p=self.scene()
        b.creeping.map_alias='CH'
        b.scout(65)
        self.assertIsNone(b.critter_search.camp_focus)
        self.assertNotEqual(orders[-1][2],(p['x'],p['y']))

    def test_fleeing_acquired_critter_outside_search_radius_stays_targeted(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);s.x=target.x-100;s.y=target.y
        b.scout(80)
        target.y=900;s.y=900
        self.assertGreater(dist(target,(c['x'],c['y'])),1500)
        g.visible=lambda *point:point!=b.enemy_main
        b.scout(82)
        self.assertEqual(orders[-1],('attack',[s.handle],[target.handle]))
        self.assertFalse(b.critter_search.reported)
        self.assertEqual(b.critter_search.hunt['handle'],target.handle)

    def test_visible_critter_far_away_receives_attack_instead_of_point_move(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);s.x=target.x-900;s.y=target.y
        b.scout(80)
        self.assertEqual(orders[-1],('attack',[s.handle],[target.handle]))
        self.assertEqual(events[-1]['event'],'scout_critter_attack_attempt')
        self.assertTrue(events[-1]['accepted'])
        g.current_target=lambda u:target
        before=len(orders);b.scout(82)
        self.assertEqual(len(orders),before) # Preserve an active attack.

    def test_latched_hunt_does_not_ignore_new_neutral_danger(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);s.x=target.x-100;s.y=target.y
        b.scout(80);orders.clear()
        guard=unit('ntrt',20,target.x+100);guard.y=target.y;g.creeps=lambda:[guard]
        b.scout(82)
        self.assertFalse(any(o[0]=='attack' for o in orders))
        self.assertTrue(any(e['event']=='scout_critter_abandoned' and e['reason']=='neutral_guard' for e in events))
        self.assertIsNone(b.scout_corpse)

    def test_lost_target_is_logged_and_never_inferred_dead(self):
        b,g,s,units,orders,events,c,p=self.scene()
        target=self.critter(units,p['x'],p['y']);s.x=target.x-100;s.y=target.y
        b.scout(80);units.remove(target)
        b.scout(82);self.assertIsNotNone(b.critter_search.hunt)
        b.scout(87)
        self.assertTrue(any(e['event']=='scout_critter_abandoned' and e['reason']=='target_not_visible' for e in events))
        self.assertIsNone(b.scout_corpse)


if __name__=='__main__':unittest.main()
