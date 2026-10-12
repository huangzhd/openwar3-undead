import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.micro import Micro
from undead.controller import ground_attack_range

class FiendRecoveryTests(unittest.TestCase):
    def test_actual_seventy_hp_escape_does_not_rejoin_active_battle(self):
        frame=json.loads((Path(__file__).parent/'fixtures/az-fiendo-recovery-0185.json').read_text())
        def make(row):
            d=dict(row);d['handle']=tuple(d['handle']);d.setdefault('hp_max',d['hp']);d.setdefault('mana',0)
            d['is_hero']=d['type'][0].isupper();return N(**d)
        own=[make(u) for u in frame['army']];foes=[make(e) for e in frame['enemies']]
        fiend=next(u for u in own if u.handle[0]==16258)
        micro=Micro(lambda *a,**k:None);micro.pulling.add(fiend.handle);micro.hit[fiend.handle]=790
        moves=micro.plan(own,foes,frame['clock'],lambda e:tuple(e.target) if e.target else None,
                         dist,lambda *p:True,(3328,3072),lambda e:ground_attack_range(e.type),coil_ready=False)
        self.assertIn(fiend.handle,micro.pulling)
        self.assertEqual(moves[fiend.handle],(fiend.x,fiend.y))

    def test_available_mana_does_not_end_recovery_before_actual_heal(self):
        dk=unit('Udea',1,0,600);dk.mana=100
        f=unit('ucry',2,-800,70);enemy=unit('ogru',3,300)
        m=Micro(lambda *a,**k:None);m.pulling.add(f.handle)
        args=([dk,f],[enemy],10,lambda e:dk.handle,dist,lambda *p:True,(-3000,0))
        moves=m.plan(*args,coil_ready=True)
        self.assertIn(f.handle,moves)
        f.hp=450
        self.assertNotIn(f.handle,m.plan(*args,coil_ready=True))

    def test_cooldown_and_range_do_not_promise_impossible_rescue(self):
        for cooldown,dk_x in ((False,0),(True,-1000)):
            dk=unit('Udea',1,dk_x,600);dk.mana=100
            f=unit('ucry',2,100,70);enemy=unit('ogru',3,300)
            m=Micro(lambda *a,**k:None)
            moves=m.plan([dk,f],[enemy],10,lambda e:f.handle,dist,lambda *p:True,(-3000,0),coil_ready=cooldown)
            self.assertIn(f.handle,moves)
            self.assertGreater(dist(moves[f.handle],enemy),dist(f,enemy))

    def test_ended_local_battle_releases_recovery_without_recalling_army(self):
        dk=unit('Udea',1,0,600);dk.mana=0
        f=unit('ucry',2,-800,70);enemy=unit('ogru',3,3000)
        m=Micro(lambda *a,**k:None);m.pulling.add(f.handle)
        moves=m.plan([dk,f],[enemy],10,lambda e:None,dist,lambda *p:True,(-3000,0))
        self.assertFalse(moves);self.assertNotIn(f.handle,m.pulling)

if __name__=='__main__':unittest.main()
