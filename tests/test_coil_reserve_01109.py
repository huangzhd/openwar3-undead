import json
from pathlib import Path
import unittest
import test_nc_combo as nc
from test_micro_loot import unit


class CoilReserveTests(unittest.TestCase):
    def scene(self):
        b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=nc.NCTests().make()
        state=json.loads((Path(__file__).parent/'fixtures/tr-orc-coil-cooldown-01108.json').read_text(encoding='utf-8'))['state']
        ranger=unit('Nbrn',30,0)
        own.append(ranger)
        for u in own:
            row=next(x for x in state['army'] if x['type']==u.type)
            for key in ('x','y','hp','hp_max','mana'):setattr(u,key,row[key])
            u.owner=0;u.has_detail=True
        row=next(x for x in state['enemies'] if x['type']=='Otch')
        h.type='Otch';h.hp=row['hp'];h.x=row['x'];h.y=row['y']
        tower=unit('owtw',31,2112,295);tower.y=-320;tower.owner=1
        foes[:]=[h,tower]
        b.player_contact=foes
        b.g.current_target=lambda u:ranger if u is tower else None
        b.hero_pressure.choose=lambda *a:h
        b.focus_siege=lambda *a:False
        return b,d,l,h,ranger,tower,own,foes,orders,events

    def test_observed_pressure_holds_coil_then_heals_after_burst(self):
        b,d,l,h,r,t,own,foes,orders,events=self.scene()
        self.assertFalse(b.heal_candidates(d)) # 94 missing HP, below ordinary threshold.
        b.combat_spells(own,foes,691.43);b.fight(own,foes,691.43)
        self.assertFalse(any(s=='deathcoil' for _,s,_ in orders))
        self.assertTrue(any(s=='frostnova' for _,s,_ in orders))
        r.hp=r.hp_max*.5
        b.combat_spells(own,foes,692.305)
        self.assertIn(('Udea','deathcoil',r.handle),orders)

    def test_pressure_nc_is_also_held_for_exposed_hero(self):
        b,d,l,h,r,t,own,foes,orders,events=self.scene()
        calls=[]
        b.nc_combo.try_cast=lambda *a,**kw:calls.append(kw.get('pressure',False))
        b.combat_spells(own,foes,691.43)
        self.assertEqual(calls,[False]) # Lethal search stays active, pressure search is held.

    def test_no_reserve_for_safe_full_hero_or_neutral_stale_target(self):
        for case in ('full','out_of_range','neutral','untargeted','dk_too_far'):
            with self.subTest(case=case):
                b,d,l,h,r,t,own,foes,orders,events=self.scene()
                if case=='full':r.hp=r.hp_max
                if case=='out_of_range':t.x=4000
                if case=='neutral':t.owner=12
                if case=='untargeted':b.g.current_target=lambda u:None
                if case=='dk_too_far':r.x=0
                b.combat_spells(own,foes,691.43);b.fight(own,foes,691.43)
                self.assertIn(('Udea','deathcoil',h.handle),orders)

    def test_lethal_spell_still_allowed_with_noncritical_exposed_hero(self):
        b,d,l,h,r,t,own,foes,orders,events=self.scene();h.hp=50
        b.combat_spells(own,foes,691.43)
        self.assertTrue(any(target==h.handle and spell in ('deathcoil','frostnova') for _,spell,target in orders))

    def test_pressure_does_not_spend_last_heal_even_before_hero_is_hurt(self):
        b,d,l,h,r,t,own,foes,orders,events=self.scene();r.hp=r.hp_max;d.mana=133.3127
        b.combat_spells(own,foes,662.78);b.fight(own,foes,662.78)
        self.assertFalse(any(spell=='deathcoil' for _,spell,_ in orders))
        r.hp=r.hp_max*.5
        b.combat_spells(own,foes,667.775)
        self.assertIn(('Udea','deathcoil',r.handle),orders)
