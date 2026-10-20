import json
import unittest
from pathlib import Path
import test_ni_route_01142 as ni
import test_battle_shop_0163 as shop
from test_micro_loot import unit
from undead.battle_shop import sellable


class RecoveredCampTests(unittest.TestCase):
    def scene(self):
        b,g,a,c=ni.NIRouteTests().scene(False,True);c.cleared.update(c.ni_opening(b.home)+c.ni_midgame(b.home));c.tier=3
        c.prepare_ni_center(g,a,b.home,483.9,True,False)
        c.active=next(p for p in c.catalog if p['id']=='ni-7')
        return b,g,a,c

    def test_real_recovered_shop_state_does_not_wait_for_old_90_seconds(self):
        b,g,a,c=self.scene()
        f=json.loads((Path(__file__).parent/'fixtures/ni_005050_shop_wait.json').read_text())
        c.defer(f['deferred']['clock'],'army_not_ready')
        self.assertEqual(c.deferred['ni-7'],499.255)
        self.assertTrue(f['summary']['situation']['orb'])
        self.assertEqual(f['summary']['situation']['army_health'],1)
        center=tuple(f['march']['center']) if 'center' in f['march'] else (-1328.636,-2826.344)
        for u in a:u.x=center[0];u.y=center[1]
        c.choose(g,a,center,b.home,f['summary']['clock'])
        self.assertEqual(c.active['id'],'ni-7')
        self.assertNotIn('ni-7',c.cleared)

    def test_short_backoff_still_requires_recovered_health(self):
        b,g,a,c=self.scene();c.ni_contested=True;c.defer(500,'army_not_ready')
        self.assertFalse(c.candidates(g,a,b.home,504))
        for u in a:u.hp=.4*u.hp_max
        self.assertFalse(c.candidates(g,a,b.home,506))
        for u in a:u.hp=u.hp_max
        self.assertEqual({p['id'] for p in c.candidates(g,a,b.home,507)},{'ni-7'})

    def test_hostile_or_path_failure_keeps_long_backoff(self):
        for reason in ('player_contact','enemy_main_route','unreachable','no_movement_or_damage_progress'):
            b,g,a,c=self.scene();c.ni_contested=True;c.defer(500,reason)
            self.assertEqual(c.deferred['ni-7'],590)
            self.assertFalse(c.candidates(g,a,b.home,506))


class LightningShieldSaleTests(unittest.TestCase):
    def test_any_hero_can_sell_and_only_real_inventory_change_confirms(self):
        for who in ('dk','lich','dark'):
            for actual in (True,False):
                g,b,s,events=shop.ShoppingTests().make();h=getattr(g,who);h.x=0
                g.bags[h.handle][1]='wlsd'
                def sell(hero,slot,target):
                    if actual:g.bags[hero.handle][slot]=None;g.gold+=50
                    g.orders.append(('sell',hero.type,'wlsd'));return True
                g.sell_item=sell
                self.assertTrue(s.sell_nearby(b,g.heroes,[],10));s.observe(g,14)
                self.assertEqual(events[-1]['event'],'shop_transaction_confirmed' if actual else 'shop_transaction_unconfirmed')

    def test_no_trip_or_sale_under_visible_threat_and_keep_illusion_wand(self):
        g,b,s,events=shop.ShoppingTests().make();g.dk.x=1000;g.bags[g.dk.handle][1]='wlsd'
        self.assertFalse(s.sell_nearby(b,g.heroes,[],10));self.assertFalse(g.orders)
        g.dk.x=0;foe=unit('ogru',999,100)
        self.assertFalse(s.sell_nearby(b,g.heroes,[foe],11));self.assertFalse(g.orders)
        self.assertTrue(sellable(g.dk,'wlsd'));self.assertFalse(sellable(g.dk,'will'))


if __name__=='__main__':unittest.main()
