import unittest
from types import SimpleNamespace as N
from math import hypot
from undead.micro import Micro
from undead.loot import Loot
from undead.policy import Situation,Action,choose_rule

def dist(a,b):
    a=(a.x,a.y) if hasattr(a,'x') else a
    b=(b.x,b.y) if hasattr(b,'x') else b
    return hypot(a[0]-b[0],a[1]-b[1])

def unit(code,i,x,hp=500):
    return N(type=code,handle=(i,0),x=x,y=0,hp=hp,hp_max=600,is_hero=code[0].isupper(),
             xp=0,level=1,mana=200,mana_max=300,item_addrs=[])

class LocalMicroTests(unittest.TestCase):
    def test_focus_fired_dk_pulls_back_and_fiends_keep_fighting(self):
        dk=unit('Udea',1,200,300)
        fiends=[unit('ucry',2,0),unit('ucry',3,-100)]
        enemy=unit('hfoo',4,350)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,*fiends],[enemy],10,lambda e:dk.handle,dist,lambda *p:True,(-2000,0))
        self.assertEqual(set(moves),{dk.handle})
        self.assertLess(moves[dk.handle][0],dk.x)
        self.assertNotEqual(choose_rule(Situation(10,hero_health=.1,army_hp=1800,local_enemy_hp=500)),Action.RETREAT)

    def test_other_hero_only_pulls_when_dk_cannot_afford_coil(self):
        dk=unit('Udea',1,0);lich=unit('Ulic',2,100,200);enemy=unit('hfoo',3,300)
        micro=Micro(lambda *a,**k:None)
        dk.mana=75
        args=([dk,lich],[enemy],1,lambda _:lich.handle,dist,lambda *p:True,(-2000,0))
        self.assertFalse(micro.plan(*args))
        dk.mana=74
        self.assertIn(lich.handle,micro.plan(*args))
        dk.mana=75
        self.assertFalse(micro.plan(*args))

    def test_low_fiend_pulls_without_coil_but_summons_do_not(self):
        dk=unit('Udea',1,0);dk.mana=0
        fiend=unit('ucry',2,100,80);enemy=unit('hfoo',3,300)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,fiend],[enemy],1,lambda _:fiend.handle,dist,lambda *p:True,(-2000,0))
        self.assertIn(fiend.handle,moves)
        self.assertGreater(dist(moves[fiend.handle],enemy),700)
        dk.mana=75
        self.assertFalse(micro.plan([dk,fiend],[enemy],2,lambda _:fiend.handle,dist,lambda *p:True,(-2000,0)))
        dk.mana=0;fiend.type='uske'
        self.assertFalse(micro.plan([dk,fiend],[enemy],3,lambda _:fiend.handle,dist,lambda *p:True,(-2000,0)))

    def test_losing_fight_can_retreat_as_a_group(self):
        self.assertEqual(choose_rule(Situation(10,hero_health=.9,army_hp=1000,local_enemy_hp=2200)),Action.RETREAT)
        self.assertEqual(choose_rule(Situation(10,army_hp=2000,local_enemy_hp=1000,army_health=.4,recent_losses=2)),Action.RETREAT)

    def test_unit_returns_to_group_when_no_longer_attacked(self):
        dk=unit('Udea',1,100,200); ally=unit('ucry',2,0);foe=unit('hfoo',3,300)
        micro=Micro(lambda *a,**k:None)
        micro.plan([dk,ally],[foe],1,lambda _:dk.handle,dist,lambda *p:True,(-2000,0))
        foe.x=1200
        moves=micro.plan([dk,ally],[foe],5,lambda _:None,dist,lambda *p:True,(-2000,0))
        self.assertFalse(moves)

    def test_early_creeping_dk_fights_until_low_but_late_battle_pulls_on_hit(self):
        dk=unit('Udea',1,0,550);ally=unit('ucry',2,-100);enemy=unit('nmrl',3,100)
        micro=Micro(lambda *a,**k:None)
        args=([dk,ally],[enemy],1,lambda _:dk.handle,dist,lambda *p:True,(-2000,0))
        self.assertFalse(micro.plan(*args,creeping=True))
        dk.hp=200
        self.assertIn(dk.handle,micro.plan(*args,creeping=True))
        dk.hp=550
        self.assertIn(dk.handle,Micro(lambda *a,**k:None).plan(*args,creeping=False))

    def test_distant_reinforcement_cannot_disable_hero_escape(self):
        dk=unit('Udea',1,0);dk.mana=0
        lich=unit('Ulic',2,100,100)
        reinforcement=unit('ucry',3,-4000)
        enemy=unit('hfoo',4,300)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,lich,reinforcement],[enemy],1,lambda _:lich.handle,dist,lambda *p:True,(-5000,0))
        self.assertIn(lich.handle,moves)
        self.assertGreater(dist(moves[lich.handle],enemy),dist(lich,enemy))
        self.assertLess(dist(lich,moves[lich.handle]),1100)

    def test_blocked_support_point_uses_reachable_local_escape(self):
        dk=unit('Udea',1,0);ally=unit('ucry',2,-600);enemy=unit('hfoo',3,200)
        micro=Micro(lambda *a,**k:None)
        route=lambda a,b:None if b[0]<-500 else dist(a,b)
        moves=micro.plan([dk,ally],[enemy],1,lambda _:dk.handle,route,lambda *p:True,(-5000,0))
        self.assertIn(dk.handle,moves)
        self.assertGreater(dist(moves[dk.handle],enemy),dist(dk,enemy))
        self.assertIsNotNone(route((dk.x,dk.y),moves[dk.handle]))

    def test_recent_attrition_retreats_even_when_survivors_are_healthy(self):
        s=Situation(817.78,army_hp=3506.42,local_enemy_hp=4242.41,
                    army_health=.683,recent_losses=3,attack_committed=True,tier=3,lich=True,orb=True,third_hero=True)
        self.assertEqual(choose_rule(s),Action.RETREAT)
        s.local_enemy_hp=1500
        self.assertEqual(choose_rule(s),Action.ATTACK)
        s.local_enemy_hp=4242.41;s.recent_losses=0
        self.assertEqual(choose_rule(s),Action.ATTACK)

