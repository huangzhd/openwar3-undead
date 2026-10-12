import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_opening_safety_0131 as safety
import test_upgrades_portal as portals
import test_scout_opening as opening
from undead.scouting import CritterSearch
from undead.micro import Micro
from undead.loot import Loot
from undead.policy import Situation

class Strategy0140Tests(unittest.TestCase):
    def portal(self):
        g,b,dk,allies,orders,clock=safety.EmergencyTests().controller()
        b.home=unit('unpl',20,-5000);dk.hp=500
        b.situation=Situation(100,local_enemy_hp=900,army_health=.9)
        foe=g.enemies()[0];foe.type='hrif';foe.x=100
        return g,b,dk,allies,orders,foe

    def test_two_dying_statues_and_low_average_do_not_force_portal(self):
        g,b,d,allies,orders,foe=self.portal()
        for u in allies[:2]:u.type='uobs';u.hp=20
        b.situation.army_health=.2
        self.assertFalse(b.emergency_portal([d,*allies],100));self.assertFalse(orders)

    def test_five_threatened_units_required_and_summons_excluded(self):
        g,b,d,allies,orders,foe=self.portal()
        for u in allies:u.hp=100
        self.assertFalse(b.emergency_portal([d,*allies],100))
        extra=unit('uske',50,0,20)
        self.assertFalse(b.emergency_portal([d,*allies,extra],101))
        extra.type='ucry'
        self.assertTrue(b.emergency_portal([d,*allies,extra],102));self.assertEqual(orders[0][0],'portal')

    def test_critical_hero_threshold_and_threat_are_both_required(self):
        g,b,d,allies,orders,foe=self.portal();d.hp=120
        self.assertFalse(b.emergency_portal([d,*allies],100))
        d.hp=119;foe.x=2000
        self.assertFalse(b.emergency_portal([d,*allies],101))
        foe.x=100;foe.hp=100;b.situation.local_enemy_hp=100
        self.assertTrue(b.emergency_portal([d,*allies],102))

    def test_distant_wounded_units_do_not_force_transport(self):
        g,b,d,allies,orders,foe=self.portal()
        far=[unit('ucry',50+i,4000,20) for i in range(5)]
        self.assertFalse(b.emergency_portal([d,*far],100));self.assertFalse(orders)

    def test_existing_lich_scroll_never_buys_even_without_previous_purchase(self):
        g,b,_=portals.PortalTests().make();g.inv[g.lich.handle][0]='stwp'
        g.inv[g.dk.handle]=['rat6']*6
        self.assertTrue(b.prepare_attack(g.heroes,1))
        self.assertFalse(g.purchases);self.assertFalse(g.transfers)
        self.assertFalse(b.tp_waiting)

    def test_unknown_teammate_inventory_blocks_duplicate_purchase(self):
        g,b,_=portals.PortalTests().make();g.inv[g.lich.handle]=None
        self.assertFalse(b.prepare_attack(g.heroes,1));self.assertFalse(g.purchases)

    def test_team_scroll_budget_releases_upgrade_gold(self):
        g,e=portals.UpgradeTests().make();g.invs['Udea']=[None]*6
        g.invs['Ulic']=['ocor','stwp']+[None]*4;g.gold=150;g.lumber=50
        self.assertTrue(e.research_upgrades(g,1));self.assertEqual(g.commands,['Rura'])

    def test_optional_reserve_is_independent_of_scroll_carrier(self):
        g,e=portals.UpgradeTests().make();before=e.optional_reserve(g,100)
        g.invs['Udea']=[None]*6;g.invs['Ulic']=['ocor','stwp']+[None]*4
        self.assertEqual(e.optional_reserve(g,100),before)
        g.invs['Ulic']=['ocor']+[None]*5
        self.assertEqual(e.optional_reserve(g,100),before+350)

    def test_extra_ground_scroll_is_not_picked_up(self):
        d=unit('Udea',1,0);l=unit('Ulic',2,0);picked=[]
        item=N(type='stwp',handle_lo=10,handle_hi=0,addr=10,x=10,y=0,life=75)
        bags={d.handle:[None]*6,l.handle:['stwp']+[None]*5}
        g=N(dist=dist,inventory=lambda h:bags[h.handle],items_on_ground=lambda:[item],
            path_distance=dist,pick_up=lambda h,it:picked.append(h.handle) or True)
        loot=Loot({},lambda *a,**kw:None)
        loot.tick(g,[d],[],1,[d,l]);self.assertFalse(picked)
        bags[l.handle]=[None]*6;loot.tick(g,[d],[],3,[d,l]);self.assertEqual(picked,[d.handle])

    def test_statue_pulls_with_full_mana_dk_and_rejoins_when_safe(self):
        d=unit('Udea',1,0);s=unit('uobs',2,100,80);foe=unit('hfoo',3,300)
        micro=Micro(lambda *a,**kw:None)
        moves=micro.plan([d,s],[foe],1,lambda _:s.handle,dist,lambda *p:True,(-2000,0))
        self.assertIn(s.handle,moves);self.assertGreater(dist(moves[s.handle],foe),dist(s,foe))
        foe.x=3000
        self.assertFalse(micro.plan([d,s],[foe],5,lambda _:None,dist,lambda *p:True,(-2000,0)))

    def search(self):
        scout=unit('uaco',1,0);home=N(x=0,y=0);events=[]
        g=N(dist=dist,path_distance=dist,visible=lambda x,y:dist(scout,(x,y))<220)
        return CritterSearch(lambda e,**kw:events.append(dict(event=e,**kw)),spawns=[]),g,scout,home,events

    def test_scout_waypoint_survives_clock_boundary_until_arrival(self):
        search,g,s,h,events=self.search();p=search.choose(g,s,h,11.9)
        s.x,s.y=p[0]*.4,p[1]*.4
        self.assertEqual(search.choose(g,s,h,13.1),p)
        s.x,s.y=p;p2=search.choose(g,s,h,15)
        self.assertNotEqual(p,p2);self.assertIn(p,search.checked)
        self.assertEqual(events[-2]['reason'],'arrived')

    def test_search_explores_both_sides_and_exhausts_without_revisiting(self):
        search,g,s,h,events=self.search();points=[]
        for t in range(40):
            p=search.choose(g,s,h,t)
            if p is not None:points.append(p);s.x,s.y=p
        self.assertEqual(len(set(points)),2)
        self.assertTrue(search.reported)
        self.assertIsNone(search.choose(g,s,h,45))

    def test_unreachable_and_stalled_search_is_bounded(self):
        search,g,s,h,events=self.search();g.path_distance=lambda a,b:None
        self.assertIsNone(search.choose(g,s,h,0))
        search,g,s,h,events=self.search();p=search.choose(g,s,h,0)
        self.assertNotEqual(search.choose(g,s,h,12),p)
        self.assertEqual(events[-2]['reason'],'no_progress_or_budget')

    def test_search_stops_at_opening_deadline_and_hidden_death_is_not_corpse(self):
        b,g,d,corpse,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        corpse.visible_to=lambda me:False
        b.scout(149);self.assertIsNone(b.scout_corpse)
        b.scout(150);self.assertEqual(orders[-1][2],b.enemy_main)

    def test_visible_critter_interrupts_search_and_tracks_observed_point(self):
        b,g,d,critter,own,all_units,orders,events,inv,cool=opening.ScoutCorpseTests().make()
        b.scout_critter=None;critter.alive=True;critter.hp=15
        b.scout(100)
        self.assertEqual(orders[-1][0],'attack');self.assertEqual(b.scout_critter,critter.handle)
        all_units.remove(critter);b.scout(105)
        self.assertEqual(orders[-1][2],(-1000,0));self.assertIsNone(b.scout_corpse)

if __name__=='__main__':unittest.main()
