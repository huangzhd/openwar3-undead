import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from test_army_recovery_0187 import Game
from undead.controller import Controller
from undead.policy import Action


class StatueTests(unittest.TestCase):
    def scene(self):
        g=Game();events=[];b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        b.home=g.home;b.creeping.safe_route=lambda *a:True
        return b,g,events

    def test_dual_roles_stable_under_damage_reordering_and_replacement(self):
        b,g,_=self.scene();r=b.army_recovery
        r.statues(b,10);first,second=g.statues
        r.active=True;r.heal_priority=True;g.army.reverse();r.statues(b,20)
        self.assertEqual(r.statue_modes[first.handle]['mode'],'life')
        self.assertEqual(r.statue_modes[second.handle]['mode'],'mana')
        self.assertEqual(len(g.orders),4)
        g.army.remove(first);replacement=unit('uobs',100,0);g.army.append(replacement)
        r.statues(b,30)
        self.assertEqual(r.statue_modes[replacement.handle]['mode'],'life')
        self.assertEqual(r.statue_modes[second.handle]['mode'],'mana')

    def test_safe_statues_hold_once_through_small_army_movements(self):
        b,g,_=self.scene();s=b.statue_support
        s.tick(b,g.army,[],10)
        for f in g.fiends:f.x+=100
        s.tick(b,g.army,[],12);s.tick(b,g.army,[],14)
        self.assertEqual(g.orders,[('hold',u.handle) for u in g.statues])

    def test_out_of_range_pair_rejoins_different_rear_points_then_stops(self):
        b,g,events=self.scene();s=b.statue_support
        for u in g.statues:u.x=-1100
        s.tick(b,g.army,[],10)
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual(len(moves),2);self.assertNotEqual(moves[0][2],moves[1][2])
        for _,h,p in moves:g.unit(h).x,g.unit(h).y=p
        g.orders.clear();s.tick(b,g.army,[],13);s.tick(b,g.army,[],16)
        self.assertEqual(g.orders,[('hold',u.handle) for u in g.statues])
        self.assertEqual(sum(e['event']=='statue_support_movement_observed' for e in events),2)

    def test_threatened_full_health_statue_pulls_but_safe_partner_stays(self):
        b,g,_=self.scene();s=b.statue_support
        first,second=g.statues;first.x=300;second.x=-350
        enemy=unit('hfoo',88,400);enemy.owner=1
        s.tick(b,g.army,[enemy],10)
        self.assertTrue(any(o[0]=='move' and o[1]==first.handle for o in g.orders))
        self.assertIn(('hold',second.handle),g.orders)

    def test_no_route_and_active_cast_do_not_create_move_orders(self):
        b,g,_=self.scene()
        for u in g.statues:u.x=-1100
        b.cast_until[g.statues[0].handle]=20;g.path_distance=lambda *a:None
        b.statue_support.tick(b,g.army,[],10);self.assertFalse(g.orders)

    def test_maximum_army_still_uses_two_statues(self):
        b,g,_=self.scene();b.economy.mass_army=True
        g.army.extend(unit('ucry',100+i,0) for i in range(15))
        self.assertEqual(b.economy.army_targets(g,1000)[1],2)


class FanTests(unittest.TestCase):
    def scene(self):
        g=Game();events=[];b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        b.home=g.home;b.action=Action.ATTACK;b.player_contact=[g.foes[0]]
        b.creeping.safe_route=lambda *a:True
        g.fiends=[unit('ucry',i,0) for i in range(101,107)]
        for i,u in enumerate(g.fiends):u.y=(i-3)*35;u.owner=0
        g.heroes[0].x=-120;g.heroes[1].x=-180
        g.army=g.fiends+g.heroes+g.statues
        target=unit('ucry',90,420);target.owner=1;g.foes=[target]
        return b,g,events

    def test_two_flanks_only_and_pending_moves_are_not_overwritten(self):
        b,g,events=self.scene();fan=b.battle_formation
        handles=fan.step(b,g.army,g.foes,g.foes[0],10)
        self.assertEqual(len(handles),2)
        points=[o[2] for o in g.orders if o[0]=='move']
        self.assertTrue(points[0][1]*points[1][1]<0)
        self.assertFalse(handles & {u.handle for u in g.heroes+g.statues})
        self.assertEqual(fan.step(b,g.army,g.foes,g.foes[0],10.5),handles)
        self.assertEqual(len(g.orders),2)
        for _,h,p in g.orders:g.unit(h).x,g.unit(h).y=p
        fan.step(b,g.army,g.foes,g.foes[0],11)
        self.assertEqual(sum(e['event']=='battle_fan_movement_observed' for e in events),2)

    def test_casting_pulling_shopping_and_blocked_terrain_are_protected(self):
        b,g,_=self.scene()
        b.cast_until[g.fiends[0].handle]=20;b.micro.pulling.add(g.fiends[1].handle)
        b.shopping.add(g.fiends[2].handle)
        moved=b.battle_formation.step(b,g.army,g.foes,g.foes[0],10)
        self.assertFalse(moved & {u.handle for u in g.fiends[:3]})
        b,g,_=self.scene();g.path_distance=lambda *a:None
        self.assertFalse(b.battle_formation.step(b,g.army,g.foes,g.foes[0],10));self.assertFalse(g.orders)

    def test_controller_moves_only_two_while_other_fiends_keep_attacking(self):
        from test_siege_0147 import SiegeTests
        b,a,f,cmd,cur,ids,p,ev=SiegeTests().game()
        a.extend(unit('ucry',100+i,0) for i in range(4))
        for i,u in enumerate(a):u.owner=0;u.mana=0;u.y=(i-3)*30
        b.g.map=lambda:N(walkable=lambda *args:True)
        b.g.walk_path=lambda start,end:[start,end]
        b.creeping.safe_route=lambda *args:True
        target=SiegeTests().enemy('ucry',90,420);f.append(target);b.player_contact=f
        b.fight(a,f,10)
        moving={o[1] for o in cmd if o[0]=='move'}
        attacking={o[1] for o in cmd if o[0]=='attack'}
        self.assertEqual(len(moving),2);self.assertFalse(moving & attacking)
        self.assertGreaterEqual(len(attacking),3)
        cmd.clear();target.owner=12;b.player_contact=[]
        b.fight(a,f,11)
        self.assertFalse(any(o[0]=='move' for o in cmd))

    def test_actual_crowded_dk_fixture_never_moves_dk_or_statue(self):
        b,g,_=self.scene()
        data=json.loads((Path(__file__).parent/'fixtures/tm-fan-blockage-01122.json').read_text(encoding='utf-8'))['sample']
        convert=lambda row:N(**{**row,'handle':tuple(row['handle'])})
        g.army=[convert(r) for r in data['own']];g.heroes=[u for u in g.army if u.is_hero]
        g.foes=[convert(r) for r in data['enemies'] if r['hp']>0]
        dk=next(u for u in g.heroes if u.type=='Udea')
        b.micro.pulling.add(dk.handle)
        target=min(g.foes,key=lambda e:dist(e,dk))
        b.battle_formation.step(b,g.army,g.foes,target,790.455)
        self.assertTrue(all(g.unit(o[1]).type in {'ucry','Ulic','Nbrn','Nngs'} for o in g.orders))
        self.assertLessEqual(len(g.orders),2)


if __name__=='__main__':unittest.main()
