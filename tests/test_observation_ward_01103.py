import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_stall_0154 as stall
from test_micro_loot import unit
from undead.coil import can_damage
from undead.targeting import in_weapon_range


class ObservationWardTests(unittest.TestCase):
    def frame(self):
        data=json.loads((Path(__file__).parent/'fixtures/observation-ward-stall-185535.json').read_text(encoding='utf-8'))
        def convert(row):
            row=dict(row);row['handle']=tuple(row['handle'])
            row['is_hero']=row['type'][0].isupper()
            return N(**row)
        return data,[convert(u) for u in data['own']],[convert(e) for e in data['enemies']]

    def test_recorded_ward_does_not_interrupt_contact_response_or_march(self):
        data,army,foes=self.frame();b,orders,_=stall.StallTests().bot()
        center=(2728,1861)
        b.player_contact=b.detect_player_contact(army,foes,center)
        self.assertFalse(b.respond_player_contact(army,data['clock']))
        self.assertEqual(b.active_foes(foes,data['clock']),[])
        b.battle_enemies=foes
        fought=[];b.fight=lambda *args:fought.append(args)
        b.go(army,tuple(data['goal']),data['clock'],attack=True)
        self.assertFalse(fought)
        self.assertTrue(any(o[0]=='attack_move' for o in orders))
        self.assertFalse(any(o[0]=='hold' for o in orders))

    def test_ward_alone_cannot_dispatch_attack_or_spell(self):
        data,army,foes=self.frame();b,orders,_=stall.StallTests().bot()
        b.fight(army,foes,data['clock'])
        self.assertFalse(orders)
        self.assertFalse(in_weapon_range(b.g,army[0],foes[0]))

    def test_friendly_ward_also_cannot_create_enemy_contact(self):
        data,army,foes=self.frame();b,_,_=stall.StallTests().bot()
        for e in foes:e.owner=0
        self.assertEqual(b.detect_player_contact(army,foes,(2728,1861)),[])

    def test_serpent_ward_and_real_troops_still_interrupt_march(self):
        for code in ('osp1','earc'):
            b,_,_=stall.StallTests().bot();ward=unit('nwad',10,200);ward.owner=1
            threat=unit(code,11,300);threat.owner=1
            army=[unit('ucry',1,0),unit('ucry',2,20)]
            self.assertEqual(b.detect_player_contact(army,[ward,threat],(0,0)),[threat])
            b.battle_enemies=[ward,threat];fought=[]
            b.fight=lambda a,e,n:fought.extend(e)
            b.go(army,(2000,0),1,attack=True)
            self.assertEqual(fought,[threat])
            self.assertTrue(in_weapon_range(b.g,army[0],threat))

    def test_coil_rejects_wards_but_still_damages_living_enemies(self):
        for code in ('nwad','osp1','osp2','osp3','ohwd'):
            self.assertFalse(can_damage(code),code)
        for code in ('earc','hfoo','ogru'):
            self.assertTrue(can_damage(code),code)
