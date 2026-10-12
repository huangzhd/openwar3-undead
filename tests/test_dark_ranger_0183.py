import unittest
from undead.micro import Micro
from test_micro_loot import unit,dist

class DarkRangerEscapeTests(unittest.TestCase):
    def scene(self):
        dk=unit('Udea',1,-2607,850);dk.y=-1317;dk.mana=190
        dark=unit('Nbrn',2,-2882,227);dark.y=-1964;dark.hp_max=550
        foe=unit('ugho',3,-2946,340);foe.y=-1926
        ally=unit('ucry',4,-2500,500);ally.y=-1450
        return Micro(lambda *a,**k:None),dk,dark,foe,ally

    def test_cooldown_does_not_cancel_injured_dark_ranger_escape(self):
        micro,dk,dark,foe,ally=self.scene()
        for now,hp in ((685.53,227),(686.78,210),(687.705,162)):
            dark.hp=hp
            moves=micro.plan([dk,dark,ally],[foe],now,lambda _:dark.handle,dist,lambda *p:True,(3328,3072),coil_ready=False)
            self.assertIn(dark.handle,moves)
            self.assertGreater(dist(moves[dark.handle],foe),dist(dark,foe))
        dark.hp=530
        moves=micro.plan([dk,dark,ally],[foe],695,lambda _:None,dist,lambda *p:True,(3328,3072),coil_ready=True)
        self.assertNotIn(dark.handle,moves)

    def test_ready_but_out_of_range_coil_cannot_hold_low_hero_in_place(self):
        micro,dk,dark,foe,ally=self.scene();dk.x=0
        moves=micro.plan([dk,dark,ally],[foe],685.53,lambda _:dark.handle,dist,lambda *p:True,(3328,3072),coil_ready=True)
        self.assertIn(dark.handle,moves)
        self.assertGreater(dist(moves[dark.handle],foe),dist(dark,foe))

    def test_available_nearby_coil_still_gets_its_rescue_window(self):
        micro,dk,dark,foe,ally=self.scene()
        moves=micro.plan([dk,dark,ally],[foe],685.53,lambda _:dark.handle,dist,lambda *p:True,(3328,3072),coil_ready=True)
        self.assertNotIn(dark.handle,moves)

if __name__=='__main__':unittest.main()
