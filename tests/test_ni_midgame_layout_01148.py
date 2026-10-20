import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_ni_route_01142 as ni
import test_creep_tempo_01101 as tempo
import test_foundation_owner_01124 as foundation
from test_micro_loot import unit
from undead.home_layout import clear_of_buildings, ENVELOPES


class NIMidgameTests(unittest.TestCase):
    def test_real_mine_clear_goes_to_544_without_statue_or_orb(self):
        f=json.loads((Path(__file__).parent/'fixtures/ni_200528_tier_two_wait.json').read_text(encoding='utf-8'))
        b,g,a,c=ni.NIRouteTests().scene()
        self.assertEqual(f['summary']['situation']['tier'],2)
        self.assertFalse(f['summary']['situation']['orb'])
        c.tier=2;c.cleared.update(c.ni_opening(b.home)[:-1])
        c.active=next(p for p in c.catalog if p['id']==f['mine_clear']['camp'])
        g.creeps=lambda:[];g.visible=lambda *p:True
        moves=[];b.go=lambda army,point,now,attack=False:moves.append(point)
        b.creep(a,tuple(f['mine_clear']['point']),f['mine_clear']['clock'])
        self.assertEqual(c.active['id'],'ni-0')
        self.assertIn((c.active['x'],c.active['y']),moves)
        self.assertNotIn((b.home.x,b.home.y),moves)

    def test_both_spawns_finish_544_then_lab_without_orb_or_statue(self):
        for north,route in ((False,['ni-0','ni-3']),(True,['ni-17','ni-14'])):
            b,g,a,c=ni.NIRouteTests().scene(north);c.tier=2
            c.cleared.update(c.ni_opening(b.home));center=(b.home.x,b.home.y)
            for k in route:
                point,_=c.choose(g,a,center,b.home,400)
                self.assertEqual(c.active['id'],k)
                foe=unit('nomg',999,point[0],2500);foe.y=point[1];foe.owner=12
                g.creeps=lambda:[foe];g.visible=lambda *p:True
                self.assertEqual(c.choose(g,a[:1],point,b.home,650)[0],point)
                self.assertNotIn(k,c.deferred)
                g.creeps=lambda:[]
                self.assertTrue(c.observe_clear(g,point,651,[]));center=point
            self.assertIsNone(c.ni_route_stage(b.home))
            c.tier=3;c.prepare_ni_center(g,a,b.home,700,True,False)
            self.assertEqual(c.ni_route_stage(b.home),'ni-7')

    def test_tier_one_does_not_open_midgame_and_orb_does_not_abandon_lab(self):
        b,g,a,c=ni.NIRouteTests().scene();c.cleared.update(c.ni_opening(b.home))
        self.assertIsNone(c.ni_route_stage(b.home))
        c.tier=2;c.cleared.add('ni-0')
        point,_=c.choose(g,a,(b.home.x,b.home.y),b.home,400)
        foe=unit('nfpt',999,point[0],900);foe.y=point[1];foe.owner=12;g.creeps=lambda:[foe]
        c.tier=3;c.prepare_ni_center(g,a,b.home,410,True,False)
        self.assertEqual(c.choose(g,a,point,b.home,410)[0],point)
        self.assertEqual(c.active['id'],'ni-3')

    def test_generic_items_cannot_race_active_ni_rod_purchase(self):
        b,g,dk,bag,buys=tempo.RodTempoTests().make();dk.x=0
        b.rod_acquisitions={'Udea':1};b.ni_rod_stop.mission={'started':229.455}
        b.items(241.325,1)
        self.assertFalse(buys);self.assertIsNone(b.shop_goal)
        b.ni_rod_stop.mission=None;b.items(245,1)
        self.assertEqual(buys,['rnec'])


class OpeningLayoutTests(unittest.TestCase):
    def scene(self):
        l,g,h,w,bs,ws,orders,ev,order=foundation.FoundationTests().scene()
        h.x=-2752;h.y=-3328
        for code,x,y in [('usep',-2752,-2816),('uaod',-3296,-3360),('uzig',-2784,-3872)]:
            b=unit(code,len(bs)+10,x);b.y=y;bs.append(b)
        g.can_afford=lambda code:True
        return l,g,h,w,bs,orders,ev,order

    def test_shop_right_of_crypt_and_graveyard_at_old_shop_slot(self):
        l,g,h,w,bs,orders,ev,order=self.scene()
        shop=l.build(g,w,'utom',h,57)
        self.assertGreater(shop[0],-2752);self.assertEqual(shop[1],-2816)
        u=unit('utom',100,shop[0]);u.y=shop[1];bs.append(u);l.observe(g,62)
        grave=l.build(g,w,'ugrv',h,81)
        self.assertEqual(grave,(-2240,-3328))
        self.assertTrue(clear_of_buildings(grave,bs,128,ENVELOPES['ugrv']))
        # Every selected candidate retains the existing outward-lane envelope.
        length=(h.x*h.x+h.y*h.y)**.5;direction=(-h.x/length,-h.y/length)
        for code,p in [('utom',shop),('ugrv',grave)]:
            dx,dy=p[0]-h.x,p[1]-h.y
            self.assertTrue(dx*direction[0]+dy*direction[1]<=0 or
                            abs(dx*direction[1]-dy*direction[0])>=ENVELOPES[code]+128)

    def test_failed_preferred_graveyard_immediately_selects_another_spot(self):
        l,g,h,w,bs,orders,ev,order=self.scene()
        first=l.build(g,w,'ugrv',h,81)
        self.assertEqual(first,(-2240,-3328))
        self.assertTrue(l.observe(g,84))
        self.assertNotEqual(l.pending['ugrv']['point'],first)

    def test_occupied_old_shop_slot_is_not_forced(self):
        l,g,h,w,bs,orders,ev,order=self.scene()
        blocker=unit('utom',100,-2240);blocker.y=-3328;bs.append(blocker)
        point=l.build(g,w,'ugrv',h,81)
        self.assertNotEqual(point,(-2240,-3328))
        self.assertTrue(clear_of_buildings(point,bs,128,ENVELOPES['ugrv']))


if __name__=='__main__':unittest.main()
