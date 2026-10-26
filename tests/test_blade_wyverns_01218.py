import unittest
from test_baseline import unit
import test_wyvern_army_01212 as wyverns
from undead.controller import Controller
from training import TrainingController
from undead.policy import Action


class BladeWyvernTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc,birds=wyverns.WyvernArmyTests().scene(kind)
        tank=unit('uabo',81,owner=0);tank.hp=tank.hp_max=1000;own.append(tank)
        blade=unit('Obla',82,owner=1,x=250);blade.hp=blade.hp_max=900;blade.mana=200;blade.has_detail=True;foes.append(blade)
        car=unit('ubsp',83,owner=0,x=-140);car.hp=car.hp_max=900;own.append(car)
        b.hero_pressure.prefer_key_heroes=True
        return b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car

    def test_blade_only_damage_tc_silence_and_hero_healing(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene(kind)
            tc.hp=1
            lich=next(u for u in own if u.type=='Ulic');lich.hp=lich.hp_max*.4
            b.combat_spells(own,foes,10)
            spells=[o for o in orders if o[0]=='cast']
            self.assertTrue(any(o[2]=='silence' and o[3]['target'] is tc for o in spells))
            self.assertTrue(any(o[2]=='frostnova' and o[3]['target'] is blade for o in spells))
            self.assertTrue(any(o[2]=='deathcoil' and o[3]['target'] is lich for o in spells))
            self.assertFalse(any(o[2] in {'deathcoil','frostnova'} and o[3].get('target') is tc for o in spells))
            orders.clear();b.focus_ranged(own,foes,12)
            shots=[o for o in orders if o[0]=='attack']
            self.assertTrue(shots);self.assertEqual({o[2] for o in shots},{blade.handle})
            self.assertTrue(b.reserve_coil_for_hero(dk,12))

    def test_unavailable_blade_leaves_low_tc_and_focuses_webbed_fly(self):
        for reason in ('hidden','far','invulnerable','dead'):
            b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
            self.assertIs(b.hero_pressure.choose(g,own,foes,9),blade)
            tc.hp=1
            if reason=='hidden':foes.remove(blade)
            if reason=='far':blade.x=2200
            if reason=='invulnerable':effects[blade.handle]=['Bvul']
            if reason=='dead':blade.hp=0;blade.alive=False
            self.assertIs(b.hero_pressure.choose(g,own,foes,10),birds[1],reason)
            b.combat_spells(own,foes,10);b.focus_ranged(own,foes,12)
            self.assertFalse(any(o[0]=='attack' and o[2]==tc.handle for o in orders))
            self.assertFalse(any(o[0]=='cast' and o[2]=='frostnova' and o[3].get('target') is tc for o in orders))

    def test_destroyer_fires_fly_after_dispel_without_retreating_first(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
        b.hero_pressure.select_strategy(g,own,foes,10)
        b.destroyer.escape_after.add(car.handle);b.last[('battle_destroyer_attack',car.handle)]=9.9
        car.x=0 # Inside the old AA safety margin: no compulsory retreat.
        pulls={car.handle:(-900,0)};b.micro.pulling.add(car.handle)
        blocked=b.rear_destroyers(own,foes,10,pulls,None)
        b.attack_destroyers(own,foes,10,blocked|set(pulls))
        self.assertNotIn(car.handle,pulls)
        self.assertTrue(any(o[0]=='attack' and o[1]==car.handle and o[2]==birds[1].handle for o in orders))
        self.assertFalse(any(o[0]=='attack' and o[1]==car.handle and o[2]==blade.handle for o in orders))

    def test_destroyer_returns_to_fly_range_instead_of_stopping_for_tc(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
        car.x=-900;pulls={};b.rear_destroyers(own,foes,10,pulls,None)
        self.assertIn(car.handle,pulls)
        car.x,car.y=pulls[car.handle];pulls={}
        blocked=b.rear_destroyers(own,foes,12,pulls,None)
        b.attack_destroyers(own,foes,12,blocked|set(pulls))
        self.assertTrue(any(o[0]=='attack' and o[1]==car.handle and o[2] in {v.handle for v in birds} for o in orders))

    def test_destroyer_protection_wins_over_immediate_output(self):
        for reason in ('focused','headhunter_focus','low','pending','cast','retreat'):
            b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
            if reason=='focused':g.current_target=lambda u:car if u.type=='owyv' else None
            if reason=='headhunter_focus':
                foes.extend(unit('ohun',90+i,owner=1,x=300) for i in range(2))
                g.current_target=lambda u:car if u.type=='ohun' else None
            if reason=='low':car.hp=car.hp_max*.4
            if reason=='pending':b.destroyer.dispel[car.handle]=dict(started=9)
            if reason=='cast':b.cast_until[car.handle]=20
            if reason=='retreat':b.action=Action.RETREAT
            pulls={};blocked=b.rear_destroyers(own,foes,10,pulls,None)
            b.attack_destroyers(own,foes,10,blocked|set(pulls))
            self.assertFalse(any(o[0]=='attack' and o[1]==car.handle for o in orders),reason)

    def test_destroyer_resumes_output_after_focus_released(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
        car.x=0;g.current_target=lambda u:car if u.type=='owyv' else None
        pulls={};b.rear_destroyers(own,foes,10,pulls,None)
        self.assertIn(car.handle,pulls)
        g.current_target=lambda _:None
        b.rear_destroyers(own,foes,12,pulls,None);b.attack_destroyers(own,foes,12,pulls)
        self.assertNotIn(car.handle,pulls)
        self.assertTrue(any(o[0]=='attack' and o[1]==car.handle for o in orders))

    def test_tank_loss_does_not_switch_back_to_tc_while_birds_remain(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds,blade,car=self.scene()
        b.hero_pressure.select_strategy(g,own,foes,10)
        own[:]=[u for u in own if u.type!='uabo'];foes.remove(blade)
        self.assertIs(b.hero_pressure.choose(g,own,foes,12),birds[1])


if __name__=='__main__':unittest.main()
