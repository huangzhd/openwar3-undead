import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.micro import Micro
from undead.scouting import SkeletonScouts
from undead.policy import Action


class LichTacticsTests(unittest.TestCase):
    def test_lich_holds_damage_position_unless_low_and_coil_unavailable(self):
        dk=unit('Udea',1,0);lich=unit('Ulic',2,100);enemy=unit('ogru',3,200)
        for hp,mana,ready,dk_x,pull in [(400,0,False,0,False),(269,75,True,0,False),
                                      (269,74,True,0,True),(269,75,False,0,True),
                                      (269,75,True,-1000,True),(270,0,False,0,False)]:
            with self.subTest(hp=hp,mana=mana,ready=ready,dk_x=dk_x):
                lich.hp=hp;dk.mana=mana;dk.x=dk_x
                micro=Micro(lambda *a,**kw:None)
                moves=micro.plan([dk,lich],[enemy],1,lambda _:lich.handle,dist,lambda *p:True,
                                 (-3000,0),coil_ready=ready)
                self.assertEqual(lich.handle in moves,pull)

    def test_healing_priority_overrides_health_ratio_and_then_uses_ratio_within_type(self):
        dk=unit('Udea',1,0);lich=unit('Ulic',2,100,300);dark=unit('Nbrn',3,100,120)
        fiend=unit('ucry',4,150,70);ghoul=unit('ugho',5,160,10);other_fiend=unit('ucry',6,160,50)
        own=[lich,dark,fiend,ghoul,other_fiend];casts=[]
        g=N(units=lambda side,codes:[u for u in own if u.type in codes],dist=dist,
            cooldown=lambda *a:0,cast=lambda h,order,target:casts.append(target) or True,
            unit=lambda h:next((u for u in own if u.handle==h),None))
        b=Controller(g,lambda *a,**kw:None)
        b.player_contact=[unit('hfoo',90,100)]
        expected=[lich,dark,other_fiend,fiend,ghoul]
        for now,target in enumerate(expected,1):
            b.heal_allies([dk,*own],now*5)
            self.assertIs(casts[-1],target)
            target.hp=target.hp_max


class SkeletonScoutTests(unittest.TestCase):
    def setup(self,count=4):
        own=[unit('uske',i,i*30) for i in range(1,count+1)]
        g=N(units=lambda side,codes:[u for u in own if u.type in codes],dist=dist,
            path_distance=dist,visible=lambda *p:True,is_building=lambda u:True)
        events=[];scouts=SkeletonScouts(lambda event,**kw:events.append((event,kw)))
        return scouts,g,own,events

    def plan(self,s,g,now=0,active=True,enemies=()):
        return s.plan(g,(0,0),(-5000,0),(500,0),[(3000,0),(0,4000)],enemies,now,active)

    def test_two_front_skeletons_stay_and_two_spares_visit_distinct_expansions(self):
        s,g,own,_=self.setup();orders=self.plan(s,g)
        self.assertEqual({u.handle for u,p in orders},{own[2].handle,own[3].handle})
        self.assertEqual(len({p for u,p in orders}),2)
        self.assertFalse({own[0].handle,own[1].handle}&set(s.assignments))

    def test_no_spares_or_no_main_assault_does_not_send_scouts(self):
        s,g,_,_=self.setup(2);self.assertFalse(self.plan(s,g))
        s,g,_,_=self.setup(4);self.assertFalse(self.plan(s,g,active=False))

    def test_scout_observes_only_provided_visible_enemy_and_fog_does_not_clear_site(self):
        s,g,own,events=self.setup(3);scout,point=self.plan(s,g)[0]
        scout.x,scout.y=point;g.visible=lambda *p:False
        self.plan(s,g,1,False)
        self.assertFalse(s.checked)
        self.assertFalse(any(e=='skeleton_scout_structure_seen' for e,_ in events))
        enemy=unit('etol',20,point[0]);enemy.y=point[1]
        g.visible=lambda *p:True;self.plan(s,g,2,False,[enemy])
        self.assertIn(point,s.checked)
        seen=[r for e,r in events if e=='skeleton_scout_structure_seen']
        self.assertEqual([r['handle'] for r in seen],[enemy.handle])
        self.assertFalse(s.assignments)

    def test_expiry_is_bounded_and_new_game_resets_sites(self):
        s,g,own,_=self.setup(3)
        # A repeatedly lost scout cannot consume new skeletons forever.
        for now in range(6):
            self.plan(s,g,now)
            for h in list(s.assignments):
                own[:]=[u for u in own if u.handle!=h]
            own.append(unit('ndr2',100+now,120))
        self.assertTrue(all(attempts<=2 for attempts in s.attempts.values()))
        self.assertFalse(s.assignments)
        fresh=SkeletonScouts(lambda *a,**kw:None)
        self.assertTrue(self.plan(fresh,g,10))

    def test_scouted_expansion_overrides_main_assault_and_survives_main_destruction(self):
        main=unit('etol',20,10000);main.owner=1;main.building=True;main.at=0
        expansion=unit('etol',21,7000);expansion.owner=1;expansion.building=True;expansion.at=0
        g=N(me=lambda:0,dist=dist,is_building=lambda u:True,visible=lambda *p:False,
            units=lambda *a:[])
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=0,y=0);b.enemy_main=(10000,0)
        b.attacking_main=True;b.memory.units={main.handle:main,expansion.handle:expansion}
        moves=[];b.go=lambda army,p,now,**kw:moves.append(p);b.fight=lambda *a:None
        b.advance_attack([],[],(7800,0),1)
        self.assertEqual(moves[-1],(7000,0))
        # Destroying the main does not invalidate the still-observed expansion.
        del b.memory.units[main.handle];g.visible=lambda *p:True
        b.advance_attack([],[expansion],(10000,0),2)
        self.assertEqual(moves[-1],(7000,0))

if __name__=='__main__':unittest.main()
