import unittest
from types import SimpleNamespace as N
from undead.loot import Loot
from undead.equipment import Equipment
import test_equipment as existing
from test_micro_loot import unit,dist

class LichOutputTests(unittest.TestCase):
    def game(self,code='tint',both=True,full=False):
        dk=unit('Udea',1,0);lich=unit('Ulic',2,700)
        heroes=[dk,lich] if both else [dk]
        inv={h.handle:(['rnec']*6 if full else [None]*6) for h in heroes}
        item=N(type=code,handle_lo=40,handle_hi=1,addr=40,x=30,y=0,life=75)
        picked=[];ground=[item];events=[]
        g=N(dist=dist,inventory=lambda h:inv[h.handle],items_on_ground=lambda:ground,
            path_distance=dist,pick_up=lambda h,it:picked.append(h.type) or True,
            unit=lambda handle:next((h for h in heroes if h.handle==handle),None),visible=lambda *p:True)
        loot=Loot({c:{'powerup':True,'effects':{'tome_int':n}} for c,n in [('tint',1),('tin2',2),('tpow',1)]},lambda e,**kw:events.append((e,kw)))
        return g,loot,heroes,picked,ground,events

    def test_int_books_go_to_farther_lich_even_with_full_inventory(self):
        for code in ('tint','tin2','tpow'):
            g,loot,heroes,picked,_,_=self.game(code,full=True)
            loot.tick(g,heroes,[],1)
            self.assertEqual(picked,['Ulic'])

    def test_before_lich_arrives_dk_consumes_and_effect_is_observed(self):
        g,loot,heroes,picked,ground,events=self.game(both=False)
        loot.tick(g,heroes,[],1);self.assertEqual(picked,['Udea'])
        ground.clear();heroes[0].mana_max+=15
        loot.tick(g,heroes,[],2)
        self.assertTrue(any(e=='powerup_confirmed' and k['hero']=='Udea' for e,k in events))

    def test_no_lich_beforehand_dk_priority_beats_closer_third_hero(self):
        g,loot,heroes,picked,_,_=self.game();heroes[1].type='Nbrn';heroes[1].x=30;heroes[0].x=700
        loot.tick(g,heroes,[],1)
        self.assertEqual(picked,['Udea'])

    def test_present_low_health_or_pulling_lich_keeps_book_for_later(self):
        for pulling in (False,True):
            g,loot,heroes,picked,_,_=self.game()
            if not pulling:heroes[1].hp=100
            army=[heroes[0]] if pulling else heroes
            loot.tick(g,army,[],1,all_heroes=heroes)
            self.assertFalse(picked)
            heroes[1].hp=500
            loot.tick(g,heroes,[],2,all_heroes=heroes)
            self.assertEqual(picked,['Ulic'])

    def test_unreachable_lich_does_not_let_dk_consume_reserved_book(self):
        g,loot,heroes,picked,_,_=self.game();g.path_distance=lambda a,b:None if a[0]==700 else dist(a,b)
        loot.tick(g,heroes,[],1)
        self.assertFalse(picked)

    def test_lich_temporary_absence_after_joining_preserves_book_until_return(self):
        g,loot,heroes,picked,ground,_=self.game();item=ground.pop()
        loot.tick(g,heroes,[],1)
        ground.append(item);loot.tick(g,[heroes[0]],[],2)
        self.assertFalse(picked)
        loot.tick(g,heroes,[],3)
        self.assertEqual(picked,['Ulic'])

    def test_gloves_int_agility_and_aura_equipment_transfer_without_losing_existing_items(self):
        for code in ('gcel','rin1','ciri','hcun','ckng','ajen','afac','ofro','oli2','oslo','ward'):
            with self.subTest(code=code):
                g,e,events=existing.EquipmentTests().setup_game();g.inv[g.dk.handle][0]=code
                g.inv[g.lich.handle][0]='rlif'
                self.assertTrue(e.tick(g,g.heroes,[],1,{}))
                existing.EquipmentTests().observed_transfer(g);e.tick(g,g.heroes,[],4,{})
                self.assertIn(code,g.inv[g.lich.handle]);self.assertIn('rlif',g.inv[g.lich.handle])
                self.assertNotIn(code,g.inv[g.dk.handle])

    def test_damage_equipment_prefers_farther_lich_but_strength_book_stays_dk(self):
        for code in ('gcel','rin1','ciri','hcun','belv','tstr'):
            g,loot,heroes,picked,_,_=self.game(code)
            loot.catalog['tstr']={'powerup':True,'effects':{'tome_str':1}}
            loot.tick(g,heroes,[],1)
            self.assertEqual(picked,['Udea' if code in {'tstr','belv'} else 'Ulic']) # Agility waits for Dark Ranger.

if __name__=='__main__':unittest.main()
