import json
from pathlib import Path
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

from test_baseline import unit
import test_frontline_01216 as frontline
import test_coil_telemetry_01150 as coil
import test_wyvern_army_01212 as wyverns
from undead.controller import Controller
from undead.frontline import impale
from undead.game_view import SDKGame
from training import TrainingController


class TrainingFeedbackTests(unittest.TestCase):
    def test_live_clock_ahead_of_tick_does_not_erase_learned_impale(self):
        g,dk,cl,foe,own,t,orders,logs=coil.CoilTelemetryTests().scene()
        cl.type='Ucrl';cl.hp=cl.hp_max=975;cl.mana=300;cl.x=cl.y=0;foe.x=300;foe.y=0
        foe.visible_to=lambda player:player==0
        g._hero_spells().states.clear()
        cl.abilities=[N(code='AUim',level=1,cooldown=0,flags=16)]
        t[0]=3;g.observe_coil(own,t[0],lambda e,**kw:logs.append(dict(event=e,**kw)))
        cl.abilities=[N(code='AUts',level=2,cooldown=0,flags=528)]
        t[0]=4;g.observe_coil(own,t[0],g._hero_spells().log)
        b=Controller(g,lambda e,**kw:logs.append(dict(event=e,**kw)),2)
        t[0]=50.8
        self.assertEqual(g.hero_spell_level(cl,'AUim'),1)
        # The caller still has the tick's 50.48 snapshot after a fresh SDK read.
        g.observe_coil(own,50.48,g._hero_spells().log)
        self.assertEqual(g.hero_spell_level(cl,'AUim'),1)
        with patch.object(SDKGame,'cast',side_effect=lambda u,s,**kw:orders.append((s,kw)) or True):
            impale(b,own,[foe],50.48)
        self.assertEqual([s for s,_ in orders],['impale'])
        self.assertEqual(g._hero_spells().states[(cl.handle,'AUim')]['level'],1)

    def test_recorded_prebattle_impale_row_survives_passive_only_snapshot(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/crypt_lord_missing_224912.json').read_text())
        for kind in (Controller,TrainingController):
            g,dk,cl,foe,own,t,orders,logs=coil.CoilTelemetryTests().scene()
            cl.type='Ucrl';cl.hp=cl.hp_max=975;cl.mana=300;cl.x=cl.y=0;foe.x=300;foe.y=0
            foe.visible_to=lambda player:player==0
            for u in own:u.skill_points=0
            g._hero_spells().states.clear()
            b=kind(g,lambda e,**kw:logs.append(dict(event=e,**kw)),2)
            for row in fixture['rows']:
                t[0]=row['clock'];cl.abilities=[N(**a) for a in row['abilities']]
                b.skills(t[0])
            state=g._hero_spells().states[(cl.handle,'AUim')]
            self.assertEqual(state['level'],1);self.assertTrue(state['missing'])
            self.assertIsNone(g.cooldown(cl,'AUim'))
            self.assertFalse(any(a['code']=='AUim' for a in g.abilities(cl)))
            t[0]=51.12
            with patch.object(SDKGame,'cast',side_effect=lambda u,s,**kw:orders.append((s,kw)) or True):
                impale(b,own,[foe],t[0])
                impale(b,own,[foe],t[0]+.2)
            self.assertEqual(len(orders),1);self.assertEqual(orders[0][0],'impale')
            self.assertTrue(any(e['event']=='hero_spell_fallback_attempt' and e['ability']=='AUim' for e in logs))
            self.assertIsNone(g.cooldown(cl,'AUim'))

    def test_unknown_impale_is_not_inferred_from_passive_or_hero_level(self):
        g,dk,cl,foe,own,t,orders,logs=coil.CoilTelemetryTests().scene()
        cl.type='Ucrl';cl.level=5;cl.abilities=[N(code='AUts',level=2,cooldown=0,flags=16)]
        for u in own:u.skill_points=0
        g._hero_spells().states.clear();b=Controller(g,lambda *a,**kw:None)
        b.skills(t[0]);t[0]+=20
        with patch.object(SDKGame,'cast') as cast:impale(b,own,[foe],t[0])
        cast.assert_not_called();self.assertEqual(g.hero_spell_level(cl,'AUim'),0)

    def test_mixed_army_focuses_blade_then_wyverns_and_reacquires(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds=wyverns.WyvernArmyTests().scene(kind)
            abo=unit('uabo',81,owner=0);abo.hp=abo.hp_max=1000;own.append(abo)
            blade=unit('Obla',82,x=250);blade.hp=blade.hp_max=900;blade.has_detail=True;blade.mana=200
            foes.append(blade);b.hero_pressure.prefer_key_heroes=True
            for now,expected in ((10,{'Obla'}),(12,{'Obla'}),(14,{'owyv'}),(16,{'owyv'}),(18,{'Obla'})):
                if now==12:tc.x=2000
                if now==14:blade.x=2000
                if now==16:tc.x=300
                if now==18:blade.x=300
                target=b.hero_pressure.choose(g,own,foes,now)
                self.assertIsNotNone(target);self.assertIn(target.type,expected)
                self.assertEqual(b.hero_pressure.wyvern_priority,now in (14,16))
            orders.clear();b.combat_spells(own,foes,20)
            novas=[o for o in orders if o[0]=='cast' and o[2]=='frostnova']
            self.assertTrue(novas);self.assertIs(novas[0][3]['target'],blade)

    def test_pure_fiend_army_retains_seventh_level_wyvern_priority(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds=wyverns.WyvernArmyTests().scene()
        b.hero_pressure.prefer_key_heroes=True
        self.assertEqual(b.hero_pressure.choose(g,own,foes,10).type,'owyv')
        self.assertTrue(b.hero_pressure.wyvern_priority)

    def test_invulnerable_front_hero_does_not_block_air_clearup(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds=wyverns.WyvernArmyTests().scene()
        own.append(unit('uabo',81,owner=0));b.hero_pressure.prefer_key_heroes=True
        effects[tc.handle]=['Bvul']
        self.assertEqual(b.hero_pressure.choose(g,own,foes,10).type,'owyv')

    def test_prebattle_tanks_lich_dk_and_all_support_slots(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=frontline.FrontlineTests().scene(kind)
            for i in range(10,20):own.append(unit('ucry',100+i,owner=0))
            for i in range(3):own.append(unit('ubsp',200+i,owner=0))
            for i in range(2):own.append(unit('uobs',210+i,owner=0))
            b.enemy_main=(2000,0);b.prepare_battle(1,army=own,foes=[])
            lich=next(u for u in own if u.type=='Ulic');points=b.prep_points
            self.assertEqual(len([u for u in own if u.type=='ubsp']),len([u for u in own if u.type=='ubsp' and u.handle in points]))
            self.assertTrue(all(u.handle in points for u in own if u.type=='uobs'))
            self.assertAlmostEqual(points[dk.handle][1],0)
            self.assertGreater(points[abo.handle][0]-points[lich.handle][0],400)
            self.assertTrue(all(g.dist(points[dk.handle],points[u.handle])<=900 for u in own if u.type=='ucry'))
            self.assertLess(g.dist(points[dk.handle],points[lich.handle]),750)
            b.battle_started=True;b.battle_last_enemy=2;orders.clear()
            b.prepare_battle(2,army=own,foes=foes);self.assertFalse(orders)

    def destroyer_scene(self):
        b,g,own,foes,orders,events,effects,dk,cl,abo=frontline.FrontlineTests().scene()
        car=next(u for u in own if u.type=='ubsp');car.x=-900
        tc=next(e for e in foes if e.type=='Otch');tc.x=300
        head=foes[0];head.x=1200;foes[:]=[tc,head]
        b.hero_pressure.prefer_key_heroes=True
        return b,g,own,foes,orders,events,effects,car,tc,head

    def test_destroyer_returns_from_dispel_escape_to_safe_rear_output(self):
        b,g,own,foes,orders,events,effects,car,tc,head=self.destroyer_scene()
        b.destroyer.escape_after.add(car.handle);pulls={car.handle:(-1000,0)}
        b.rear_destroyers(own,foes,10,pulls,None)
        self.assertIn(car.handle,pulls)
        point=pulls[car.handle];self.assertGreater(point[0],car.x)
        self.assertLess(point[0],0);self.assertGreaterEqual(g.dist(point,head),690)
        self.assertLessEqual(g.dist(point,tc),450)
        car.x,car.y=point;pulls={};b.rear_destroyers(own,foes,12,pulls,None)
        b.attack_destroyers(own,foes,12,pulls)
        self.assertNotIn(car.handle,pulls)
        self.assertTrue(any(o[0]=='attack' and o[1]==car.handle and o[2]==tc.handle for o in orders))
        self.assertNotIn(car.handle,b.destroyer.escape_after)

    def test_destroyer_does_not_advance_through_aa_or_interrupt_dispel(self):
        for reason in ('aa','casting','pending','low'):
            b,g,own,foes,orders,events,effects,car,tc,head=self.destroyer_scene()
            if reason=='aa':head.x=tc.x
            if reason=='casting':b.cast_until[car.handle]=20
            if reason=='pending':b.destroyer.dispel[car.handle]=dict(started=9)
            if reason=='low':car.hp=car.hp_max*.4
            pulls={};b.rear_destroyers(own,foes,10,pulls,None)
            self.assertFalse(any(e=='battle_destroyer_output_position' for e,_ in events),reason)
            b.attack_destroyers(own,foes,10,pulls)
            self.assertFalse(any(o[0]=='attack' for o in orders),reason)

    def test_destroyer_can_fire_behind_tanks_when_ranged_medoid_is_far_back(self):
        b,g,own,foes,orders,events,effects,car,tc,head=self.destroyer_scene()
        for u in own:
            if u.type in {'uabo','Ucrl'}:u.x=300
        tc.x=550;head.x=1500
        pulls={};b.rear_destroyers(own,foes,10,pulls,None)
        self.assertIn(car.handle,pulls)
        p=pulls[car.handle]
        self.assertLessEqual(p[0],180);self.assertLessEqual(g.dist(p,tc),450)
        car.x,car.y=p;b.attack_destroyers(own,foes,12)
        self.assertTrue(any(o[0]=='attack' and o[1]==car.handle for o in orders))


if __name__=='__main__':unittest.main()
