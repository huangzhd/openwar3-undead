import unittest
import test_safe_siege_0196 as safe
from test_micro_loot import dist
from undead.siege import fire_clearance,safe_route

class ArtilleryApproachTests(unittest.TestCase):
    def make(self):
        helper=safe.SafeSiegeTests();b,a,f,cmd,cur,ids,p,ev=helper.setup_battle()
        tower=helper.enemy('hgtw',20,1000);tower.y=1000
        cat=helper.enemy('ocat',21,900);f.extend([tower,cat])
        return b,a,f,cmd,cur,ev,tower,cat

    def test_contact_advances_without_subsequent_tower_hold(self):
        b,a,f,cmd,cur,ev,tower,cat=self.make();b.player_contact=[cat]
        b.respond_player_contact(a,10)
        actions=[(op,p) for op,h,p in cmd if h==a[2].handle]
        self.assertEqual(actions[-1][0],'move')
        self.assertLess(dist(actions[-1][1],cat),dist(a[2],cat))

    def test_two_towers_do_not_veto_attack_advance(self):
        b,a,f,cmd,cur,ev,tower,cat=self.make();tower.x=700;tower.y=0;cat.x=1300
        f.append(safe.SafeSiegeTests().enemy('hgtw',23,1050));b.player_contact=[cat]
        b.respond_player_contact(a,10)
        self.assertIs(cur[a[2].handle],tower) # nearer tower becomes the attack objective
        self.assertFalse(any(op=='hold' for op,h,p in cmd))

    def test_in_range_artillery_can_be_attacked_under_tower(self):
        b,a,f,cmd,cur,ev,tower,cat=self.make();tower.x=500;tower.y=0;cat.x=450
        b.fight(a,f,10)
        self.assertIs(cur[a[2].handle],cat)

    def test_casting_and_emergency_pull_preempt_advance(self):
        for mode in ('casting','pulling'):
            b,a,f,cmd,cur,ev,tower,cat=self.make();b.player_contact=[cat];u=a[2]
            if mode=='casting':b.cast_until[u.handle]=20
            else:b.micro.pulling.add(u.handle)
            b.respond_player_contact(a,10)
            self.assertFalse(any(h==u.handle for op,h,p in cmd))
