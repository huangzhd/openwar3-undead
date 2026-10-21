import unittest
from types import SimpleNamespace as N
import test_dark_ranger_tanking as tanking
import test_battle_shop_0163 as shopping
import test_camp_summon_01171 as summon
import test_opening_safety_0131 as ticks
import test_al_route_01166 as routes
from test_micro_loot import unit,dist
from undead.formation import Formation
from undead.policy import Action


class ArrivalTests(unittest.TestCase):
    def test_departure_captures_nearby_party_without_later_reinforcements(self):
        b,g,a,c=routes.ALRouteTests().scene()
        dk=a[0];near=unit('ucry',90,dk.x+100);near.y=dk.y
        far=unit('ucry',91,dk.x+2500);far.y=dk.y
        b.go=lambda *a,**kw:None
        b.creep([*a,near,far],(dk.x,dk.y),145)
        self.assertIn(near.handle,b.creep_party);self.assertNotIn(far.handle,b.creep_party)
        newcomer=unit('ucry',92,dk.x);newcomer.y=dk.y
        original=set(b.creep_party)
        b.creep([*a,near,far,newcomer],(dk.x,dk.y),146)
        self.assertEqual(b.creep_party,original)

    def scene(self):
        b,dk,sk,e,attacks,holds,targets,events=tanking.SkeletonOpeningTests().setup_fight()
        moves=[];b.go_raw=lambda us,p,t:moves.extend((u.handle,p) for u in us)
        f=unit('ucry',10,-700)
        b.creep_party={u.handle for u in (dk,sk,f)}
        return b,dk,sk,f,e,attacks,holds,moves,targets

    def test_waits_only_for_departing_party_then_first_hit_releases_main(self):
        b,dk,sk,f,e,attacks,holds,moves,targets=self.scene()
        late=unit('ucry',11,-3000);new=unit('ucry',12,-4000)
        army=[dk,sk,f,late,new,unit('ucry',13,-4100),unit('ucry',14,-4200)]
        self.assertTrue(b.skeleton_opening(army,[e],10));self.assertFalse(attacks)
        before=list(holds);b.skeleton_opening(army,[e],11)
        self.assertEqual(holds,before) # No repeated stop/formation orders.
        f.x=0;moves.clear()
        self.assertTrue(b.skeleton_opening(army,[e],12))
        self.assertEqual(attacks,[(sk.handle,e.handle)])
        self.assertTrue({late.handle,new.handle}<={h for h,p in moves})
        targets[e.handle]=sk
        self.assertTrue(b.skeleton_opening(army,[e],12.5)) # Aggro alone is not the first hit.
        e.hp-=12
        self.assertFalse(b.skeleton_opening(army,[e],13))
        self.assertFalse(b.skeleton_opening(army,[e],14))

    def test_shop_and_recovery_members_do_not_delay_camp(self):
        for mode in ('shopping','reserved','pulling'):
            b,dk,sk,f,e,attacks,holds,moves,targets=self.scene()
            if mode=='shopping':b.shopping.add(f.handle)
            elif mode=='reserved':b.battle_shop.orb=dict(hero=f.handle)
            else:b.micro.pulling.add(f.handle)
            b.skeleton_opening([dk,sk,f],[e],10)
            self.assertEqual(attacks,[(sk.handle,e.handle)],mode)

    def test_stuck_party_member_has_one_bounded_wait_not_repeated_holds(self):
        b,dk,sk,f,e,attacks,holds,moves,targets=self.scene()
        b.skeleton_opening([dk,sk,f],[e],10)
        b.skeleton_opening([dk,sk,f],[e],18)
        self.assertEqual(attacks,[(sk.handle,e.handle)])
        self.assertFalse(b.skeleton_opening([dk,sk,f],[e],30))
        self.assertFalse(b.skeleton_opening([dk,sk,f],[e],40))

    def test_forward_skeleton_cannot_open_while_travel_party_is_far_behind(self):
        b,dk,sk,f,e,attacks,holds,moves,targets=self.scene()
        dk.x=-1400;f.x=-1500;sk.x=400
        b.skeleton_opening([dk,sk,f],[e],10)
        self.assertFalse(attacks)
        self.assertTrue(all(p[0]<e.x for h,p in moves))
        self.assertTrue({dk.handle,f.handle,sk.handle}<={h for h,p in moves})

    def test_nearby_path_detour_does_not_reverse_dk_while_army_advances(self):
        dk=unit('Udea',1,-1199);dk.y=-3698
        f=unit('ucry',2,-1604);f.y=-3775
        target=(2176,-3049);formation=Formation(lambda *a,**k:None)
        def terrain(a,b):
            return 1200 if dist(a,b)<600 and a!=b else dist(a,b)
        orders=formation.plan([f,dk],target,249.63,terrain,lambda a,b:[(64,-2880),b])
        self.assertTrue(all(p==(64,-2880) and not hold for u,p,hold in orders))
        self.assertFalse(formation.catching_up)

    def test_casting_carrier_filtered_from_combat_still_confirms_actual_pair(self):
        fixture=summon.CampSummonTests()
        b,g,a,c,own,orders,events,cool,ok=fixture.scene()
        b.camp_summon.tick(b,a,178);b.cast_until[a[0].handle]=181
        self.assertTrue(b.camp_summon.tick(b,a[1:],179))
        fixture.spawn(b,own,179.5)
        self.assertFalse(b.camp_summon.tick(b,own[1:],180))
        self.assertTrue(events[-1]['confirmed'])

    def test_casting_dk_remains_in_departing_party_and_is_waited_for_later(self):
        fixture=summon.CampSummonTests()
        b,g,a,c,own,orders,events,cool,ok=fixture.scene()
        dk=a[0];center=(dk.x,dk.y)
        b.camp_summon.tick(b,a,178);b.cast_until[dk.handle]=181
        fixture.spawn(b,own,179.5);b.creep_strength=own
        b.creep(own[1:],center,180)
        self.assertIn(dk.handle,b.creep_party)
        camp=c.active;guard=unit('nftb',990,camp['x'],400);guard.owner=12;guard.y=camp['y']
        for u in own[1:]:u.x=guard.x-700;u.y=guard.y
        dk.x=guard.x-1400;dk.y=guard.y
        attacks=[];g.attack=lambda u,t:attacks.append(u.handle) or True;g.hold=lambda u:True
        self.assertTrue(b.skeleton_opening(own,[guard],182))
        self.assertFalse(attacks)
        self.assertTrue(any(o[0]=='move' and o[1]==dk.handle for o in orders))

    def test_target_switch_does_not_restart_camp_wait_budget(self):
        b,dk,sk,f,e,attacks,holds,moves,targets=self.scene()
        other=unit(e.type,99,600);other.owner=12
        b.creeping.active=dict(id='same-camp')
        self.assertTrue(b.skeleton_opening([dk,sk,f],[e,other],10))
        e.x=700
        self.assertTrue(b.skeleton_opening([dk,sk,f],[e,other],14));self.assertFalse(attacks)
        self.assertTrue(b.skeleton_opening([dk,sk,f],[e,other],18))
        self.assertEqual(attacks,[(sk.handle,other.handle)])
        self.assertFalse(b.skeleton_opening([dk,sk,f],[e,other],25))


