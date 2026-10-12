import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller,ground_attack_range
from undead.micro import Micro
from undead.policy import Action
from undead.retreat import escape_point

class RodTests(unittest.TestCase):
    def make(self):
        dk=unit('Udea',1,0,600);dk.owner=0;live=[];orders=[];events=[];cd=[0]
        corpse=unit('nogr',2,100,0);corpse.owner=12;corpse.alive=False;corpse.visible_to=lambda me:True
        g=N(me=lambda:0,dist=dist,units=lambda side,codes:[u for u in live if u.type in codes],
            use_item=lambda *a:orders.append('rod') or True,cooldown=lambda *a:cd[0],
            move=lambda *a:orders.append('move') or True)
        b=Controller(g,lambda event,**kw:events.append(dict(event=event,**kw)))
        return b,dk,corpse,live,orders,events,cd

    def test_observed_corpse_triggers_without_old_twelve_second_delay(self):
        b,dk,c,live,orders,events,cd=self.make();b.last['rod']=99
        b.observe_rod_corpses([c],100)
        self.assertTrue(b.maintain_skeletons(dk,0,100));self.assertEqual(orders,['rod'])
        b.go_raw([dk],(500,0),100.2);self.assertEqual(orders,['rod'])
        fresh=unit('uske',5,100);live.append(fresh);b.observe_rod_skeletons(101)
        self.assertIn(fresh.handle,b.skeleton_expiry);self.assertIn(c.handle,b.rod_used)
        self.assertFalse(b.maintain_skeletons(dk,0,104))

    def test_missing_hidden_or_stale_corpse_and_cooldown_do_not_waste_orders(self):
        for mode in ('none','hidden','stale','cooldown','far','pulling'):
            b,dk,c,live,orders,events,cd=self.make()
            if mode=='hidden':c.visible_to=lambda me:False
            if mode!='none':b.observe_rod_corpses([c],100)
            now=161 if mode=='stale' else 100
            if mode=='cooldown':cd[0]=5
            if mode=='far':dk.x=2000
            if mode=='pulling':b.micro.pulling.add(dk.handle)
            self.assertFalse(b.maintain_skeletons(dk,0,now),mode);self.assertFalse(orders)

    def test_unconfirmed_summoning_is_bounded_and_never_reported_as_effect(self):
        b,dk,c,live,orders,events,cd=self.make();b.observe_rod_corpses([c],100)
        for now in (100,104,108,112,116):
            b.observe_rod_skeletons(now);b.maintain_skeletons(dk,0,now)
        self.assertEqual(orders,['rod']*3)
        self.assertTrue(any(e['event']=='rod_summon_unconfirmed' for e in events))
        self.assertFalse(b.skeleton_expiry);self.assertFalse(b.rod_used)

    def test_distant_scouts_do_not_suppress_local_skeletons(self):
        b,dk,c,live,orders,events,cd=self.make();b.observe_rod_corpses([c],100)
        live.extend(unit('uske',10+i,5000) for i in range(4))
        self.assertTrue(b.maintain_skeletons(dk,0,100))
        b,dk,c,live,orders,events,cd=self.make();b.observe_rod_corpses([c],100)
        live.extend(unit('uske',10+i,100) for i in range(4))
        self.assertFalse(b.maintain_skeletons(dk,0,100))

    def test_lost_vision_is_not_a_corpse(self):
        b,dk,c,live,orders,events,cd=self.make();c.alive=True;c.hp=100
        b.observe_rod_corpses([c],100);b.observe_rod_corpses([],101)
        self.assertFalse(b.rod_corpses);self.assertFalse(b.maintain_skeletons(dk,0,101))

class EscapeTests(unittest.TestCase):
    def test_creeping_dk_pulls_before_45_percent_when_damage_predicts_danger(self):
        dk=unit('Udea',1,0,440);dk.hp_max=775;dk.mana=100
        ally=unit('ucry',2,-300);e=unit('nogr',3,100)
        m=Micro(lambda *a,**k:None);m.damage.samples[dk.handle]=[(393.73,507)]
        moves=m.plan([dk,ally],[e],394.73,lambda u:dk.handle,dist,lambda *p:True,(-2000,0),lambda u:100,creeping=True)
        self.assertGreater(dk.hp/dk.hp_max,.45);self.assertIn(dk.handle,moves);self.assertLess(moves[dk.handle][0],0)

    def test_neutral_escape_allows_safe_short_trial_but_not_player_chase(self):
        dk=unit('Udea',1,0,440);dk.level=2;dk.hp_max=775
        foe=unit('nogr',2,100);foe.owner=12
        g=N(dist=dist,path_distance=dist,buffs=lambda u:[],current_target=lambda u:dk)
        b=Controller(g,lambda *a,**k:None);b.action=Action.CREEP;b.portal_pulls[dk.handle]=(-800,0)
        self.assertTrue(b.escape_available(dk,[foe],394.73))
        foe.owner=1;b.escape_started.clear()
        self.assertFalse(b.escape_available(dk,[foe],394.73))
        foe.owner=12;g.buffs=lambda u:['BSTN'];b.escape_started.clear()
        self.assertFalse(b.escape_available(dk,[foe],394.73))

    def test_stalled_retreat_cannot_defer_tp_forever(self):
        dk=unit('Udea',1,0,440);dk.level=2;foe=unit('nogr',2,100);foe.owner=12
        g=N(dist=dist,path_distance=dist,buffs=lambda u:[],current_target=lambda u:dk)
        b=Controller(g,lambda *a,**k:None);b.action=Action.CREEP;b.portal_pulls[dk.handle]=(-600,0)
        self.assertTrue(b.escape_available(dk,[foe],100))
        self.assertFalse(b.escape_available(dk,[foe],101.1))

if __name__=='__main__':unittest.main()
