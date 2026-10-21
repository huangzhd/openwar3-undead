import unittest
from types import SimpleNamespace as N
from test_formation import u
from test_baseline import unit
from test_micro_loot import dist
import test_al_entry_01169 as entry
from undead.formation import Formation
from undead.controller import Controller
from undead.policy import Action
from undead.structures import is_structure


class MarchExpansionTests(unittest.TestCase):
    def test_al_shop_joiner_enters_current_segment_without_dragging_dk_back(self):
        # 204919, 245.300 -> 251.030: the arriving fiend used to return to -1728.
        dk=u('Udea',-666,-3372,1);fiend=u('ucry',-1225,-3413,2)
        route=[(-1728,-3904),(-1216,-3392),(-448,-3392),(64,-2880),(1728,-2880),(2176,-3050)]
        f=Formation(lambda *a,**k:None);f.route=route.copy();f.objective=route[-1]
        f.known={dk.handle,fiend.handle};f.joiners={fiend.handle};f.cursors={dk.handle:2}
        f.last_plan=245;f.last_progress=245
        path=lambda a,b:self.fail('Joining must not rebuild the main route')
        orders=f.plan([dk,fiend],route[-1],245.3,dist,path)
        self.assertEqual(orders[1][1],(dk.x,dk.y))
        dk.x,dk.y=332,-2881;fiend.x,fiend.y=-129,-2983
        orders=f.plan([dk,fiend],route[-1],251.03,dist,path)
        self.assertTrue(all(p[0]>obj.x and not hold for obj,p,hold in orders))
        self.assertFalse(f.aura_wait);self.assertNotIn(fiend.handle,f.joiners)
        dk.x,dk.y=700,-2880;fiend.x,fiend.y=300,-2900
        orders=f.plan([dk,fiend],route[-1],253,dist,path)
        self.assertTrue(all(p[0]>obj.x for obj,p,_ in orders));self.assertFalse(f.aura_wait)
        self.assertEqual(f.route,route)

    def test_merc_melee_guard_arrival_releases_attack_while_ranged_guard_stays_back(self):
        pull,b,army,ranged,orders,events=entry.MercenaryPullTests().scene()
        # Actual 204919 camp geometry: nsqt reaches the rear before nfsh moves far.
        b.creeping.active.update(x=1100,y=-1200)
        for obj in army:obj.x,obj.y=-144,-492
        ranged.x,ranged.y=877,-1260
        melee=unit('nsqt',90,owner=12,x=1060);melee.y=-1146
        b.g.creeps=lambda:[ranged,melee]
        self.assertTrue(pull.tick(b,army,510.95))
        ranged.hp-=10
        self.assertTrue(pull.tick(b,army,516.33))
        orders.clear()
        # Merely standing near the rendezvous without displacement cannot release it.
        self.assertTrue(pull.tick(b,army,517));self.assertTrue(orders)
        melee.x,melee.y=630,-854;orders.clear()
        self.assertFalse(pull.tick(b,army,521.025));self.assertFalse(orders)
        self.assertEqual(events[-1]['reason'],'guard_pulled_observed')
        self.assertFalse(pull.tick(b,army,522))

    def scene(self):
        g=N(me=lambda:0,dist=dist,path_distance=dist,visible=lambda *p:False)
        b=Controller(g,lambda *a,**k:None);b.enemy_main=(10000,0);b.home=N(x=0,y=0)
        moves=[];b.go=lambda army,p,now,**kw:moves.append((p,kw));b.fight=lambda *a:None
        return b,g,moves

    def test_all_races_observed_expansion_supersedes_main_and_old_target(self):
        for code in ('htow','hkee','hcas','ogre','ostr','ofrt','unpl','unp1','unp2','ugol','etol','etoa','etoe','egol'):
            with self.subTest(code=code):
                b,g,moves=self.scene();main=unit('htow',1,x=10000);mine=unit(code,2,x=4000)
                b.memory.update([main,mine],0,0,is_structure);b.attack_target=main.handle;b.attacking_main=True
                b.advance_attack([],[],(9500,0),1)
                self.assertEqual(moves[-1][0],(4000,0));self.assertTrue(moves[-1][1]['travel'])
                self.assertFalse(b.attacking_main);self.assertEqual(b.attack_target,mine.handle)
                self.assertIn('已侦察分矿',b.intent)

    def test_nearest_reachable_observed_expansion_then_keep_it_until_fair_destruction(self):
        b,g,moves=self.scene()
        sites=[unit('htow',1,x=10000),unit('ugol',2,x=2000),unit('etol',3,x=4000),
               unit('htow',4,x=1000,visible=False),unit('ngol',5,owner=15,x=500),unit('etrp',6,x=600)]
        b.memory.update(sites,0,0,is_structure)
        g.path_distance=lambda a,p:None if p==(2000,0) else dist(a,p)
        b.advance_attack([],[],(0,0),1);self.assertEqual(moves[-1][0],(4000,0))
        g.path_distance=dist
        b.advance_attack([],[],(0,0),2);self.assertEqual(moves[-1][0],(4000,0))
        g.visible=lambda *p:True
        b.advance_attack([],[],(4000,0),3);self.assertEqual(moves[-1][0],(2000,0))
        b.advance_attack([],[],(2000,0),4);self.assertNotEqual(moves[-1][0],(2000,0))
        self.assertNotIn(sites[3].handle,b.memory.units)

    def test_local_main_siege_cannot_override_distant_expansion(self):
        b,g,moves=self.scene();b.action=Action.ATTACK
        mine=unit('ugol',2,x=4000);main=unit('htow',1,x=10000)
        b.memory.update([main,mine],0,0,is_structure)
        army=[unit('Udea',3,owner=0,x=9500)]
        b.siege.choose=lambda *a:self.fail('Do not reacquire main siege before travelling')
        self.assertFalse(b.focus_siege(army,[main],1))
        b.advance_attack(army,[main],(9500,0),1)
        self.assertEqual(moves[-1][0],(4000,0))

    def test_travel_releases_existing_main_attack_and_moves_existing_army(self):
        b,g,_=self.scene();b.action=Action.ATTACK
        main=unit('htow',1,x=9800);mine=unit('ugol',2,x=4000)
        army=[unit('Udea',3,owner=0,x=9500),unit('ucry',4,owner=0,x=9400)]
        b.memory.update([main,mine],0,0,is_structure);b.battle_enemies=[main]
        g.current_target=lambda obj:main;g.walk_path=lambda a,p:[p]
        orders=[];b.go=Controller.go.__get__(b)
        b.go_raw=lambda units,p,now,attack=False:orders.extend((obj.handle,p,attack) for obj in units)
        b.advance_attack(army,[main],(9500,0),1)
        self.assertEqual({h for h,p,a in orders},{obj.handle for obj in army})
        self.assertTrue(all(p==(4000,0) and not attack for h,p,attack in orders))

    def test_idle_main_workers_do_not_pin_army_but_real_contacts_still_intercept(self):
        b,g,_=self.scene();b.action=Action.ATTACK
        mine=unit('ugol',2,x=4000);army=[unit('Udea',3,owner=0,x=9500)]
        worker=unit('ewsp',4,x=9600);soldier=unit('earc',5,x=9600)
        b.memory.update([mine],0,0,is_structure);b.player_contact=[worker]
        g.current_target=lambda obj:None
        self.assertFalse(b.respond_player_contact(army,1));self.assertFalse(b.player_contact)
        intercepted=[];b.focus_siege=lambda army,foes,now:intercepted.extend(foes) or True
        for enemy in (worker,soldier):
            b.player_contact=[enemy];g.current_target=lambda obj:army[0] if obj is worker else None
            self.assertTrue(b.respond_player_contact(army,2))
            self.assertIn(enemy,intercepted)


if __name__=='__main__':unittest.main()
