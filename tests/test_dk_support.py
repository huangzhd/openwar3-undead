import unittest
from types import SimpleNamespace as N
from math import hypot
from undead.micro import Micro,DK_SUPPORT_DISTANCE
from undead.controller import Controller
from undead.policy import Action
from test_micro_loot import unit,dist


class DkSupportTests(unittest.TestCase):
    def test_repeated_chase_cannot_walk_dk_away_from_stationary_army(self):
        dk=unit('Udea',1,0);allies=[unit('ucry',2,-100),unit('ucry',3,-150)]
        enemy=unit('ogru',4,100)
        micro=Micro(lambda *a,**k:None)
        travelled=0
        for now in range(40):
            enemy.x=dk.x+100;enemy.y=dk.y
            moves=micro.plan([dk,*allies],[enemy],now,lambda _:dk.handle,dist,lambda *p:True,(-5000,0),lambda _:100)
            self.assertIn(dk.handle,moves)
            point=moves[dk.handle]
            self.assertLessEqual(dist(point,allies[0]),DK_SUPPORT_DISTANCE+50)

            dx,dy=point[0]-dk.x,point[1]-dk.y
            scale=min(1,120/max(1,hypot(dx,dy)))
            dk.x+=dx*scale;dk.y+=dy*scale
            travelled+=hypot(dx*scale,dy*scale)
        self.assertGreater(travelled,120)

    def test_chased_dk_outside_support_cannot_keep_fleeing_away(self):
        dk=unit('Udea',1,2000);allies=[unit('ucry',2,0),unit('ucry',3,-100)]
        enemy=unit('ogru',4,1900)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,*allies],[enemy],1,lambda _:dk.handle,dist,lambda *p:True,(-5000,0),lambda _:100)
        self.assertLessEqual(dist(moves[dk.handle],allies[0]),dist(dk,allies[0]))
        self.assertIsNotNone(micro.dk_support)

    def test_separated_dk_keeps_moving_toward_help_when_pursuer_blocks_rejoin(self):
        dk=unit('Udea',1,2000);ally=unit('ucry',2,0);enemy=unit('ogru',3,1900)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,ally],[enemy],1,lambda _:dk.handle,dist,lambda *p:True,(-5000,0),lambda _:600)
        self.assertLess(dist(moves[dk.handle],ally),dist(dk,ally)-40)
        self.assertIsNotNone(micro.dk_support)

    def test_ground_detour_rejects_apparently_close_escape(self):
        dk=unit('Udea',1,0);ally=unit('ucry',2,100);enemy=unit('ogru',3,200)
        # Woods make every candidate more separated by ground despite nearby XY.
        route=lambda a,b:2000+dist(a,b) if tuple(b)==(ally.x,ally.y) else dist(a,b)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,ally],[enemy],1,lambda _:dk.handle,route,lambda *p:True,(-5000,0),lambda _:100)
        point=moves[dk.handle]
        self.assertTrue(point==(dk.x,dk.y) or route(point,(ally.x,ally.y))<route((dk.x,dk.y),(ally.x,ally.y))-40)
        self.assertIsNotNone(micro.dk_support)

    def test_safe_dk_rejoins_before_resuming_objective_even_without_hostiles(self):
        dk=unit('Udea',1,-1500);ally=unit('ucry',2,0)
        micro=Micro(lambda *a,**k:None);micro.dk_recovering=dk.handle
        moves=micro.plan([dk,ally],[],10,lambda _:None,dist,lambda *p:True,(-5000,0))
        self.assertEqual(moves[dk.handle],(ally.x,ally.y))
        self.assertEqual(micro.dk_support['point'],(dk.x,dk.y))
        dk.x=-500
        self.assertFalse(micro.plan([dk,ally],[],11,lambda _:None,dist,lambda *p:True,(-5000,0)))
        self.assertIsNone(micro.dk_support)
        self.assertIsNone(micro.dk_recovering)

    def test_unreachable_support_holds_and_requests_escort_then_recovers(self):
        dk=unit('Udea',1,0);ally=unit('ucry',2,-100);enemy=unit('ogru',3,100)
        micro=Micro(lambda *a,**k:None)
        moves=micro.plan([dk,ally],[enemy],1,lambda _:dk.handle,lambda *a:None,lambda *p:True,(-5000,0))
        self.assertEqual(moves[dk.handle],(dk.x,dk.y))
        self.assertEqual(micro.dk_support['reason'],'blocked_escape')
        self.assertFalse(micro.plan([dk,ally],[],5,lambda _:None,dist,lambda *p:True,(-5000,0)))

    def test_controller_prioritizes_escort_over_advance_loot_and_shopping(self):
        dk=unit('Udea',1,0);allies=[unit('ucry',2,-1500),unit('ucry',3,-1550)]
        home=unit('unp2',5,-3000);enemy=unit('ogru',6,100)
        own=[dk,*allies,home]
        for u in own:u.owner=0
        moves=[];forbidden=[]
        g=N(resources=lambda:dict(food_used=0),snapshot=lambda **kw:N(clock=100,in_game=True,units=own),
            my_buildings=lambda *a:[home],map=lambda:N(starts=[],walkable=lambda *p:True),me=lambda:0,
            is_building=lambda u:u is home,my_heroes=lambda:[dk],
            units=lambda owner,codes:[u for u in own if u.type in codes],enemies=lambda:[enemy],
            creeps=lambda:[],my_units=lambda:own,dist=dist,path_distance=dist,
            current_target=lambda u:dk,inventory=lambda u:['stwp'],cooldown=lambda *a:1)
        bot=Controller(g,lambda *a,**kw:None);bot.attack_committed=True
        bot.economy.tick=lambda *a:None;bot.scout=lambda *a:None;bot.skills=lambda *a:None
        bot.items=lambda *a:setattr(bot,'shop_goal',(-3000,0))
        bot.go_raw=lambda army,p,now,attack=False:moves.extend((u.handle,p,attack) for u in army)
        bot.advance_attack=lambda *a:forbidden.append('advance')
        bot.loot.tick=lambda *a:forbidden.append('loot')
        bot.prepare_attack=lambda *a:forbidden.append('shopping')
        bot.tick()
        self.assertEqual(bot.action,Action.CREEP)
        self.assertFalse(forbidden)
        orders={h:(p,attack) for h,p,attack in moves}
        self.assertFalse(orders[dk.handle][1])
        for ally in allies:
            self.assertFalse(orders[ally.handle][1])
            self.assertEqual(orders[ally.handle][0],bot.micro.dk_support['point'])

    def test_rejoined_dk_does_not_return_to_an_obsolete_terrain_turn(self):
        dk=unit('Udea',1,100);allies=[unit('ucry',2,0),unit('ucry',3,-100)]
        home=unit('unpl',5,-6000);own=[dk,*allies,home];orders=[]
        for u in own:u.owner=0
        g=N(resources=lambda:dict(food_used=0),snapshot=lambda **kw:N(clock=100,in_game=True,units=own),
            my_buildings=lambda *a:[home],map=lambda:N(starts=[],walkable=lambda *p:True),me=lambda:0,
            is_building=lambda u:u is home,my_heroes=lambda:[dk],
            units=lambda owner,codes:[u for u in own if u.type in codes],enemies=lambda:[],
            creeps=lambda:[],my_units=lambda:own,dist=dist,path_distance=dist,walk_path=lambda a,b:[b],
            current_target=lambda u:None,inventory=lambda u:['stwp'],cooldown=lambda *a:1)
        bot=Controller(g,lambda *a,**kw:None)
        bot.economy.tick=lambda *a:None;bot.scout=lambda *a:None;bot.skills=lambda *a:None
        bot.items=lambda *a:None;bot.loot.tick=lambda *a:None
        bot.micro.dk_recovering=dk.handle
        bot.formation.route=[(3000,0),(-5000,0)]
        bot.formation.objective=(-5000,0);bot.formation.last_progress=100
        bot.formation.route_distance=5000
        bot.formation.cursors={dk.handle:0,allies[0].handle:1,allies[1].handle:1}
        bot.go_raw=lambda army,p,now,attack=False:orders.extend((u.handle,p) for u in army)
        bot.creep=lambda army,center,now:bot.go(army,(-5000,0),now,attack=True)
        bot.tick()
        self.assertEqual({h for h,p in orders},{dk.handle,allies[0].handle,allies[1].handle})
        self.assertTrue(all(p==(-5000,0) for h,p in orders))

    def test_nearby_escort_fights_while_distant_escort_closes_without_distraction(self):
        near=unit('ucry',2,300);far=unit('ucry',3,1200);orders=[]
        g=N(dist=dist,move=lambda u,*p:orders.append((u.handle,'move')) or True,
            attack_move=lambda u,*p:orders.append((u.handle,'attack')) or True)
        bot=Controller(g,lambda *a,**kw:None)
        bot.micro.dk_support=dict(handle=(1,0),point=(0,0),gap=1200,reason='separated')
        bot.support_dk([near,far],1)
        self.assertEqual(orders,[(near.handle,'attack'),(far.handle,'move')])

    def test_escort_respects_shield_isolation_and_cast_protection(self):
        dk=unit('Udea',1,0);ally=unit('ucry',2,-1000);lich=unit('Ulic',3,-1100)
        moves=[]
        g=N(dist=dist,move=lambda u,*p:moves.append(u.handle) or True,
            attack_move=lambda u,*p:moves.append(u.handle) or True)
        bot=Controller(g,lambda *a,**kw:None)
        bot.micro.dk_support=dict(handle=dk.handle,point=(0,0),gap=1000,reason='separated')
        bot.shield_moves={ally.handle:(-1500,0)};bot.cast_until[lich.handle]=11
        self.assertTrue(bot.support_dk([ally,lich],10))
        self.assertFalse(moves)
        bot.support_dk([ally,lich],12)
        self.assertEqual(moves,[lich.handle])

if __name__=='__main__':unittest.main()
