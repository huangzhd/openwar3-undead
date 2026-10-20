import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_foundation_owner_01124 as foundation
import test_destroyer_01139 as destroyer
from test_micro_loot import FakeLootGame, unit
from undead.controller import Controller
from undead.loot import Loot
from undead.policy import Action


class BuildingPriorityTests(unittest.TestCase):
    def test_all_buildings_reselect_lost_orders_without_24_second_wait(self):
        for code in ('uzig','uaod','usep','uslh','utom','ugrv'):
            l,g,h,w,bs,ws,orders,ev,order=foundation.FoundationTests().scene()
            g.can_afford=lambda code:True
            first=l.build(g,w,code,h,100)
            self.assertTrue(l.observe(g,102.1),code)
            self.assertNotEqual(l.pending[code]['point'],first,code)
            self.assertEqual(l.pending[code]['worker'],w.handle)
            self.assertEqual(len(orders),2)

    def test_supply_travel_progress_and_real_foundation_never_duplicate(self):
        l,g,h,w,bs,ws,orders,ev,order=foundation.FoundationTests().scene()
        g.can_afford=lambda code:True;point=l.build(g,w,'uzig',h,100)
        order[0]=0x757a6967
        for t in (102,104,106):
            w.x+=(point[0]-w.x)*.3;w.y+=(point[1]-w.y)*.3
            l.observe(g,t)
        self.assertEqual(len(orders),1)
        b=unit('uzig',99,point[0]);b.y=point[1];bs.append(b)
        l.observe(g,107)
        self.assertFalse(l.pending);self.assertEqual(len(orders),1)

    def test_real_supply_shortage_precedes_shopping_reserve_even_before_third_hero(self):
        f=json.loads((Path(__file__).parent/'fixtures/ni_201653_supply_loot.json').read_text(encoding='utf-8'))
        res=f['summaries'][-1]['resources']
        for existing in (3,4):
            g,e=destroyer.DestroyerEconomyTests().scene()
            g.own=[u for u in g.own if u.type not in {'Nbrn','uzig'}]
            e.ever_heroes.discard('Nbrn');g.food=res['food_used'];g.cap=res['food_cap']
            for i in range(existing):
                b=unit('uzig',900+i,1000+i*400);b.owner=0;g.own.append(b)
            e.save_for_trade=True
            e.tick(g,604)
            self.assertTrue(g.builds)
            self.assertEqual(g.builds[-1][1],'uzig')
            self.assertFalse(g.commands)

    def test_unfinished_supply_is_not_duplicated(self):
        g,e=destroyer.DestroyerEconomyTests().scene();g.food=g.cap
        zig=g.my_buildings({'uzig'})[0];g.busy[zig.handle]=N(kind='construction',queue=['uzig'])
        e.save_for_trade=True;e.tick(g,600)
        self.assertFalse(g.builds)

    def test_shortage_saves_insufficient_gold_instead_of_optional_spending(self):
        g,e=destroyer.DestroyerEconomyTests().scene();g.food=g.cap;g.gold=100
        e.tick(g,600)
        self.assertFalse(g.builds);self.assertFalse(g.commands);self.assertEqual(g.gold,100)


class ImmediateLootTests(unittest.TestCase):
    def test_mid_camp_picker_takes_drop_while_others_keep_fighting(self):
        g=FakeLootGame();g.hero.hp=g.hero.hp_max
        friend=unit('ucry',2,20);foe=unit('nftt',3,300);foe.owner=12
        g.creeps=lambda:[foe]
        b=Controller(g,lambda *a,**k:None);b.action=Action.CREEP;b.loot=Loot({},b.log)
        b.creeping.active={'id':'ni-0'};b.creeping.map_alias='NI'
        calls=[];b.fight=lambda army,foes,now:calls.append(([u.handle for u in army],foes))
        b.go=lambda *a,**k:self.fail('main army must not follow the picker')
        self.assertTrue(b.collect_loot([g.hero,friend],[foe],400,[g.hero]))
        self.assertEqual(g.pickups,['ratf']);self.assertEqual(calls,[([friend.handle],[foe])])
        self.assertFalse(b.creeping.paused)
        g.ground=[];g.inv[0]='ratf';g.hero.item_addrs=[99]
        self.assertFalse(b.collect_loot([g.hero,friend],[foe],401,[g.hero]))
        self.assertTrue(b.loot.done)

    def test_enemy_contact_and_unavailable_picker_do_not_force_loot(self):
        for reason in ('enemy','hurt'):
            g=FakeLootGame();g.hero.hp=g.hero.hp_max if reason=='enemy' else 100
            foe=unit('ogru' if reason=='enemy' else 'nftt',3,200)
            foe.owner=1 if reason=='enemy' else 12;g.creeps=lambda:[foe] if reason=='hurt' else []
            b=Controller(g,lambda *a,**k:None);b.action=Action.CREEP;b.loot=Loot({},b.log)
            self.assertFalse(b.collect_loot([g.hero],[foe],400,[g.hero]))
            self.assertFalse(g.pickups)


if __name__=='__main__':unittest.main()
