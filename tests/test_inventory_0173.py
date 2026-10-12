import unittest
from types import SimpleNamespace as N
import bootstrap
from undead.game_view import Game
from undead.policy import Situation, Action, choose_rule


class InventoryTests(unittest.TestCase):
    def make(self, items=None, abilities=None, **changes):
        values=dict(handle=(1,2),handle_lo=1,handle_hi=2,owner=0,alive=True,
                    is_hero=True,has_detail=True,
                    items=items if items is not None else ['rat6','ocor','afac','rnec',None,None],
                    abilities=[N(code=c) for c in (abilities if abilities is not None else ['AIrd','AIar'])])
        values.update(changes)
        hero=N(**values); units={hero.handle:hero}
        g=Game.__new__(Game)
        g.snapshot=lambda *a,**kw:N(by_handle=units,unit_by_handle=lambda h:units.get(h))
        g.me=lambda:0
        return g,hero,units

    def test_current_slots_allow_formed_army_to_attack_when_ainv_is_missing(self):
        g,h,_=self.make()
        bag=g.inventory(h)
        s=Situation(700,tier=3,lich=True,dk=True,third_hero=True,orb='ocor' in bag)
        self.assertEqual(choose_rule(s),Action.ATTACK)
        self.assertEqual(bag,['rat6','ocor','afac','rnec',None,None])
        bag[1]=None
        self.assertEqual(g.inventory(h)[1],'ocor')

    def test_current_empty_inventory_revokes_readiness_instead_of_caching_orb(self):
        g,h,units=self.make();self.assertIn('ocor',g.inventory(h))
        current=N(**vars(h));current.items=[None]*6;units[h.handle]=current
        s=Situation(701,tier=3,lich=True,third_hero=True,orb='ocor' in g.inventory(h))
        self.assertEqual(choose_rule(s),Action.CREEP)
        self.assertEqual(g.inventory(h),[None]*6)

    def test_missing_hero_never_uses_stale_snapshot(self):
        g,h,units=self.make();units.clear();self.assertIsNone(g.inventory(h))

    def test_unavailable_or_unowned_details_do_not_establish_inventory(self):
        for change in (dict(owner=1),dict(alive=False),dict(is_hero=False),
                       dict(has_detail=False),dict(items=['ocor'])):
            with self.subTest(change=change):
                g,h,_=self.make(**change);self.assertIsNone(g.inventory(h))

    def test_regular_sdk_inventory_is_preserved(self):
        g,h,_=self.make(items=['pman',None,None,None,None,None],abilities=['AInv'])
        self.assertEqual(g.inventory(h),h.items)
        self.assertIsNone(g.inventory(None))


if __name__=='__main__':unittest.main()