class FakeLootGame:
    def __init__(self,code='ratf',full=False):
        self.hero=unit('Udea',1,100)
        self.inv=['rnec']*6 if full else [None]*6
        self.item=N(handle_lo=9,handle_hi=1,type=code,addr=99,x=150,y=0,life=75)
        self.ground=[self.item]
        self.pickups=[]
    def unit(self,h):return self.hero
    def inventory(self,h):return self.inv
    def items_on_ground(self):return self.ground
    def path_distance(self,a,b):return dist(a,b)
    def visible(self,*p):return True
    def dist(self,a,b):return dist(a,b)
    def pick_up(self,h,it):self.pickups.append(it.type);return True

class LootTests(unittest.TestCase):
    def test_normal_drop_requires_free_slot_and_real_inventory_change(self):
        events=[];g=FakeLootGame();loot=Loot({},lambda e,**k:events.append(e))
        self.assertIsNotNone(loot.tick(g,[g.hero],[],1))
        g.ground=[];g.inv[0]='ratf';g.hero.item_addrs=[99]
        loot.tick(g,[g.hero],[],2)
        self.assertIn('loot_confirmed',events)
        g=FakeLootGame(full=True);loot=Loot({},lambda *a,**k:None)
        self.assertIsNone(loot.tick(g,[g.hero],[],1))
        self.assertFalse(g.pickups)

    def test_book_can_be_picked_up_with_full_inventory_and_consumes(self):
        events=[];g=FakeLootGame('texp',full=True)
        loot=Loot({'texp':{'powerup':True}},lambda e,**k:events.append(e))
        self.assertIsNotNone(loot.tick(g,[g.hero],[],1))
        g.ground=[];g.hero.xp+=100
        loot.tick(g,[g.hero],[],2)
        self.assertIn('powerup_confirmed',events)

    def test_enemy_near_drop_prevents_a_hero_running_out_to_loot(self):
        g=FakeLootGame();loot=Loot({},lambda *a,**k:None)
        self.assertIsNone(loot.tick(g,[g.hero],[unit('hfoo',8,300)],1))
        self.assertFalse(g.pickups)

    def test_rejected_or_disappearing_item_is_not_reported_as_collected(self):
        g=FakeLootGame();events=[]
        loot=Loot({},lambda e,**k:events.append(e))
        loot.tick(g,[g.hero],[],1)
        g.ground=[]
        loot.tick(g,[g.hero],[],2)
        self.assertIn('loot_unconfirmed',events)
        self.assertNotIn('loot_confirmed',events)

