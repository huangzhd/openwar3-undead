import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.hazards import LightningShield,SAFE_GAP
from undead.controller import Controller


class ShieldTests(unittest.TestCase):
    def test_actual_buff_moves_carrier_away_and_restores_after_expiry(self):
        carrier=unit('ucry',1,0);ally=unit('Udea',2,80);foe=unit('hfoo',3,400)
        active=[True];events=[]
        hazard=LightningShield(lambda e,**k:events.append(e))
        buffs=lambda u:['Blsh'] if active[0] and u is carrier else []
        moves=hazard.plan([carrier,ally],[foe],1,buffs,lambda *p:True,dist)
        p=moves[carrier.handle]
        self.assertGreaterEqual(dist(p,ally),SAFE_GAP)
        self.assertGreaterEqual(dist(p,foe),dist(carrier,foe)-50)
        self.assertNotIn('lightning_shield_separated',events)
        carrier.x,carrier.y=p
        self.assertIn(carrier.handle,hazard.plan([carrier,ally],[foe],2,buffs,lambda *p:True,dist))
        self.assertIn('lightning_shield_separated',events)
        active[0]=False
        self.assertFalse(hazard.plan([carrier,ally],[foe],3,buffs,lambda *p:True,dist))

    def test_blocked_route_does_not_fabricate_separation(self):
        carrier=unit('uske',1,0);ally=unit('ucry',2,40);events=[]
        h=LightningShield(lambda e,**k:events.append(e))
        moves=h.plan([carrier,ally],[],1,lambda u:['Blsh'] if u is carrier else [],lambda *p:True,lambda *p:None)
        self.assertEqual(moves[carrier.handle],(0,0))
        self.assertIn('lightning_shield_blocked',events)
        self.assertNotIn('lightning_shield_separated',events)

    def test_fight_and_formation_cannot_pull_isolated_carrier_back(self):
        carrier=unit('ucry',1,0);dk=unit('Udea',2,50);dk.mana=0;foe=unit('hfoo',3,250)
        attacked=[];moved=[]
        g=N(dist=dist,is_building=lambda _:False,current_target=lambda _:None,
            attack=lambda u,*a,**k:attacked.append(u.handle) or True,
            attack_move=lambda u,*a:moved.append(u.handle) or True,
            move=lambda u,*a:moved.append(u.handle) or True)
        b=Controller(g,lambda *a,**k:None);b.shield_moves={carrier.handle:(-400,0)}
        b.fight([carrier,dk],[foe],1)
        b.go([carrier,dk],(500,0),1,attack=True)
        self.assertNotIn(carrier.handle,attacked+moved)
        self.assertIn(dk.handle,attacked)
        b.shield_moves.clear();b.fight([carrier,dk],[foe],3)
        self.assertIn(carrier.handle,attacked)
