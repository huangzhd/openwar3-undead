import unittest
from types import SimpleNamespace as N
from test_upgrades_portal import PortalGame
from undead.controller import Controller

class ShoppingTests(unittest.TestCase):
    def make(self):
        g=PortalGame();b=Controller(g,lambda *a,**kw:None)
        g.inv[g.dk.handle]=['stwp','rnec','rat6','gcel','cnob','rlif']
        return g,b

    def test_full_dk_makes_room_then_wrong_recipient_transfers_without_duplicate_buy(self):
        g,b=self.make()
        self.assertTrue(b.shop_item(g.heroes,g.lich,g.shop,'ocor',1))
        self.assertEqual(g.purchases,[])
        self.assertEqual(g.transfers,[(g.dk.handle,2,g.lich.handle)])
        self.assertGreater(b.cast_until[g.dk.handle],1)
        # The command receipt alone does not prove room was made.
        b.shop_item(g.heroes,g.lich,g.shop,'ocor',2)
        self.assertFalse(g.purchases)
        g.inv[g.dk.handle][2]=None;g.inv[g.lich.handle][0]='rat6'
        b.shop_item(g.heroes,g.lich,g.shop,'ocor',4)
        self.assertEqual(g.purchases,['ocor'])
        g.inv[g.dk.handle][2]='ocor'
        b.shop_item(g.heroes,g.lich,g.shop,'ocor',8)
        self.assertEqual(g.transfers[-1],(g.dk.handle,2,g.lich.handle))
        self.assertEqual(g.purchases,['ocor'])

    def test_last_recipient_slot_is_reserved_for_the_orb(self):
        g,b=self.make();g.inv[g.lich.handle]=['rat6']*5+[None]
        self.assertTrue(b.shop_item(g.heroes,g.lich,g.shop,'ocor',1))
        self.assertFalse(g.transfers);self.assertFalse(g.purchases)

    def test_unaffordable_purchase_does_not_pin_army_at_shop(self):
        g,b=self.make();g.gold=374
        self.assertFalse(b.shop_item(g.heroes,g.lich,g.shop,'ocor',1))
        self.assertFalse(g.transfers);self.assertFalse(g.purchases)

    def test_unconfirmed_purchases_are_bounded_and_cooldown_releases_army(self):
        g,b=self.make();g.inv[g.dk.handle]=[None]*6
        for now in (1,4,7):self.assertTrue(b.shop_item(g.heroes,g.lich,g.shop,'ocor',now))
        for now in (8,20,50,126):self.assertFalse(b.shop_item(g.heroes,g.lich,g.shop,'ocor',now))
        self.assertEqual(g.purchases,['ocor']*3)
        b.shop_item(g.heroes,g.lich,g.shop,'ocor',127)
        self.assertEqual(g.purchases,['ocor']*4)

    def test_failed_make_room_does_not_retry_forever_or_discard_items(self):
        g,b=self.make()
        for now in (1,4,7):b.shop_item(g.heroes,g.lich,g.shop,'ocor',now)
        self.assertFalse(b.shop_item(g.heroes,g.lich,g.shop,'ocor',10))
        self.assertFalse(b.shop_item(g.heroes,g.lich,g.shop,'ocor',140))
        self.assertEqual(len(g.transfers),3)
        self.assertFalse(g.purchases)
        self.assertEqual(g.inv[g.dk.handle],['stwp','rnec','rat6','gcel','cnob','rlif'])