class OrbDepartureTests(unittest.TestCase):
    def test_every_live_health_level_can_leave_buy_and_deliver(self):
        for hp in (1,78,169,244,411):
            g,b,s,events=shopping.ShoppingTests().make();g.dk.hp=hp;g.dk.hp_max=850
            b.micro.pulling.add(g.dk.handle);b.micro.dk_recovering=g.dk.handle
            s.orb_tick(b,g.heroes,[],481,3)
            self.assertIn(('move','Udea',(0,0)),g.orders)
            self.assertNotIn(g.dk.handle,b.micro.pulling)
            g.dk.x=0;s.orb_tick(b,g.heroes,[],485,3);s.observe(g,486)
            self.assertIn('ocor',g.inventory(g.dk))
            g.dk.x=g.lich.x;s.orb_tick(b,g.heroes,[],490,3);s.observe(g,491)
            s.orb_tick(b,g.heroes,[],495,3)
            self.assertIn('ocor',g.inventory(g.lich));self.assertIsNone(s.orb)

    def test_low_health_does_not_bypass_actual_danger_or_blocked_route(self):
        for mode in ('attacker','route','enemy'):
            g,b,s,events=shopping.ShoppingTests().make();g.dk.hp=1
            foe=unit('nogr',99,g.dk.x);foe.owner=12 if mode=='attacker' else 1
            g.current_target=lambda u:g.dk if u is foe else None
            if mode=='attacker':b.micro.pulling.add(g.dk.handle)
            if mode=='route':b.creeping.safe_route=lambda *a:False
            s.orb_tick(b,g.heroes,[] if mode=='route' else [foe],481,3)
            self.assertFalse(g.orders);self.assertIsNone(s.orb)

    def test_full_tick_dispatches_injured_dk_before_lich_mercenary_pull(self):
        g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
        lich=unit('Ulic',100,-850,600);lich.owner=0;a.append(lich)
        for u in [dk,*a]:u.x=-850;u.hp=u.hp_max
        dk.hp=169;dk.hp_max=850
        home=g.my_buildings()[0];home.type='unp2';shop=unit('utom',101,-4900)
        own=[dk,*a,home,shop]
        for u in own:u.owner=0
        g.my_units=lambda:own;g.snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own)
        g.units=lambda side,codes:[u for u in own if u.type in codes]
        g.my_heroes=lambda:[dk,lich];g.inventory=lambda u:[None]*6
        g.unit=lambda h:next((u for u in own if u.handle==h),None)
        g.resources=lambda:dict(gold=500,lumber=300,food_used=30,food_cap=50)
        guard=unit('nfsh',501,0,450);guard.owner=12
        g.enemies=lambda:[];g.creeps=lambda:[guard];g.current_target=lambda u:None
        g.map=lambda:N(starts=[],walkable=lambda *p:True);g.visible=lambda *p:True
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        g.attack=lambda u,e,**kw:orders.append(('tag',u.handle,e.handle)) or True
        b.creeping.map_alias='AL';b.creeping.catalog=[dict(id='al-11',kind='mercenary',x=0,y=0)]
        b.creeping.active=b.creeping.catalog[0];b.creeping.safe_route=lambda *a:True
        b.emergency_portal=lambda *a:False;b.heal_allies=lambda *a:None
        b.combat_spells=lambda *a:None;b.shields.plan=lambda *a:{}
        b.micro.pulling.add(dk.handle);b.micro.plan=lambda *a,**kw:{dk.handle:(-850,0)}
        b.economy.ready=lambda g,c:[shop];b.economy.revival_pending=lambda g:False
        b.tick(forced=Action.CREEP)
        self.assertIn(('tag',lich.handle,guard.handle),orders)
        dk_moves=[o[2] for o in orders if o[0]=='move' and o[1]==dk.handle]
        self.assertTrue(dk_moves);self.assertTrue(all(p==(-4900,0) for p in dk_moves))
        self.assertIsNotNone(b.battle_shop.orb)


if __name__=='__main__':unittest.main()
