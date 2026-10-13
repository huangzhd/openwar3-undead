import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_battle_shop_0163 as trading
import test_consumables as consumables
from undead.controller import Controller,ground_attack_range
from undead.consumables import Consumables
from undead.creeping import Creeping
from undead.micro import Micro
from undead.policy import Action,Situation
from undead.retreat import escape_point,clearance

class DefenseTests(unittest.TestCase):
    def make(self):
        g,b,s,events=trading.ShoppingTests().make()
        b.home=N(x=0,y=0);b.action=Action.DEFEND;b.situation.threatened=True
        g.dk.x=0;g.lich.x=600;g.dark.x=650;g.dk.mana=0
        g.walk_path=lambda a,z:[z]
        return g,b,s,events

    def test_enemy_on_lich_does_not_block_safe_dk_mana_purchase(self):
        g,b,s,_=self.make();foe=unit('ugho',90,900)
        reserved=s.defend_tick(b,[foe],500,3)
        self.assertIn('pman',g.inventory(g.dk));self.assertEqual(reserved,{g.dk.handle})
        self.assertFalse(any(o[0] in ('move','group') for o in g.orders))

    def test_orb_bought_at_home_and_transferred_without_sending_army(self):
        g,b,s,_=self.make();g.dk.mana=100;g.lich.x=100;g.dark.x=200
        s.defend_tick(b,[],500,3);s.observe(g,502)
        s.defend_tick(b,[],504,3);s.observe(g,506)
        self.assertIn('ocor',g.inventory(g.lich))
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),1)
        self.assertFalse(any(o[0]=='group' for o in g.orders))

    def test_purchase_blockers_preserve_revival_and_do_not_cross_enemy(self):
        for mode in ('revive','gold','stock','blocked','enemy','full'):
            g,b,s,_=self.make();g.bags[g.lich.handle][0]='ocor';now=500;foes=[]
            if mode=='revive':g.pending_heroes={'Nbrn'}
            if mode=='gold':g.gold=199
            if mode=='stock':now=400
            if mode=='blocked':g.path_distance=lambda *a:None
            if mode=='enemy':foes=[unit('ucry',90,100)]
            if mode=='full':g.bags[g.dk.handle]=['rat6']*6
            s.defend_tick(b,foes,now,3)
            self.assertFalse(g.orders,mode)

    def test_wrong_recipient_does_not_trigger_duplicate_mana_buy(self):
        g,b,s,_=self.make();g.lich.x=100;g.bags[g.lich.handle][0]='pman'
        s.defend_tick(b,[],500,3)
        self.assertIn('pman',g.inventory(g.dk));self.assertFalse(any(o[0]=='buy' for o in g.orders))

    def test_unconfirmed_purchase_and_stalled_travel_are_bounded(self):
        g,b,s,_=self.make();g.buy=lambda sh,c:g.orders.append(('buy',c)) or True
        for now in range(500,532,4):s.observe(g,now);s.defend_tick(b,[],now,3)
        self.assertEqual(sum(o[0]=='buy' for o in g.orders),3)
        g,b,s,_=self.make();g.dk.x=500
        for now in (500,505,513,514):s.defend_tick(b,[],now,3)
        self.assertEqual(sum(o[0]=='move' for o in g.orders),2)

    def test_mana_consumption_then_coil_prefers_wounded_lich(self):
        g=consumables.Game();g.effect=True;dk,lich,_=g.heroes;dk.mana=0
        dk.hp=600;lich.hp=200;g.bags[dk.handle][0]='pman'
        g.units=lambda side,codes:[u for u in g.army if u.type in codes]
        g.cast=lambda h,spell,target:g.orders.append(('coil',target.type)) or True
        b=Controller(g,lambda *a,**kw:None)
        c=Consumables(lambda *a,**kw:None);c.tick(g,g.army,[],500,b.cast_until,coil_needed=True)
        b.player_contact=[unit('hfoo',90,100)]
        c.observe(g,502);b.heal_allies(g.army,502)
        self.assertEqual(dk.mana,150);self.assertIn(('coil','Ulic'),g.orders)

    def test_supplied_dk_must_rejoin_before_departure(self):
        import test_late_defense_0164 as recovery
        g,b,army,dk,lich,moves=recovery.RecoveryTests().make()
        g.bags[dk.handle][0]='stwp';dk.x=2000
        self.assertFalse(b.prepare_attack(army,500));self.assertTrue(moves)
        dk.x=lich.x
        self.assertTrue(b.prepare_attack(army,502))

    def test_healthy_dk_does_not_redirect_whole_defense(self):
        dk=unit('Udea',1,0,600);g=N(unit=lambda h:dk)
        b=Controller(g,lambda *a,**kw:None);b.situation=Situation(500,threatened=True)
        b.micro.dk_support=dict(handle=dk.handle,point=(1000,0),gap=900)
        self.assertFalse(b.support_dk([unit('ucry',2,0)],500))

