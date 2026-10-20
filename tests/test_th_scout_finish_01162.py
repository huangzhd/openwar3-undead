import json
import unittest
from pathlib import Path
import test_th_scout_route_01159 as th
from test_micro_loot import unit,dist


class THScoutFinishTests(unittest.TestCase):
    def scene(self):
        b,g,s,units,orders,events,c,p=th.THScoutTests().scene()
        proof=json.loads((Path(__file__).parent/'fixtures/th_003711_scout_hunt.json').read_text(encoding='utf-8'))['events']
        start=next(e for e in proof if e['event']=='scout_critter_attack_attempt')
        end=next(e for e in proof if e['event']=='scout_critter_abandoned')
        target=th.THScoutTests().critter(units,*start['point'])
        s.x=target.x-start['distance'];s.y=target.y
        b.scout(start['clock'])
        target.x,target.y=end['point'];target.hp=end['hp']
        # The log records path distance, not the final scout coordinate.
        # Reconstruct a nearby finishing position; retain actual target data.
        s.x=target.x-end['distance'];s.y=target.y
        guard=unit('ntrt',50,target.x+600);guard.y=target.y
        guard.owner=12
        g.creeps=lambda:[guard]
        g.current_target=lambda u:target if u is s else None
        orders.clear()
        return b,g,s,target,guard,orders,events,end

    def test_actual_damaged_target_keeps_attack_despite_outer_guard_circle(self):
        b,g,s,t,e,orders,events,end=self.scene()
        b.scout(end['clock'])
        self.assertFalse(orders) # No move overrides the running attack.
        self.assertEqual(b.critter_search.hunt['handle'],t.handle)
        self.assertTrue(any(r['event']=='scout_critter_finish_committed' for r in events))
        self.assertIsNone(b.scout_corpse)
        t.hp=0;t.alive=False;b.scout(end['clock']+1.5)
        self.assertIsNotNone(b.scout_corpse)
        self.assertTrue(any(r['event']=='scout_neutral_detour' and r['goal']==b.enemy_main
                            for r in events)) # Enemy scouting retains visible-guard avoidance.

    def test_actual_attackers_or_weapon_range_cancel_finishing_exception(self):
        for attacking in (True,False):
            b,g,s,t,e,orders,events,end=self.scene()
            if attacking:g.current_target=lambda u:t if u is s else s if u is e else None
            else:e.x=s.x+30;e.y=s.y
            b.scout(end['clock'])
            self.assertIn(t.handle,b.critter_search.hunt_failed)
            self.assertIsNone(b.scout_corpse)

    def test_hurt_worker_and_full_health_critter_do_not_get_exception(self):
        for hurt in (True,False):
            b,g,s,t,e,orders,events,end=self.scene()
            if hurt:s.hp=.6*s.hp_max
            else:t.hp=15
            b.scout(end['clock'])
            self.assertIn(t.handle,b.critter_search.hunt_failed)

    def test_progressing_static_destination_survives_old_24_second_budget(self):
        b,g,s,units,orders,events,c,p=th.THScoutTests().scene()
        b.scout(64.65)
        goal=(p['x'],p['y'])
        for now,x in [(70,-3400),(76,-2900),(82,-2300),(89.305,-1743),(94,-1300)]:
            s.x=x;s.y=1984;b.scout(now)
            self.assertEqual(b.critter_search.job['point'],goal)
            self.assertEqual(orders[-1][2],goal)
        b.scout(103) # No progress still has a bounded exit.
        self.assertIn(goal,b.critter_search.failed)

    def test_opening_travel_does_not_detour_for_unseen_static_guards(self):
        b,g,s,units,orders,events,c,p=th.THScoutTests().scene()
        b.start_search.camps=[dict(id='risk',spawns=[dict(x=s.x+900,y=s.y,code='ntrt')])]
        b.scout(65)
        self.assertEqual(orders[-1][2],(p['x'],p['y']))
        self.assertFalse(any(e['event']=='scout_neutral_detour' for e in events))

    def test_visible_threat_still_detours_and_terrain_turn_is_not_subdivided(self):
        b,g,s,units,orders,events,c,p=th.THScoutTests().scene()
        s.x=0;s.y=0
        guard=unit('ntrt',50,1000);guard.y=0;guard.visible_to=lambda _:True
        g.creeps=lambda:[guard]
        point=b.start_search.safe_step(g,s,(2500,0),65,public_layout=False,step_limit=None)
        self.assertNotEqual(point,(2500,0))
        self.assertGreater(dist(s,point),350)
        # Every point of this simple visible-threat detour stays outside 800.
        for i in range(101):
            self.assertGreaterEqual(dist((point[0]*i/100,point[1]*i/100),guard),799)


if __name__=='__main__':unittest.main()
