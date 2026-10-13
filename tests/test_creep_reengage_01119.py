import unittest
from test_micro_loot import unit,dist
from undead.micro import Micro


class CreepReengageTests(unittest.TestCase):
    def scene(self,hp=300):
        dk=unit('Udea',1,0,hp);fiend=unit('ucry',2,-100,550)
        creep=unit('nogr',3,100);creep.owner=12
        return Micro(lambda *a,**k:None),dk,fiend,creep

    def plan(self,m,dk,fiend,creep,now,target):
        return m.plan([dk,fiend],[creep],now,lambda e:target,dist,lambda *p:True,
                      (-3000,0),lambda e:100,creeping=True)

    def test_sixty_percent_dk_keeps_ordinary_creep_damage(self):
        m,dk,fiend,creep=self.scene(360)
        self.assertNotIn(dk.handle,self.plan(m,dk,fiend,creep,1,dk.handle))

    def test_stale_creep_target_outside_weapon_range_does_not_hold_dk_forever(self):
        m,dk,fiend,creep=self.scene()
        self.assertIn(dk.handle,self.plan(m,dk,fiend,creep,1,dk.handle))
        dk.x=-500
        self.plan(m,dk,fiend,creep,5,dk.handle)
        self.assertNotIn(dk.handle,m.pulling)
        dk.x=-100
        self.assertNotIn(dk.handle,self.plan(m,dk,fiend,creep,6,fiend.handle))

    def test_dk_under_fire_or_critical_does_not_reengage(self):
        for hp in (300,120):
            m,dk,fiend,creep=self.scene(hp)
            self.plan(m,dk,fiend,creep,1,dk.handle)
            if hp==120:dk.x=-500
            self.plan(m,dk,fiend,creep,5,dk.handle if hp==300 else fiend.handle)
            self.assertIn(dk.handle,m.pulling)

    def test_sudden_damage_still_triggers_escape_above_half_health(self):
        m,dk,fiend,creep=self.scene(550)
        self.plan(m,dk,fiend,creep,1,dk.handle)
        dk.hp=360
        self.assertIn(dk.handle,self.plan(m,dk,fiend,creep,2,dk.handle))


if __name__=='__main__':unittest.main()
