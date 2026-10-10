import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller

class CoilTests(unittest.TestCase):
    def game(self,own):
        casts=[];attacks=[]
        g=N(units=lambda owner,codes:[u for u in own if u.type in codes],dist=dist,
            cooldown=lambda *a:0,cast=lambda u,spell,target:casts.append((spell,target.type)) or True,
            unit=lambda h:next((u for u in own if u.handle==h),None),is_building=lambda u:False,
            current_target=lambda u:None,attack=lambda u,target,**k:attacks.append(target.type) or True)
        return Controller(g,lambda *a,**k:None),casts,attacks

    def test_skeletons_never_consume_healing_even_when_most_damaged(self):
        dk=unit('Udea',1,0,600);fiend=unit('ucry',2,60,200)
        own=[dk,fiend,unit('uske',3,40,1),unit('uskm',4,50,1)]
        bot,casts,_=self.game(own)
        bot.heal_allies(own,10)
        self.assertEqual(casts,[('deathcoil','ucry')])
        fiend.hp=600;bot.cast_until.clear();bot.heal_checks.clear()
        bot.heal_allies(own,20)
        self.assertEqual(casts,[('deathcoil','ucry')])

    def test_critter_and_skeleton_still_get_normal_attacks_without_coil(self):
        for code in ('nshe','ncrb','npig','uske','uskm','nske','nska','nskf','nskg','Nbrn','ucry'):
            with self.subTest(code=code):
                dk=unit('Udea',1,0,600);target=unit(code,2,100,15)
                target.owner=15 if code in ('nshe','ncrb','npig') else 12
                bot,casts,attacks=self.game([dk])
                bot.fight([dk],[target],10)
                self.assertEqual(casts,[])
                self.assertEqual(attacks,[code])

    def test_living_enemy_and_hostile_creep_can_receive_damage_coil(self):
        for code in ('hfoo','nmrl'):
            dk=unit('Udea',1,0,600);target=unit(code,2,100,200)
            bot,casts,attacks=self.game([dk])
            bot.fight([dk],[target],10)
            self.assertEqual(casts,[('deathcoil',code)])
            self.assertEqual(attacks,[]) # protect DK casting animation

    def test_mechanical_building_and_unknown_are_not_damage_candidates(self):
        for code in ('hmtt','htow','xxxx'):
            dk=unit('Udea',1,0,600)
            bot,casts,_=self.game([dk])
            bot.fight([dk],[unit(code,2,100,200)],10)
            self.assertEqual(casts,[])
