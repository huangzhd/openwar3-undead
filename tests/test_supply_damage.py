import unittest
from types import SimpleNamespace as N
from test_upgrades_portal import UpgradeGame
from test_baseline import unit
from undead.economy import Economy

class DamagedSupplyTests(unittest.TestCase):
    def game(self):
        g=UpgradeGame();g.food=39
        g.resources=lambda:dict(gold=3000,lumber=2000,food_used=39,food_cap=40)
        zig=g.my_buildings({'uzig'})[0];zig.hp=50
        g.own.extend([unit('uzig',301,owner=0),unit('uzig',302,owner=0)])
        for b in g.my_buildings({'uzig'}):b.hp=50
        e=Economy(lambda *a,**kw:None);built=[]
        e.build=lambda g,code,home,now:built.append(code) or True
        return g,e,built

    def test_damaged_completed_zigs_allow_supply_expansion(self):
        g,e,built=self.game()
        e.tick(g,1000)
        self.assertEqual(built,['uzig'])
        self.assertFalse(g.commands)
        # Actual new construction prevents another tower until it finishes.
        new=unit('uzig',303,owner=0);new.hp=10;g.own.append(new)
        g.busy[new.handle]=N(kind='construction',queue=[])
        e.tick(g,1003);self.assertEqual(built,['uzig'])

    def test_real_construction_blocks_duplicate_supply_even_at_full_health(self):
        g,e,built=self.game();zig=g.my_buildings({'uzig'})[0];zig.hp=zig.hp_max
        g.busy[zig.handle]=N(kind='construction',queue=[])
        e.tick(g,1000);self.assertFalse(built)

if __name__=='__main__':unittest.main()
