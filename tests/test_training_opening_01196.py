import unittest
from undead.controller import Controller
import test_blight_dispel_01194 as opening


class TrainingOpeningTests(unittest.TestCase):
    def test_melee_advances_without_stationary_layout_with_or_without_skull(self):
        for skull in (True,False):
            with self.subTest(skull=skull):
                b,g,own,foes,orders,events,effects,car,dk,bag,uses=opening.BlightDispelTests().scene(Controller)
                if not skull:bag.clear()
                for e in foes:e.x=1000
                pulls={}
                for now in (1,4,7):b.prepare_blight(own,foes,now)
                b.battle_actions(own,foes,10,pulls)
                self.assertFalse(b.blight_waiting)
                self.assertFalse(any(e=='battle_prebattle_layout' for e,_ in events))
                self.assertFalse(uses)
                self.assertNotIn(dk.handle,b.cast_until)
                self.assertFalse(any(e.startswith('battle_skull_') for e,_ in events))
                # The main army keeps its ordinary advance despite a nearby foe
                # and a skull carried by the DK; no opening formation owns it.
                orders.clear()
                b.engage_battle([u for u in own if u.handle not in pulls],foes,12)
                advancing=[o for o in orders if o[0]=='move' and o[1] in {u.handle for u in own if u.type=='ucry'}]
                self.assertTrue(advancing)
                self.assertTrue(all(o[2][0]>g.unit(o[1]).x for o in advancing))
                self.assertFalse(any(o[0] in {'hold','hold_after'} for o in orders))
                orders.clear();b.battle_enemies=[]
                b.go([u for u in own if u.type=='ucry'],(2000,0),15,attack=True)
                self.assertTrue(any(o[0] in {'attack','attack_move'} for o in orders))
                self.assertFalse(any(o[0] in {'hold','hold_after'} for o in orders))


if __name__=='__main__':unittest.main()
