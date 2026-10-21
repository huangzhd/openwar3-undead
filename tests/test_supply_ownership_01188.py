import unittest
from undead.equipment import Equipment, HEALTH_POTIONS
from test_consumables import Game
import test_lich_items_0129 as lich_cases
from test_micro_loot import unit


class SupplyOwnershipTests(unittest.TestCase):
    def scene(self):
        g=Game();events=[];locks={}
        e=Equipment(lambda event,**kw:events.append((event,kw)))
        return g,e,events,locks

    def settle(self,g,e,locks,potions_only=True):
        for now in range(1,45,4):e.tick(g,g.heroes,[],now,locks,potions_only)

    def test_two_bottles_split_and_two_scrolls_balance_lich_first(self):
        for supplies_only in (True,False):
            g,e,events,locks=self.scene();dk,lich,dark=g.heroes
            g.bags[dk.handle][:4]=['phea','pghe','shea','sres']
            self.settle(g,e,locks,supplies_only)
            self.assertFalse(any(c in HEALTH_POTIONS for c in g.bags[dk.handle]))
            self.assertEqual([sum(c in HEALTH_POTIONS for c in g.bags[h.handle]) for h in (lich,dark)],[1,1])
            self.assertIn('shea',g.bags[lich.handle]);self.assertIn('sres',g.bags[dk.handle])
            self.assertEqual(sum(n=='equipment_transfer_confirmed' for n,_ in events),3)
            self.assertEqual(len(g.orders),3) # no oscillation on later ticks

    def test_dark_keeps_only_bottle_even_when_lich_has_none(self):
        g,e,_,locks=self.scene();g.bags[g.heroes[2].handle][0]='phea'
        self.settle(g,e,locks,False)
        self.assertFalse(g.orders)

    def test_duplicate_on_either_ranged_hero_supplies_the_other(self):
        for donor in (1,2):
            g,e,_,locks=self.scene();g.bags[g.heroes[donor].handle][:2]=['pghe','phea']
            self.settle(g,e,locks,False)
            self.assertEqual([sum(c in HEALTH_POTIONS for c in b) for b in g.bags.values()],[0,1,1])
            self.assertEqual(len(g.orders),1)

    def test_scroll_handoff_respects_recipient_cast_distance_and_full_bag(self):
        for reason in ('cast','distance','full','unknown','danger'):
            g,e,_,locks=self.scene();dk,lich,_=g.heroes;g.bags[dk.handle][0]='shea'
            if reason=='cast':locks[lich.handle]=20
            if reason=='distance':lich.x=1000
            if reason=='full':g.bags[lich.handle]=['cnob']*5+[None]
            if reason=='unknown':g.bags[lich.handle]=None
            e.tick(g,g.heroes,[dk] if reason=='danger' else [],1,locks,True)
            self.assertFalse(g.orders)

    def test_one_scroll_per_hero_stays_and_full_lich_does_not_lose_self_rescue(self):
        g,e,_,locks=self.scene();dk,lich,dark=g.heroes
        g.bags[lich.handle]=['ocor','rnec','pnvl','cnob','phea','shea']
        g.bags[dk.handle][0]='sres';g.bags[dark.handle][0]='shea'
        self.settle(g,e,locks,False)
        self.assertFalse(g.orders);self.assertIn('shea',g.bags[lich.handle])

    def test_three_scrolls_on_lich_balance_without_taking_last_scroll(self):
        g,e,_,locks=self.scene();dk,lich,dark=g.heroes
        g.bags[lich.handle][:3]=['shea','sres','shea']
        self.settle(g,e,locks)
        self.assertEqual([sum(c in {'shea','sres'} for c in b) for b in g.bags.values()],[1,1,1])
        self.assertEqual(len(g.orders),2)

    def test_single_scroll_moves_to_lich_even_if_donor_has_only_one(self):
        for donor in (0,2):
            g,e,_,locks=self.scene();g.bags[g.heroes[donor].handle][0]='shea'
            self.settle(g,e,locks)
            self.assertIn('shea',g.bags[g.heroes[1].handle]);self.assertEqual(len(g.orders),1)

    def test_failed_scroll_handoff_has_three_attempt_limit_and_no_confirmation(self):
        g,e,events,locks=self.scene();g.bags[g.heroes[0].handle][0]='shea'
        g.give_item=lambda *a:g.orders.append('receipt') or True
        self.settle(g,e,locks)
        self.assertEqual(len(g.orders),3)
        self.assertFalse(any(n=='equipment_transfer_confirmed' for n,_ in events))

    def loot_scene(self,code):
        g,loot,heroes,picked,ground,events=lich_cases.LichOutputTests().game(code)
        dark=unit('Nbrn',3,50);heroes.append(dark)
        bags={h.handle:[None]*6 for h in heroes};g.inventory=lambda h:bags[h.handle]
        return g,loot,heroes,picked,bags

    def test_ground_blood_fills_lich_then_dark_and_never_dk(self):
        for lich_has,dark_has,want in ((False,True,['Ulic']),(True,False,['Nbrn']),(True,True,[])):
            g,loot,heroes,picked,bags=self.loot_scene('phea')
            if lich_has:bags[heroes[1].handle][0]='pghe'
            if dark_has:bags[heroes[2].handle][0]='phea'
            loot.tick(g,heroes,[],1)
            self.assertEqual(picked,want)

    def test_ground_scroll_prefers_lich_then_missing_hero(self):
        for code in ('shea','sres'):
            for has_scroll in (False,True):
                g,loot,heroes,picked,bags=self.loot_scene(code)
                if has_scroll:bags[heroes[1].handle][0]='shea'
                loot.tick(g,heroes,[],1)
                self.assertEqual(picked,['Udea'] if has_scroll else ['Ulic'])

    def test_absent_ranged_heroes_do_not_make_dk_pick_up_blood(self):
        g,loot,heroes,picked,bags=self.loot_scene('phea')
        loot.tick(g,heroes[:1],[],1)
        self.assertFalse(picked)

    def test_blue_still_returns_to_dk_alongside_new_allocation(self):
        g,e,_,locks=self.scene();dk,lich,dark=g.heroes
        g.bags[lich.handle][:2]=['pman','phea'];g.bags[dark.handle][:2]=['phea','shea']
        self.settle(g,e,locks)
        self.assertIn('pman',g.bags[dk.handle]);self.assertIn('shea',g.bags[lich.handle])
        self.assertIn('phea',g.bags[lich.handle]);self.assertIn('phea',g.bags[dark.handle])


if __name__=='__main__':unittest.main()
