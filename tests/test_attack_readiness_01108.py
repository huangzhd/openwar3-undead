import unittest
import test_scout_regroup_01105 as regroup
from test_micro_loot import unit,dist
from undead.micro import Micro

class AttackReadinessTests(unittest.TestCase):
    def test_tier_three_and_orb_trip_exclude_hard_home_camp_but_keep_744(self):
        for courier in (False,True):
            b,g,army,_=regroup.HomeHalfTests().army();c=b.creeping
            c.home_only=True;c.tier=3 if not courier else 2;c.resupply_home=courier
            allowed={p['id'] for p in c.candidates(g,army,b.home,600)}
            self.assertNotIn('tr-2',allowed)
            self.assertIn('tr-7',allowed)

    def test_active_hard_camp_releases_to_regroup_when_dk_departs(self):
        b,g,army,_=regroup.HomeHalfTests().army();c=b.creeping;c.tier=3;c.resupply_home=True
        c.active=next(p for p in c.catalog if p['id']=='tr-2')
        # The camp is still occupied; a visibly empty camp must instead stay cleared.
        guard=unit('nogr',99,c.active['x']);guard.y=c.active['y'];g.creeps=lambda:[guard]
        c.cleared={p['id'] for p in c.catalog if c.pre_attack_safe(p)}
        goal,_=c.choose(g,army,(-4000,-4600),b.home,600)
        self.assertIsNone(goal);self.assertIn('tr-2',c.deferred)
        self.assertNotIn('tr-2',c.cleared)

    def test_depleted_force_does_not_open_another_744(self):
        b,g,army,_=regroup.HomeHalfTests().army();c=b.creeping;c.tier=2
        for u in army:u.hp=u.hp_max*.6
        self.assertNotIn('tr-7',{p['id'] for p in c.candidates(g,army,b.home,440)})

    def test_creeping_pulls_injured_spider_even_when_coil_is_ready(self):
        dk=unit('Udea',1,0,600);f=unit('ucry',2,100,230);e=unit('ntrt',3,200)
        m=Micro(lambda *a,**kw:None)
        result=m.plan([dk,f],[e],400,lambda _:f.handle,dist,lambda *p:True,(-2000,0),creeping=True,coil_ready=True)
        self.assertIn(f.handle,result)
        self.assertGreater(dist(result[f.handle],e),dist(f,e))
        f.hp=500
        result=m.plan([dk,f],[e],405,lambda _:None,dist,lambda *p:True,(-2000,0),creeping=True,coil_ready=True)
        self.assertNotIn(f.handle,result)
