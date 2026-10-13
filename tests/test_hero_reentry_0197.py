import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.micro import Micro
from undead.controller import ground_attack_range
from test_micro_loot import unit,dist

class HeroReentryTests(unittest.TestCase):
    def test_archived_244_hp_lich_stays_protected_after_damage_pause(self):
        f=json.loads((Path(__file__).parent/'fixtures/th-human-hero-reentry-0196.json').read_text(encoding='utf-8'))
        def make(x):
            d=dict(x);d['handle']=tuple(d['handle']);d.setdefault('hp_max',max(1,d['hp']));d.setdefault('mana',0)
            d['is_hero']=d['type'][0].isupper();return N(**d)
        army=list(map(make,f['army']));foes=list(map(make,f['enemies']))
        lich=next(u for u in army if u.type=='Ulic');m=Micro(lambda *a,**k:None)
        m.pulling.add(lich.handle);m.hit[lich.handle]=710
        moves=m.plan(army,foes,f['clock'],lambda e:tuple(e.target) if e.target else None,
                     dist,lambda *p:True,(-3904,2880),lambda e:ground_attack_range(e.type),coil_ready=False)
        self.assertIn(lich.handle,moves)
        self.assertEqual(moves[lich.handle],(lich.x,lich.y))
        self.assertIn(lich.handle,m.pulling)

    def scenario(self,code):
        dk=unit('Udea',1,0,600);dk.mana=0
        hero=unit(code,2,-800,200);fiend=unit('ucry',3,0,550);foe=unit('ogru',4,300,700)
        m=Micro(lambda *a,**k:None);m.pulling.add(hero.handle);m.hit[hero.handle]=1
        def step(t=10):return m.plan([dk,hero,fiend],[foe],t,lambda _:fiend.handle,
            dist,lambda *p:True,(-3000,0),lambda _:100)
        return m,dk,hero,fiend,foe,step

    def test_support_heroes_wait_for_health_not_healer_mana(self):
        for code in ('Ulic','Nbrn','Nngs'):
            with self.subTest(code=code):
                m,dk,h,f,e,step=self.scenario(code)
                self.assertEqual(step()[h.handle],(h.x,h.y))
                dk.mana=200
                self.assertIn(h.handle,step(11))
                h.hp=430
                self.assertNotIn(h.handle,step(12))
                self.assertNotIn(h.handle,m.pulling)

    def test_ended_battle_releases_protection_even_if_still_wounded(self):
        m,dk,h,f,e,step=self.scenario('Ulic')
        self.assertIn(h.handle,step())
        e.x=3000
        self.assertNotIn(h.handle,step(11))

    def test_healing_hero_does_not_recall_healthy_fiends_or_dk(self):
        m,dk,h,f,e,step=self.scenario('Nbrn')
        self.assertEqual(set(step()),{h.handle})

    def test_returned_fire_resumes_escape_instead_of_holding_under_attack(self):
        m,dk,h,f,e,step=self.scenario('Ulic');step()
        e.x=-650
        moves=step(11)
        self.assertGreater(dist(moves[h.handle],e),dist(h,e))

if __name__=='__main__':unittest.main()