class EscapeTests(unittest.TestCase):
    def test_wounded_lich_does_not_resume_attack_during_damage_sample_gap(self):
        dk=unit('Udea',1,-100);dk.mana=0;lich=unit('Ulic',2,0,354)
        foe=unit('ugho',3,100);m=Micro(lambda *a,**kw:None);m.pulling.add(lich.handle)
        moves=m.plan([dk,lich],[foe],616.23,lambda e:lich.handle,dist,lambda *p:True,(-1000,0))
        self.assertIn(lich.handle,moves);self.assertLess(moves[lich.handle][0],lich.x)

    def test_blocked_lich_remains_reserved_instead_of_rejoining_attack(self):
        dk=unit('Udea',1,-100);dk.mana=0;lich=unit('Ulic',2,0,100);foe=unit('ugho',3,100)
        moves=Micro(lambda *a,**kw:None).plan([dk,lich],[foe],1,lambda e:lich.handle,lambda *a:None,lambda *p:False,(-1000,0))
        self.assertEqual(moves[lich.handle],(0,0))

    def test_homeward_escape_keeps_actual_route_safety(self):
        lich=unit('Ulic',1,0,100);foe=unit('ugho',2,150)
        g=N(dist=dist,path_distance=dist,walk_path=lambda a,z:[z],map=lambda:N(walkable=lambda *p:True))
        p=escape_point(g,lich,[foe],ground_attack_range,home=(-1000,0))
        self.assertLess(p[0],0);self.assertGreater(clearance(p,[foe],ground_attack_range),200)
        g.walk_path=lambda a,z:[(150,0),z]
        self.assertIsNone(escape_point(g,lich,[foe],ground_attack_range,home=(-1000,0)))

class RouteTests(unittest.TestCase):
    def test_home_shop_beats_closer_enemy_camp_during_orb_supply(self):
        camps=[dict(id='home',kind='shop',x=-2000,y=0,hp=1000,max_level=5,difficulty=10),
               dict(id='enemy',kind='neutral',x=1000,y=0,hp=500,max_level=3,difficulty=5)]
        g=N(map=lambda:N(starts=[(-3000,0),(3000,0)]),creeps=lambda:[],dist=dist,path_distance=dist,visible=lambda *a:False)
        c=Creeping(lambda *a,**kw:None,camps);c.resupply_home=True;c.tier=3;c.active=camps[1]
        army=[unit('Ulic',1,0,600),unit('uobs',2,0,600),unit('ucry',3,0,600)]
        point,_=c.choose(g,army,(700,0),N(x=-3000,y=0),500)
        self.assertEqual(point,(-2000,0));self.assertIn('enemy',c.deferred)
        c.cleared.add('home');c.active=None
        self.assertIsNone(c.choose(g,army,(700,0),N(x=-3000,y=0),501)[0])

if __name__=='__main__':unittest.main()