class ControllerIntegrationTests(unittest.TestCase):
    def test_damaged_dk_moves_back_while_other_units_reach_combat_dispatch(self):
        from undead.controller import Controller
        dk=unit('Udea',1,200,200); fiend=unit('ucry',2,0);fiend2=unit('ucry',3,-100)
        enemy=unit('hfoo',4,350)
        home=unit('unpl',5,-3000)
        own=[dk,fiend,fiend2,home]
        for obj in own:obj.owner=0
        g=N(snapshot=lambda **kw:N(clock=100,in_game=True,units=own),
            my_buildings=lambda *args:[home],map=lambda:N(starts=[],walkable=lambda *p:True),me=lambda:0,
            is_building=lambda u:u.type=='unpl',my_heroes=lambda:[dk],
            units=lambda owner,types:[u for u in own if u.type in types],enemies=lambda:[enemy],
            creeps=lambda:[],my_units=lambda:own,dist=dist,path_distance=dist,
            current_target=lambda e:dk,inventory=lambda h:[None]*6,
            cooldown=lambda *a:1)
        events=[]
        bot=Controller(g,lambda e,**kw:events.append(e))
        bot.economy.tick=lambda *a:None
        bot.scout=lambda *a:None
        bot.skills=lambda *a:None
        bot.items=lambda *a:None
        moves=[];fighters=[]
        bot.go_raw=lambda units,point,now,attack=False:moves.extend(u.handle for u in units)
        bot.creep=lambda units,center,now:fighters.extend(u.handle for u in units)
        bot.tick()
        self.assertIn(dk.handle,moves)
        self.assertNotIn(dk.handle,fighters)
        self.assertEqual(set(fighters),{fiend.handle,fiend2.handle})
        self.assertNotEqual(bot.action,Action.RETREAT)

class BaseLossTests(unittest.TestCase):
    def test_surviving_army_keeps_deciding_without_bypassing_readiness_after_hall_destroyed(self):
        from undead.controller import Controller
        dk=unit('Udea',1,0,600);fiend=unit('ucry',2,50,600)
        old=unit('unp2',3,-3000);zig=unit('uzig',4,-2800)
        own=[dk,fiend,zig]
        for u in own:u.owner=0
        g=N(snapshot=lambda **kw:N(clock=1500,in_game=True,units=own),
            my_buildings=lambda codes=None:[] if codes else [zig],
            map=lambda:N(starts=[],walkable=lambda *p:True),me=lambda:0,
            is_building=lambda u:u.type=='uzig',my_heroes=lambda:[dk],
            units=lambda owner,codes:[u for u in own if u.type in codes],
            enemies=lambda:[],creeps=lambda:[],my_units=lambda:own,
            dist=dist,path_distance=dist,current_target=lambda u:None,
            inventory=lambda u:['stwp']+[None]*5,cooldown=lambda *a:1)
        events=[];orders=[];b=Controller(g,lambda e,**kw:events.append(e))
        b.home=old;b.enemy_main=(5000,0);b.attack_committed=True
        b.economy.tick=lambda *a:None;b.scout=lambda *a:None;b.skills=lambda *a:None
        b.items=lambda *a:None;b.loot.tick=lambda *a:None
        b.creep=lambda army,*a:orders.extend(u.handle for u in army)
        b.advance_attack=lambda *a:self.fail("missing hall and heroes must block assault")
        b.tick()
        self.assertEqual(b.situation.now,1500)
        self.assertEqual(b.situation.tier,0)
        self.assertIs(b.home,zig)
        self.assertEqual(b.action,Action.CREEP)
        self.assertEqual(set(orders),{dk.handle,fiend.handle})
        self.assertIn('base_hall_missing',events)

class HealingTests(unittest.TestCase):
    def test_heal_precedes_damage_and_movement_cannot_cancel_cast(self):
        from undead.controller import Controller
        dk=unit('Udea',1,0);fiend=unit('ucry',2,50,100)
        statue=unit('uobs',3,50,20);dark=unit('Nbrn',4,40,400)
        enemy=unit('hfoo',5,200);own=[dk,fiend,statue,dark]
        casts=[];moves=[];attacks=[]
        g=N(units=lambda owner,codes:[u for u in own if u.type in codes],dist=dist,
            cooldown=lambda *a:0,cast=lambda u,spell,target:casts.append((spell,target.type)) or True,
            unit=lambda h:next((u for u in own if u.handle==h),None),is_building=lambda u:False,
            current_target=lambda u:None,attack=lambda u,*a,**k:attacks.append(u.handle) or True,
            move=lambda u,*p:moves.append(u.handle) or True)
        bot=Controller(g,lambda *a,**k:None)
        self.assertEqual({u.type for u in bot.heal_candidates(dk)},{'ucry','Nbrn'})
        bot.heal_allies(own,10)
        bot.fight([dk,fiend],[enemy],10)
        bot.go_raw([dk],(-100,0),10)
        self.assertEqual(casts,[('deathcoil','Nbrn')])
        self.assertNotIn(dk.handle,moves)
        self.assertNotIn(dk.handle,attacks)
        self.assertIn(fiend.handle,attacks)
        bot.go_raw([dk],(-100,0),11)
        self.assertIn(dk.handle,moves)
        dk.mana=74
        bot.heal_allies(own,12)
        self.assertEqual(casts,[('deathcoil','Nbrn')])

if __name__=='__main__':unittest.main()
