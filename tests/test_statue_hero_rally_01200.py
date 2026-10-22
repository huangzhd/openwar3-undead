import unittest
from unittest.mock import Mock
import test_support_fan_01122 as support
import test_lich_safety_panel_01198 as backline
from test_micro_loot import unit,dist
from training import TrainingController
from undead.controller import Controller,ground_attack_range
from undead.micro import Micro
from undead.policy import Action
from undead.retreat import statue_rally_rank


class RescueStatueTests(unittest.TestCase):
    def scene(self,kind=Controller):
        old,g,events=support.StatueTests().scene()
        b=kind(g,old.log,2);b.home=g.home;b.creeping.safe_route=lambda *a:True
        b.action=Action.ATTACK
        hero=g.heroes[1];hero.x=-900;hero.hp=270
        b.backline_guards.add(hero.handle)
        b.army_recovery.statue_modes={g.statues[0].handle:dict(mode='life'),g.statues[1].handle:dict(mode='mana')}
        return b,g,hero,events

    def test_both_statues_follow_retreating_hero_beyond_old_350_leash_in_both_modes(self):
        results=[]
        for kind in (Controller,TrainingController):
            b,g,hero,events=self.scene(kind)
            b.statue_support.tick(b,g.army,g.foes,10,{hero.handle})
            moves=[o for o in g.orders if o[0]=='move']
            self.assertEqual(len(moves),2)
            self.assertNotEqual(moves[0][2],moves[1][2])
            for _,h,p in moves:
                self.assertLessEqual(dist(p,hero),220)
                self.assertGreater(dist(p,g.fiends[0]),350)
                self.assertIsNotNone(b.army_recovery.safe_path(b,(g.unit(h).x,g.unit(h).y),p,g.foes,combat=True))
            results.append(moves)
        self.assertEqual(*results)

    def test_arrival_prioritizes_life_even_for_mana_car_and_logs_real_buff(self):
        b,g,hero,events=self.scene();s=b.statue_support
        s.tick(b,g.army,g.foes,10,{hero.handle})
        for op,h,p in list(g.orders):g.unit(h).x,g.unit(h).y=p
        g.orders.clear();s.tick(b,g.army,g.foes,13,{hero.handle})
        self.assertEqual(g.orders,[('cast',u.handle,'replenishlife') for u in g.statues])
        self.assertTrue(all(hero.handle in p['before'] for p in s.supply_checks.values()))
        g.buffs=lambda u:['Brpl'] if u.handle==hero.handle else []
        g.orders.clear();s.tick(b,g.army,g.foes,14.3,{hero.handle})
        self.assertTrue(any(e['event']=='statue_supply_recipients_observed' and any(r['handle']==hero.handle for r in e['recipients']) for e in events))
        self.assertFalse(g.orders)

    def test_follow_replans_when_hero_moves_then_releases_after_recovery(self):
        b,g,hero,events=self.scene();s=b.statue_support
        s.tick(b,g.army,g.foes,10)
        hero.x=-1200;g.orders.clear();s.tick(b,g.army,g.foes,12)
        self.assertTrue(all(dist(o[2],hero)<=220 for o in g.orders if o[0]=='move'))
        b.backline_guards.clear();hero.hp=360;s.tick(b,g.army,g.foes,14)
        self.assertIn(hero.handle,s.rescuing)
        hero.hp=390;s.tick(b,g.army,g.foes,16)
        self.assertNotIn(hero.handle,s.rescuing)

    def test_no_safe_route_does_not_cross_enemy_to_rescue(self):
        b,g,hero,events=self.scene()
        enemy=unit('otbk',91,-400);enemy.owner=1
        b.statue_support.tick(b,g.army,[enemy],10)
        self.assertFalse(any(e['event']=='statue_hero_rescue_move' for e in events))
        self.assertFalse(b.statue_support.rescue_handled)

    def test_protected_controlled_empty_mana_and_unknown_spell_are_not_sent(self):
        for mode in ('protected','cast','controlled','empty','unknown'):
            b,g,hero,events=self.scene();blocked={hero.handle}
            for car in g.statues:
                if mode=='protected':blocked.add(car.handle)
                if mode=='cast':b.cast_until[car.handle]=20
                if mode=='empty':car.mana=0
                if mode=='controlled':car.has_detail=True
            if mode=='controlled':g.buffs=lambda u:['BOhx'] if u.type=='uobs' else []
            if mode=='unknown':g.cooldown=lambda *a:None
            b.statue_support.tick(b,g.army,g.foes,10,blocked)
            self.assertFalse(any(e['event']=='statue_hero_rescue_move' for e in events),mode)
            self.assertFalse(any(o[0]=='cast' for o in g.orders),mode)

    def test_low_nonretreating_or_far_hero_does_not_take_over_pair(self):
        for mode in ('not_retreating','far','healthy'):
            b,g,hero,events=self.scene()
            if mode=='not_retreating':b.backline_guards.clear()
            if mode=='far':hero.x=-4000
            if mode=='healthy':hero.hp=600
            b.statue_support.tick(b,g.army,g.foes,10)
            self.assertFalse(any(e['event']=='statue_hero_rescue_move' for e in events),mode)

    def test_collective_retreat_does_not_overwrite_statue_rescue(self):
        b,g,hero,events=self.scene();b.action=Action.RETREAT
        b.emergency_portal=lambda *a:False;b.go=Mock()
        b.collective_retreat(g.army,10)
        self.assertEqual(len(b.statue_support.rescue_handled),2)
        self.assertFalse(any(u.type=='uobs' for u in b.go.call_args.args[0]))


