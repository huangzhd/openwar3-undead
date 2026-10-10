import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.policy import Action


class MarchRecoveryTests(unittest.TestCase):
    def controller(self):
        orders=[]
        g=N(dist=dist,path_distance=dist,walk_path=lambda a,b:[b],
            move=lambda u,*p:orders.append((u,p,False)) or True,
            attack_move=lambda u,*p:orders.append((u,p,True)) or True,
            hold=lambda u:None)
        bot=Controller(g,lambda *a,**kw:None);bot.action=Action.ATTACK
        return bot,orders

    def test_roadside_autotarget_does_not_pin_trailing_dk_while_main_marches(self):
        bot,orders=self.controller()
        dk=unit('Udea',1,0);allies=[unit('ucry',2,1100),unit('ucry',3,1150)]
        army=[dk,*allies]
        for now in range(0,40,2):
            orders.clear();bot.go(army,(12000,0),now,attack=True)
            for u,p,attack in orders:
                # A harmless roadside target pins attack-move near the old base.
                if u is dk and u.x<800 and attack:continue
                u.x+=min(640 if u is dk else 540,max(0,p[0]-u.x))
            self.assertLess(dist(dk,allies[0]),1600)
        self.assertGreater(dk.x,9000)
        self.assertGreater(allies[0].x,9000)

    def test_catchup_rejoins_then_discards_pre_skirmish_turn(self):
        bot,orders=self.controller()
        dk=unit('Udea',1,0);allies=[unit('ucry',2,1500),unit('ucry',3,1550)]
        bot.formation.route=[(-2000,0),(6000,0)]
        bot.formation.objective=(6000,0);bot.formation.last_progress=0
        bot.go([dk,*allies],(6000,0),0,attack=True)
        self.assertEqual(orders[0][1:],((1500,0),False))
        dk.x=1300;orders.clear()
        bot.go([dk,*allies],(6000,0),2,attack=True)
        self.assertTrue(all(p==(6000,0) and attack for u,p,attack in orders))
        self.assertFalse(bot.formation.catching_up)

    def test_lagging_lich_also_catches_up_without_stopping_main_body(self):
        bot,orders=self.controller()
        lich=unit('Ulic',1,0);allies=[unit('ucry',2,1500),unit('ucry',3,1550)]
        bot.go([lich,*allies],(6000,0),0,attack=True)
        self.assertFalse(orders[0][2])
        self.assertTrue(all(p==(6000,0) and attack for _,p,attack in orders[1:]))

    def test_retreat_overrides_active_catchup_and_cast_protection_remains(self):
        bot,orders=self.controller()
        dk=unit('Udea',1,0);army=[dk,unit('ucry',2,1500),unit('ucry',3,1550)]
        bot.cast_until[dk.handle]=2
        bot.go(army,(6000,0),0,attack=True)
        self.assertFalse(any(u is dk for u,_,_ in orders))
        bot.action=Action.RETREAT;orders.clear()
        bot.go(army,(-6000,0),3)
        self.assertTrue(all(p==(-6000,0) and not attack for _,p,attack in orders))
        self.assertEqual(len(orders),3)


if __name__=='__main__':unittest.main()
