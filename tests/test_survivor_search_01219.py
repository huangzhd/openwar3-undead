import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock
import test_backline_endgame_01199 as endgame
from test_baseline import unit
from undead.policy import Action


class SurvivorSearchTests(unittest.TestCase):
    def scene(self):
        b,g,own,foes,orders,events,effects=endgame.EndgameTests().scene()
        b.update_training_phase(70,2,True)
        return b,g,own,foes,orders,events,effects

    def test_rejected_nearby_shade_does_not_pin_pursuit_of_distant_blade(self):
        b,g,own,foes,orders,events,effects=self.scene()
        shade=unit('ushd',81,owner=1,x=50);shade.hp=8.75;shade.has_detail=True
        blade=unit('Obla',82,owner=1,x=1400);blade.hp=338.97;blade.has_detail=True
        b.combat_progress.quarantine(shade,100,'repeated_rejected_attacks')
        targets=b.refresh_survivors(own,[shade,blade],101)
        self.assertEqual(targets,[blade])
        self.assertIsNone(b.search_target(own,[shade,blade],101))
        self.assertEqual(b.last_foe_position,(1400,0))
        b.pursue_survivors(own,[shade,blade],101)
        self.assertTrue(any(o[0]=='attack_move' and o[2][0]>100 for o in orders))

    def test_quarantined_last_unit_is_retried_without_resetting_search(self):
        b,g,own,foes,orders,events,effects=self.scene()
        shade=unit('ushd',81,owner=1,x=50);shade.hp=8.75;shade.has_detail=True
        b.combat_progress.quarantine(shade,100,'rejected')
        self.assertEqual(b.refresh_survivors(own,[shade],100),[])
        b.search_target(own,[],100);route=list(b.search_route)
        self.assertEqual(b.refresh_survivors(own,[shade],119),[])
        self.assertEqual(b.refresh_survivors(own,[shade],120),[shade])
        b.search_target(own,[shade],120)
        self.assertEqual(b.search_route,route)
        b.combat_progress.quarantine(shade,121,'rejected')
        self.assertEqual(b.refresh_survivors(own,[shade],122),[])
        shade.hp+=10
        self.assertEqual(b.refresh_survivors(own,[shade],123),[shade])

    def test_public_map_route_covers_bounds_and_keeps_cycling_without_win(self):
        b,g,own,foes,orders,events,effects=self.scene()
        g.map=lambda:N(bounds=(-2000,2000,-2000,2000),walkable=lambda x,y:x!=1120)
        b.search_target(own,[],100)
        self.assertGreater(len(b.search_route),20)
        added=b.search_route[9:]
        self.assertTrue(all(-2000<x<2000 and -2000<y<2000 and x!=1120 for x,y in added))
        self.assertTrue(any(x>0 and y>0 for x,y in added))
        self.assertTrue(any(x<0 and y<0 for x,y in added))
        for i in range(len(b.search_route)*2):self.assertIsNotNone(b.search_target(own,[],130+i*29))
        self.assertTrue(b.training_endgame)

    def test_low_health_retreat_and_cast_locks_override_search(self):
        for reason in ('low','retreat','recovery','cast','blocked'):
            b,g,own,foes,orders,events,effects=self.scene();u=own[0];blocked=set()
            if reason=='low':u.hp=u.hp_max*.4
            if reason=='retreat':b.action=Action.RETREAT
            if reason=='recovery':b.army_recovery.active=True
            if reason=='cast':b.cast_until[u.handle]=200
            if reason=='blocked':blocked.add(u.handle)
            b.pursue_survivors([u],[],100,blocked,search_point=(1400,0))
            self.assertFalse(orders,reason)

    def test_dk_follows_searching_army_without_charging_survivor(self):
        b,g,own,foes,orders,events,effects=self.scene()
        dk=unit('Udea',83,owner=0,x=-1000);dk.hp=dk.hp_max=900;own.append(dk)
        b.army_recovery.safe_path=Mock(return_value=400)
        b.follow_search_dk(own,[],100)
        moves=[o for o in orders if o[0]=='move' and o[1]==dk.handle]
        self.assertEqual(moves[0][2],(-600.,0.))
        orders.clear();dk.hp=400;b.follow_search_dk(own,[],102)
        self.assertFalse(orders)

    def test_destroyer_can_search_air_survivor_without_ground_path(self):
        b,g,own,foes,orders,events,effects=self.scene()
        car=next(u for u in own if u.type=='ubsp');car.x=0
        bird=unit('owyv',82,owner=1,x=1500);bird.has_detail=True
        g.path_distance=lambda *a:None
        b.pursue_survivors([car],[bird],100)
        self.assertTrue(any(o[0]=='attack_move' and o[1]==car.handle for o in orders))

    def test_air_only_search_releases_spacing_but_not_protection(self):
        for reason in ('spacing','hurt','pulling','cast','foes'):
            b,g,own,foes,orders,events,effects=self.scene()
            car=next(u for u in own if u.type=='ubsp');pulls={car.handle:(-800,0)}
            if reason=='hurt':car.hp=car.hp_max*.4
            if reason=='pulling':b.micro.pulling.add(car.handle)
            if reason=='cast':b.cast_until[car.handle]=200
            b.release_air_search_positions([car],foes if reason=='foes' else [],100,pulls)
            self.assertEqual(car.handle in pulls,reason!='spacing')
            if not pulls:
                b.pursue_survivors([car],[],100,search_point=(1400,0))
                self.assertTrue(any(o[0]=='attack_move' for o in orders))


if __name__=='__main__':unittest.main()