class HeroRallyTests(unittest.TestCase):
    def test_diagram_prefers_overlap_behind_pair_over_an_outward_flank(self):
        cars=[unit('uobs',1,-300),unit('uobs',2,-300)];cars[0].y=-100;cars[1].y=100
        enemies=[unit('ogru',3,200)]
        self.assertLess(statue_rally_rank((-440,0),cars,enemies),statue_rally_rank((-300,200),cars,enemies))
        self.assertLess(statue_rally_rank((-440,0),cars,enemies),statue_rally_rank((-160,0),cars,enemies))

    def test_lich_dark_and_dk_retreat_into_safe_statue_overlap(self):
        for kind in (Controller,TrainingController):
            for code in ('Ulic','Nbrn','Udea'):
                b,g,own,foes,orders,events,effects,lich,dk=backline.LichSafetyTests().scene(kind)
                own[:]=[u for u in own if u.type!='uobs']
                cars=[unit('uobs',50,-350),unit('uobs',51,-350)];cars[0].y=-100;cars[1].y=100
                own.extend(cars)
                hero=next(u for u in own if u.type==code);hero.hp_max=600;hero.hp=270;hero.x=0;hero.y=0
                if code=='Udea':
                    pulls=b.micro.plan(own,foes,10,lambda _:hero.handle,dist,lambda *a:True,(-2000,0),
                                       lambda e:ground_attack_range(e.type),aggressive_battle=True)
                else:
                    pulls={};b.rear_backline(own,foes,10,pulls)
                self.assertIn(hero.handle,pulls)
                point=pulls[hero.handle]
                self.assertLessEqual(point[0],-350,(kind,code,point))
                self.assertEqual(sum(dist(point,car)<=220 for car in cars),2,(kind,code,point))
                self.assertTrue(all(dist(point,e)-ground_attack_range(e.type)>=140 for e in foes))

    def test_statues_in_enemy_fire_do_not_attract_retreating_heroes(self):
        b,g,own,foes,orders,events,effects,lich,dk=backline.LichSafetyTests().scene()
        own[:]=[u for u in own if u.type!='uobs'];own.append(unit('uobs',50,150))
        pulls={};b.rear_backline(own,foes,10,pulls)
        self.assertLess(pulls[lich.handle][0],lich.x)
        self.assertGreater(dist(pulls[lich.handle],own[-1]),dist(lich,own[-1]))


if __name__=='__main__':unittest.main()
