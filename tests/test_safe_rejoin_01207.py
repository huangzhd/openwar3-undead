import unittest
from types import SimpleNamespace as N
import test_tc_pressure_01186 as battle
from undead.controller import Controller
from undead.policy import Action
from training import TrainingController


class SafeRejoinTests(unittest.TestCase):
    def scene(self,code='Udea',kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=battle.TcFirstTests().scene(kind)
        u=next((v for v in own if v.type==code),own[0])
        u.type=code;u.hp=u.hp_max*.3;u.x=-1600;u.y=0
        b.micro.pulling.add(u.handle)
        if code=='Udea':b.dk_battle_recovering=True
        if code=='uobs':b.statue_support.retreating.add(u.handle)
        g.current_target=lambda v:None
        return b,g,own,foes,orders,events,effects,u

    def ready(self,b,own,foes,u):
        pulls={u.handle:(u.x,u.y)}
        b.rejoin_battle_units(own,foes,10,pulls)
        self.assertEqual(pulls[u.handle],(u.x,u.y))
        b.rejoin_battle_units(own,foes,13,pulls)
        return pulls

    def test_all_regular_roles_return_after_quiet_in_both_controllers(self):
        self.assertIs(Controller.rejoin_battle_units,TrainingController.rejoin_battle_units)
        for kind in (Controller,TrainingController):
            for code in ('Udea','Ulic','Nbrn','Nngs','ucry','ugho','ubsp','uobs','uban'):
                with self.subTest(kind=kind.__name__,code=code):
                    b,g,own,foes,orders,events,effects,u=self.scene(code,kind)
                    pulls=self.ready(b,own,foes,u)
                    self.assertGreater(pulls[u.handle][0],u.x+300)
                    self.assertLessEqual(g.dist(pulls[u.handle],own[1]),700)
                    self.assertTrue(any(e=='battle_safe_rejoin' for e,_ in events))

    def test_dk_returns_to_coil_and_aura_range_without_melee_and_can_heal(self):
        b,g,own,foes,orders,events,effects,u=self.scene();lich=own[6];lich.hp=150
        b.micro.dk_support={'point':(u.x,u.y)}
        pulls=self.ready(b,own,foes,u);point=pulls[u.handle]
        self.assertLessEqual(g.dist(point,lich),700)
        self.assertGreaterEqual(sum(g.dist(point,v)<=900 for v in own),len(own)//2)
        self.assertIsNone(b.micro.dk_support)
        u.x,u.y=point;b.rejoin_battle_units(own,foes,14,pulls)
        b.attack_dk(own,foes,14,set(pulls));b.heal_allies(own,15)
        self.assertFalse(any(o[0]=='attack' and o[1]==u.handle for o in orders))
        self.assertTrue(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target']==lich for o in orders))

    def test_returned_ranged_units_fire_in_place_and_move_loop_does_not_cancel(self):
        for code in ('ucry','Ulic','Nbrn','ubsp'):
            b,g,own,foes,orders,events,effects,u=self.scene(code)
            foes[:]=[foes[2]];foes[0].type='ogru' # Melee enemy permits safe ranged fire.
            pulls=self.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
            orders.clear();b.rejoin_battle_units(own,foes,14,pulls)
            self.assertTrue(any(o[0]=='attack' and o[1]==u.handle for o in orders),code)
            b.go_raw([u],pulls[u.handle],14)
            self.assertFalse(any(o[0]=='move' and o[1]==u.handle for o in orders),code)

    def test_statue_rejoins_then_resumes_supply(self):
        b,g,own,foes,orders,events,effects,u=self.scene('uobs')
        own[1].hp=200
        pulls=self.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
        b.rejoin_battle_units(own,foes,14,pulls)
        self.assertNotIn(u.handle,pulls)
        b.statue_support.tick(b,own,foes,14,set(pulls))
        self.assertTrue(any(o[0]=='cast' and o[1]==u.handle and o[2]=='replenishlife' for o in orders))

    def test_chasing_recent_damage_or_exposure_resets_quiet(self):
        for why in ('chasing','damage','exposure'):
            b,g,own,foes,orders,events,effects,u=self.scene()
            pulls={u.handle:(u.x,u.y)};b.rejoin_battle_units(own,foes,10,pulls)
            if why=='chasing':g.current_target=lambda v:u if v==foes[0] else None
            if why=='damage':b.micro.hit[u.handle]=12
            if why=='exposure':foes[0].x=u.x+100
            b.rejoin_battle_units(own,foes,13,pulls)
            self.assertEqual(pulls[u.handle],(u.x,u.y),why)
            self.assertIsNone(b.battle_rejoin[u.handle]['quiet'],why)
            g.current_target=lambda v:None;foes[0].x=400
            b.rejoin_battle_units(own,foes,16,pulls)
            self.assertEqual(pulls[u.handle],(u.x,u.y),why)
            b.rejoin_battle_units(own,foes,19,pulls)
            self.assertGreater(pulls[u.handle][0],u.x,why)

    def test_unsafe_or_missing_path_preserves_escape_order(self):
        for why in ('missing','obstacle','detour','crosses_enemy'):
            b,g,own,foes,orders,events,effects,u=self.scene()
            if why=='missing':g.walk_path=lambda *a:None
            if why=='obstacle':g.map=lambda:N(walkable=lambda *a:False)
            if why=='detour':g.path_distance=lambda *a:10000
            if why=='crosses_enemy':g.walk_path=lambda a,p:[a,(foes[0].x,foes[0].y),p]
            pulls=self.ready(b,own,foes,u)
            self.assertEqual(pulls[u.handle],(u.x,u.y),why)

    def test_cached_route_is_rechecked_before_next_plan_interval(self):
        b,g,own,foes,orders,events,effects,u=self.scene()
        self.ready(b,own,foes,u)
        g.walk_path=lambda a,p:[a,(foes[0].x,foes[0].y),p]
        pulls={u.handle:(u.x-100,u.y)}
        b.rejoin_battle_units(own,foes,13.2,pulls)
        self.assertEqual(pulls[u.handle],(u.x-100,u.y))

    def test_exclusive_rescue_cast_and_whole_army_retreat_are_preserved(self):
        for why in ('blocked','cast','stun','shield','shop','burrow','creep','teleport','retreat','recovery'):
            b,g,own,foes,orders,events,effects,u=self.scene();blocked=set()
            if why=='blocked':blocked.add(u.handle)
            if why=='cast':b.cast_until[u.handle]=20
            if why=='stun':effects[u.handle]=['BSTN']
            if why=='shield':b.shield_moves[u.handle]=(100,100)
            if why=='shop':b.shopping.add(u.handle)
            if why=='burrow':b.fiend_burrow.pending[u.handle]={}
            if why=='creep':b.creep_aggro.active={'victim':u.handle}
            if why=='teleport':b.teleport={'hero':u.handle}
            if why=='retreat':b.action=Action.RETREAT
            if why=='recovery':b.army_recovery.active=True
            pulls={u.handle:(-1800,0)}
            for now in (10,13):b.rejoin_battle_units(own,foes,now,pulls,blocked)
            self.assertEqual(pulls[u.handle],(-1800,0),why)
            self.assertFalse(orders,why)

    def test_rejoin_tracks_moving_army_even_after_enemies_leave_sight(self):
        b,g,own,foes,orders,events,effects,u=self.scene('ugho')
        pulls=self.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
        b.micro.pulling.clear();foes.clear()
        for v in own:
            if v!=u:v.x+=1200
        b.rejoin_battle_units(own,foes,16,pulls)
        self.assertGreater(pulls[u.handle][0],u.x+300)
        u.hp=u.hp_max;b.rejoin_battle_units(own,foes,17,{})
        self.assertNotIn(u.handle,b.battle_rejoin)

    def test_skeletons_keep_their_autonomous_orders(self):
        for code in ('uske','uskm','ndr1','ndr2','ndr3'):
            b,g,own,foes,orders,events,effects,u=self.scene(code)
            pulls=self.ready(b,own,foes,u)
            self.assertEqual(pulls[u.handle],(u.x,u.y))
            self.assertFalse(orders)

    def test_injured_ghoul_returns_to_tanked_soldier_then_stops_when_target_turns(self):
        b,g,own,foes,orders,events,effects,u=self.scene('ugho')
        foe=foes[0];foe.type='ogru';foes[:]=[foe]
        tank=own[1];tank.x=foe.x-50
        g.current_target=lambda v:tank if v==foe else None
        pulls=self.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
        b.rejoin_battle_units(own,foes,14,pulls)
        self.assertIn(('attack',u.handle,foe.handle),orders)
        g.current_target=lambda v:u if v==foe else None
        escape=(u.x-500,u.y);pulls={u.handle:escape};orders.clear()
        b.rejoin_battle_units(own,foes,15,pulls)
        self.assertEqual(pulls[u.handle],escape)
        self.assertFalse(orders)

    def test_melee_never_waives_hero_threat_or_uses_wounded_ally_as_tank(self):
        for why in ('hero','injured_tank','critical_self'):
            b,g,own,foes,orders,events,effects,u=self.scene('ugho')
            foe=foes[0];foe.type='ogru';foes[:]=[foe]
            tank=own[1];tank.x=foe.x-50
            if why=='hero':foe.type='Otch';foe.is_hero=True
            if why=='injured_tank':tank.hp=tank.hp_max*.3
            if why=='critical_self':u.hp=u.hp_max*.2
            g.current_target=lambda v:tank if v==foe else None
            pulls=self.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
            b.rejoin_battle_units(own,foes,14,pulls)
            self.assertFalse(any(o[0]=='attack' and o[1]==u.handle for o in orders),why)

    def test_shared_battle_pipeline_retains_rejoin_through_final_move_and_attack(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,u=self.scene('Udea',kind)
            g.cooldown=lambda *a:5
            for now in (10,13):
                pulls={u.handle:(u.x,u.y)}
                b.battle_actions(own,foes,now,pulls)
            self.assertGreater(pulls[u.handle][0],u.x+300)
            orders.clear();b.go_raw([u],pulls[u.handle],13)
            b.engage_battle([v for v in own if v.handle not in pulls],foes,13)
            self.assertIn(('move',u.handle,pulls[u.handle]),orders)
            self.assertFalse(any(o[0]=='attack' and o[1]==u.handle for o in orders))


if __name__=='__main__':unittest.main()
