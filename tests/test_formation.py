import unittest
from types import SimpleNamespace as N
import bootstrap
from openwar3.pathing import Grid
from undead.formation import Formation, distance

def u(code,x,y,i): return N(type=code,x=x,y=y,handle=(i,0),is_hero=code[0].isupper())

class FormationTests(unittest.TestCase):
    def test_opposite_sides_of_woods_correct_only_separated_unit(self):
        grid=Grid(20,20,100,0,0,bytearray(400))
        for row in range(16): grid.blocked[row*20+5]=1
        army=[u('Udea',650,250,1),u('Ulic',450,250,2),u('ucry',450,350,3)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(1800,300),0,grid.distance,grid.path)
        self.assertLess(distance((650,250),(450,250)),800)
        self.assertEqual(f.stage,'advance')
        self.assertEqual(orders[0][1],f.anchor)  # Only DK comes around the woods.
        self.assertFalse(any(hold for _,_,hold in orders))
        self.assertTrue(all(point==f.route[0] for _,point,_ in orders[1:]))
        self.assertIsNone(f.rally)

    def test_nearby_coarse_grid_disconnection_keeps_army_on_shared_exit(self):
        army=[u('Udea',0,0,1),u('Ulic',-220,150,2),u('ucry',0,-30,3)]
        def coarse(a,b):
            return None if a==(-220,150) else distance(a,b)
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(0,3000),0,coarse,lambda a,b:[(0,500),b])
        self.assertTrue(all(not hold and point==(0,500) for _,point,hold in orders))
        for obj,_,_ in orders:obj.y+=350
        orders=f.plan(army,(0,3000),2,distance,lambda a,b:[b])
        self.assertTrue(all(point[1]>=500 and not hold for _,point,hold in orders))
        self.assertIsNone(f.rally)

    def test_distant_disconnected_unit_does_not_stop_main_body(self):
        army=[u('Udea',0,0,1),u('Ulic',-1100,0,2),u('ucry',0,-30,3)]
        def coarse(a,b):
            return None if a==(-1100,0) else distance(a,b)
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(0,3000),0,coarse,lambda a,b:[b])
        self.assertEqual(f.stage,'advance')
        self.assertEqual(orders[1][1],f.anchor)
        self.assertTrue(all(point==(0,3000) for obj,point,_ in orders if obj is not army[1]))
        self.assertFalse(any(hold for _,_,hold in orders))

    def test_open_ground_does_not_wait_for_spread_or_intermediate_waypoints(self):
        army=[u('Udea',500,0,1),u('Ulic',0,30,2),u('ucry',-500,-30,3)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(4000,0),0,distance,lambda a,b:[b])
        self.assertEqual(f.stage,'advance')
        self.assertEqual({p for _,p,_ in orders},{(4000,0)})
        self.assertFalse(any(hold for _,_,hold in orders))

    def test_only_leading_dk_returns_to_moving_main_body_then_resumes(self):
        army=[u('Udea',1000,0,1),u('Ulic',0,30,2),u('ucry',0,-30,3)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(4000,0),0,distance,lambda a,b:[b])
        self.assertFalse(orders[0][2])
        self.assertEqual(orders[0][1],f.anchor)
        self.assertTrue(all(not hold and p==(4000,0) for _,p,hold in orders[1:]))
        army[1].x=army[2].x=500
        orders=f.plan(army,(4000,0),2,distance,lambda a,b:[b])
        self.assertFalse(any(hold for _,_,hold in orders))
        self.assertTrue(all(point==(4000,0) for _,point,_ in orders))
        army[0].x=-500
        orders=f.plan(army,(4000,0),4,distance,lambda a,b:[b])
        self.assertFalse(orders[0][2]) # A trailing DK catches up instead of braking.

    def test_units_pass_shared_terrain_turns_without_waiting_for_tail(self):
        army=[u('Udea',0,0,1),u('Ulic',0,30,2),u('ucry',0,-30,3)]
        f=Formation(lambda *a,**k:None)
        turns=[(0,1000),(1000,1000),(1000,0)]
        f.plan(army,(1000,0),0,distance,lambda a,b:turns)
        army[1].y=1000
        orders=f.plan(army,(1000,0),2,distance,lambda a,b:turns)
        self.assertEqual(orders[1][1],(1000,1000))
        self.assertFalse(orders[1][2])
        self.assertEqual(orders[2][1],(0,1000))

    def test_open_march_simulation_keeps_moving_with_dk_in_aura_range(self):
        army=[u('Udea',0,0,1),u('Ulic',-50,0,2),u('ucry',-100,0,3)]
        f=Formation(lambda *a,**k:None)
        max_gap=0
        for now in range(30):
            orders=f.plan(army,(12000,0),now,distance,lambda a,b:[b])
            for obj,point,hold in orders:
                if not hold:obj.x+=min(400 if obj.type=='Udea' else 270,point[0]-obj.x)
            max_gap=max(max_gap,abs(army[0].x-army[2].x))
        self.assertGreater(army[2].x,7900)
        self.assertLessEqual(max_gap,1200) # Severe-gap correction plus one simulation-step margin.

    def test_shared_route_follows_terrain_turns(self):
        grid=Grid(20,20,100,0,0,bytearray(400))
        for row in range(16): grid.blocked[row*20+5]=1
        army=[u('Udea',350,250,1),u('Ulic',350,350,2),u('ucry',250,250,3)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(1650,250),0,grid.distance,grid.path)
        self.assertTrue(any(y>=1600 for x,y in f.route))
        self.assertEqual(len({p for _,p,_ in orders}),1)
        self.assertLess(orders[0][1][0],500)

    def test_missing_route_holds_everyone_and_does_not_fall_back_to_solo_routing(self):
        army=[u('Udea',0,0,1),u('ucry',0,20,2)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(1000,0),0,distance,lambda a,b:None)
        self.assertEqual(f.stage,'blocked')
        self.assertTrue(all(hold for _,_,hold in orders))

    def test_hero_retreat_does_not_wait_for_distant_reinforcements(self):
        army=[u('Udea',0,0,1),u('ucry',2000,0,2)]
        f=Formation(lambda *a,**k:None)
        orders=f.plan(army,(-2000,0),0,distance,lambda a,b:[b],retreat=True)
        self.assertEqual(f.stage,'retreat')
        self.assertTrue(all(not hold for _,_,hold in orders))
        self.assertEqual(len({p for _,p,_ in orders}),1)

if __name__=='__main__':unittest.main()
