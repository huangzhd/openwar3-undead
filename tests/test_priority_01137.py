import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_first_attack_01132 as supplies
import test_economy_timing_01131 as timing
import test_ch_opening_01130 as opening
from test_micro_loot import unit
from test_baseline import unit as building


class ManaPriorityTests(unittest.TestCase):
    def test_two_coils_skip_potion_and_release_orb_budget_after_portal_sale(self):
        g,b,events=supplies.SuppliesTests().scene();g.dk.mana=150;s=b.first_attack_supply
        g.bags[g.lich.handle][0]='ocor' # Orb purchase now includes the first TP sale trip.
        self.assertEqual(s.reserve(b,3),0)
        s.tick(b,g.heroes,[],500,3);b.battle_shop.observe(g,502)
        s.tick(b,g.heroes,[],504,3)
        self.assertEqual(g.orders,[('sell','stwp')]);self.assertTrue(s.ready(b));self.assertTrue(s.done)

    def test_low_mana_cannot_spend_or_hold_orb_and_third_hero_funds(self):
        for missing in ('orb','hero'):
            g,b,events=supplies.SuppliesTests().scene();g.dk.mana=50;g.bags[g.dk.handle]=[None]*6
            if missing=='hero':g.heroes.remove(g.dark);g.bags[g.lich.handle][0]='ocor'
            s=b.first_attack_supply
            self.assertEqual(s.reserve(b,3),0);self.assertFalse(s.tick(b,g.heroes,[],500,3))
            self.assertFalse(g.orders);self.assertTrue(s.ready(b))

    def test_low_mana_after_core_purchase_buys_only_if_nearby(self):
        for distance in (0,2000):
            g,b,events=supplies.SuppliesTests().scene();g.dk.mana=50;g.dk.x=distance
            g.bags[g.dk.handle]=[None]*6;g.bags[g.lich.handle][0]='ocor';s=b.first_attack_supply
            self.assertEqual(s.reserve(b,3),200 if distance==0 else 0)
            s.tick(b,g.heroes,[],500,3)
            self.assertEqual('pman' in g.inventory(g.dk),distance==0)
            self.assertFalse(any(o[0]=='move' for o in g.orders));self.assertTrue(s.ready(b))

    def test_unknown_inventory_cannot_claim_portal_sale_complete(self):
        g,b,events=supplies.SuppliesTests().scene();g.bags[g.dk.handle]=None
        self.assertFalse(b.first_attack_supply.ready(b))


class MidgameCampsTests(unittest.TestCase):
    def scene(self):
        b,g,old,orders=opening.CHOpeningTests().scene()
        frame=json.loads((Path(__file__).parent/'fixtures/ch-midgame-01137.json').read_text(encoding='utf-8'))['frame']
        army=[]
        for r in frame['army']:
            u=unit(r['type'],r['handle'][0],r['x'],r['hp']);u.y=r['y'];u.hp_max=r['hp_max'];u.mana=r['mana'];army.append(u)
        c=b.creeping;c.tier=2;c.home_only=True;c.cleared={'ch-9','ch-13','ch-6','ch-0'}
        return b,g,army,c

    def test_actual_lich_army_without_dk_or_statue_can_continue_to_murlocs(self):
        b,g,army,c=self.scene();army=[u for u in army if u.type!='Udea'];center=(-3834,3431)
        g.walk_path=lambda a,z:[a,z]
        point,foes=c.choose(g,army,center,b.home,405)
        self.assertEqual(c.active['id'],'ch-5');self.assertNotEqual(point,(b.home.x,b.home.y))
        self.assertNotIn('ch-4',{x['id'] for x in c.candidates(g,army,b.home,405)})

    def test_healthy_dual_hero_three_fiends_allow_home_expansion_without_statue(self):
        for home,expected in (((2176,4224),'ch-4'),((-2304,-4736),'ch-12')):
            b,g,old,orders=opening.CHOpeningTests().scene(*home);c=b.creeping;c.tier=2;c.home_only=True
            army=[unit('Udea',1,home[0]),unit('Ulic',2,home[0])]+[unit('ucry',i,home[0]) for i in (3,4,5)]
            for u in army:u.y=home[1];u.hp=u.hp_max;u.level=3
            ids={x['id'] for x in c.candidates(g,army,b.home,420)}
            self.assertNotIn(expected,ids);self.assertNotIn('ch-7',ids) # Latest CH route excludes the side expansion.
            camp=next(camp for camp in c.catalog if camp['id']==expected)
            self.assertTrue(c.ch_midgame_support(g,camp,army,b.home))

    def test_injured_hero_and_known_blocked_paths_still_exclude(self):
        for why in ('hero','route','cleared'):
            b,g,army,c=self.scene();army=[u for u in army if u.type!='Udea']
            if why=='hero':next(u for u in army if u.type=='Ulic').hp=100
            if why=='route':g.path_distance=lambda *a:None
            if why=='cleared':c.cleared.add('ch-5')
            g.walk_path=lambda a,z:[a,z]
            c.choose(g,army,(-3834,3431),b.home,405)
            self.assertTrue(c.active is None or c.active['id']!='ch-5')


class BuildOrderTests(unittest.TestCase):
    def test_tier_three_lich_slaughter_then_optional_population(self):
        g,e=timing.TransitionBudgetTests().game(2);g.gold=1500;g.lumber=900
        e.tick(g,300);self.assertEqual(g.commands,['unp2']);self.assertFalse(g.builds)
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'],progress=.1)
        e.tick(g,304);self.assertEqual(g.commands,['unp2','Ulic']);self.assertFalse(g.builds)
        e.tick(g,308);self.assertEqual([x[1] for x in g.builds],['uslh'])
        h=building('uslh',990,owner=0);h.x,h.y=g.builds[-1][2:];g.own.append(h);g.busy[h.handle]=N(kind='construction',queue=['uslh'])
        g.food=36;e.tick(g,312);self.assertEqual([x[1] for x in g.builds],['uslh','uzig'])

    def test_tier_three_saving_does_not_spend_on_lich_slaughter_or_tower(self):
        g,e=timing.TransitionBudgetTests().game(2);g.gold=300;g.lumber=200;g.food=38
        e.tick(g,300);self.assertFalse(g.commands);self.assertFalse(g.builds)

    def test_food_needed_for_lich_is_only_supply_exception_after_tier_three_paid(self):
        g,e=timing.TransitionBudgetTests().game(2);g.gold=1000;g.lumber=800;g.food=38
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'],progress=.1)
        e.tick(g,304);self.assertEqual([x[1] for x in g.builds],['uzig']);self.assertFalse(g.commands)

if __name__=='__main__':unittest.main()
