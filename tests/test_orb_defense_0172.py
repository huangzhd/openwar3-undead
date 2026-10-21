import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_battle_shop_0163 as shopping
import test_combat_focus as focus
import test_opening_safety_0131 as tick_fixture
import test_dark_ranger_tanking as tanking
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.policy import Action,Situation

class OrbDefenseTests(unittest.TestCase):
    def test_neutrals_cannot_stop_independent_departure_purchase_or_delivery(self):
        g,b,s,events=shopping.ShoppingTests().make()
        creep=unit('nogr',90,1950);creep.owner=12
        b.micro.dk_support=dict(handle=g.dk.handle,point=(1900,0))
        for t in (500,501,504):
            self.assertEqual(s.orb_tick(b,g.heroes,[creep],t,3),{g.dk.handle})
            self.assertIsNotNone(s.orb)
        self.assertTrue(all(o[1]=='Udea' for o in g.orders))
        g.dk.x=0;s.orb_tick(b,g.heroes,[creep],507,3);s.observe(g,508)
        self.assertIn('ocor',g.inventory(g.dk))
        g.dk.x=g.lich.x;s.orb_tick(b,g.heroes,[creep],511,3);s.observe(g,512)
        s.orb_tick(b,g.heroes,[creep],515,3)
        self.assertIn('ocor',g.inventory(g.lich));self.assertIsNone(s.orb)

    def test_real_dk_danger_releases_then_safe_state_can_retry_promptly(self):
        for danger in ('enemy','pull','defense'):
            with self.subTest(danger=danger):
                g,b,s,events=shopping.ShoppingTests().make();s.orb_tick(b,g.heroes,[],500,3)
                foe=unit('hfoo',90,2000);foe.owner=1
                hostiles=[foe] if danger=='enemy' else []
                if danger=='pull':
                    b.micro.pulling.add(g.dk.handle);foe.owner=12;hostiles=[foe]
                    g.current_target=lambda u:g.dk if u is foe else None
                if danger=='defense':b.action=Action.DEFEND
                self.assertFalse(s.orb_tick(b,g.heroes,hostiles,501,3));self.assertIsNone(s.orb)
                b.micro.pulling.clear();b.action=Action.CREEP
                self.assertFalse(s.orb_tick(b,g.heroes,[],502,3))
                self.assertEqual(s.orb_tick(b,g.heroes,[],507,3),{g.dk.handle})

    def test_archived_defense_frame_leaves_neutrals_and_preserves_casts(self):
        frame=json.loads((Path(__file__).parent/'fixtures/lr-defense-creeps-0171.json').read_text())
        army=[N(**{**u,'handle':tuple(u['handle']),'is_hero':u['type'][0].isupper()}) for u in frame['army']]
        orders=[];g=N(dist=dist,move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True,me=lambda:0)
        b=Controller(g,lambda *a,**k:None);b.home=N(x=-3904,y=-3968);b.action=Action.DEFEND
        b.battle_enemies=[unit('ngst',99,-700)];b.battle_enemies[0].owner=12
        raid=unit('Udea',100,-3100);raid.owner=1;raid.y=-3968
        b.cast_until[army[0].handle]=624
        b.defend_base(army,[raid],622.555)
        self.assertEqual({o[1] for o in orders},{u.handle for u in army[1:]})
        self.assertTrue(all(o[2]==(-3904,-3968) for o in orders))

    def test_arrived_defenders_attack_player_and_ignore_carrier_creep(self):
        b,f,d,s,h,e,army,foes,orders,targets,events=focus.CombatFocusTests().make()
        b.action=Action.DEFEND;b.home=N(x=-400,y=0)
        creep=unit('nogr',80,100,1);creep.owner=12;b.battle_enemies=[creep]
        b.creeping.drop_bindings[creep.handle]=True
        targets[f.handle]=creep;targets[d.handle]=creep
        b.defend_base(army,[e],10)
        self.assertIs(targets[f.handle],e);self.assertIs(targets[d.handle],e)
        b.fight(army,[creep],13)
        self.assertFalse(any(o[0]=='attack' and o[2]==creep.handle for o in orders))

    def test_full_tick_base_raid_preempts_camp_support_and_equipment(self):
        g,b,dk,allies,orders,clock=tick_fixture.EmergencyTests().controller()
        dk.hp=dk.hp_max;dk.mana=0;g.abilities=lambda u:[]
        for u in allies:u.hp=u.hp_max
        foe=g.enemies()[0];foe.x=-4500;foe.hp=300;foe.visible_to=lambda me:True
        creep=unit('nogr',90,100,300);creep.owner=12
        g.creeps=lambda:[creep];g.current_target=lambda u:creep if u in [dk,*allies] else None
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        b.micro.plan=lambda *a,**kw:{};b.shields.plan=lambda *a:{}
        b.emergency_portal=lambda *a:False;b.combat_spells=lambda *a:None;b.frost_armor=lambda *a:None
        b.recruit_tavern=lambda *a:set();b.stop_hero_chases=lambda *a:None
        b.support_dk=lambda *a:orders.append(('wrong_support',)) or True
        b.creep=lambda *a:orders.append(('wrong_creep',))
        b.equipment.tick=lambda *a:orders.append(('wrong_equipment',)) or True
        b.tick()
        self.assertEqual(b.action,Action.DEFEND)
        self.assertEqual({o[1] for o in orders if o[0]=='move'},{u.handle for u in [dk,*allies]})
        self.assertTrue(all(o[0]=='move' and o[2]==(-5000,0) for o in orders))

    def test_creep_attacks_survive_next_tick_and_late_fiend_joins(self):
        b,f,d,s,h,e,army,foes,orders,targets,events=focus.CombatFocusTests().make()
        b.action=Action.CREEP;b.home=N(x=-3000,y=0);b.opening_rod_finished=True
        creep=unit('nogr',80,300,500);creep.owner=12
        b.creeping.active=dict(id='test',kind='ogre',x=300,y=0)
        b.creeping.choose=lambda *a:((300,0),[creep])
        b.creeping.tier=1;b.situation=Situation(300,tier=1)
        b.g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or targets.pop(u.handle,None) or True
        late=unit('ucry',100,-2000,550);late.owner=0;army.append(late)
        b.creep(army,(0,0),300);self.assertIs(targets[f.handle],creep)
        b.creep(army,(0,0),303);self.assertIs(targets[f.handle],creep)
        self.assertFalse(any(o[0]=='move' and o[1] in {f.handle,d.handle} for o in orders))
        self.assertTrue(any(o[0]=='move' and o[1]==late.handle for o in orders))

    def test_dk_waits_for_slower_skeletons_before_aggro_with_bounded_wait(self):
        b,dk,sk,e,attacks,holds,targets,events=tanking.SkeletonOpeningTests().setup_fight()
        dk.x=-300;sk.x=-600;e.x=500
        moves=[];b.go_raw=lambda us,p,t:moves.extend((u.handle,p) for u in us)
        self.assertTrue(b.skeleton_opening([dk,sk],[e],190))
        self.assertFalse(attacks);self.assertIn(sk.handle,[h for h,p in moves])
        sk.x=-300
        self.assertTrue(b.skeleton_opening([dk,sk],[e],191))
        self.assertEqual(attacks,[(sk.handle,e.handle)]);self.assertIn(dk.handle,holds)
        self.assertTrue(b.skeleton_opening([dk,sk],[e],192))
        targets[e.handle]=sk;e.hp-=12
        self.assertFalse(b.skeleton_opening([dk,sk],[e],193))
        targets.clear();self.assertFalse(b.skeleton_opening([dk,sk],[e],197))

if __name__=='__main__':unittest.main()
