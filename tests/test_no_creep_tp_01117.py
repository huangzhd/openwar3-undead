import unittest
import test_tempo_01116 as actual
import test_expansion_aggro_0128 as aggro
from test_micro_loot import unit,dist
from undead.micro import Micro
from undead.policy import Action

class NoNeutralPortalTests(unittest.TestCase):
    def test_hard_ban_covers_every_action_even_when_blocked_critical_or_remote_enemy_visible(self):
        for action in Action:
            b,g,army,dk,foes,orders,events=actual.CreepEscapeTests().scene()
            b.action=action;dk.hp=20;b.micro.damage.rates[dk.handle]=300;g.path_distance=lambda *a:None
            distant=unit('Udea',99,10000);distant.owner=1;distant.target=None;g.enemies=lambda:[distant]
            self.assertFalse(b.emergency_portal(army,404.975));self.assertFalse(orders)
            self.assertTrue(any(e['event']=='neutral_portal_forbidden' for e in events))

    def test_half_health_dk_disengages_then_rejoins_camp_damage(self):
        dk=unit('Udea',1,0,300);fiend=unit('ucry',2,-100,550);creep=unit('nogr',3,100);creep.owner=12
        m=Micro(lambda *a,**k:None)
        moves=m.plan([dk,fiend],[creep],1,lambda e:dk.handle,dist,lambda *p:True,(-3000,0),lambda e:100,creeping=True)
        self.assertIn(dk.handle,moves);self.assertNotIn(fiend.handle,moves)
        dk.x=-700;creep.x=100
        moves=m.plan([dk,fiend],[creep],5,lambda e:fiend.handle,dist,lambda *p:True,(-3000,0),lambda e:100,creeping=True)
        self.assertNotIn(dk.handle,m.pulling)
        self.assertEqual(moves[dk.handle],(fiend.x,fiend.y))

    def test_no_skeleton_can_transfer_to_healthy_fiend_and_stop_friendly_attack(self):
        a,g,v,sk,e,targets,orders,events=aggro.CreepAggroTests().setup()
        v.type='Udea';v.is_hero=True;sk.type='ucry';sk.hp=sk.hp_max=550
        a.step(g,[v,sk],[e],0,True)
        self.assertEqual(orders[-1],('attack',v.handle,sk.handle,True))
        targets[e.handle]=sk;a.step(g,[v,sk],[e],.8,True)
        self.assertFalse(a.protected);self.assertEqual(orders[-1],('attack',v.handle,e.handle,False))

if __name__=='__main__':unittest.main()
