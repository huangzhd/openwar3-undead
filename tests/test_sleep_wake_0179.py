import unittest
from types import SimpleNamespace as N
from undead.sleep_wake import SleepWake
from undead.controller import Controller
from test_micro_loot import unit,dist

class WakeTests(unittest.TestCase):
    def make(self):
        actor=unit('ucry',1,0);target=unit('Ulic',2,200)
        for u in [actor,target]:u.owner=0;u.hp=u.hp_max=600
        own={u.handle:u for u in [actor,target]};buffs={actor.handle:[],target.handle:['BUsl']}
        orders=[];events=[];locks={}
        g=N(unit=lambda h:own.get(h),buffs=lambda u:buffs[u.handle],dist=dist,
            attack=lambda u,t,force=False:orders.append(('attack',u.handle,t.handle,force)) or True,
            stop=lambda u:orders.append(('stop',u.handle)) or True)
        w=SleepWake(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        return g,w,actor,target,buffs,orders,locks,events

    def test_one_nearby_actor_wakes_then_stops_and_resumes_orders(self):
        g,w,a,t,b,o,locks,events=self.make()
        w.start(g,[a,t],10,locks);self.assertEqual(o,[('attack',a.handle,t.handle,True)])
        controller=Controller.__new__(Controller);controller.g=g;controller.cast_until=locks;controller.last={}
        g.move=lambda u,x,y:o.append(('move',u.handle)) or True
        controller.go_raw([a],(0,0),10.5);self.assertEqual(len(o),1)
        t.hp-=25;b[t.handle]=[];w.observe(g,11,locks)
        self.assertEqual(o[-1],('stop',a.handle));self.assertIsNone(w.active)
        controller.go_raw([a],(0,0),11);self.assertEqual(o[-1],('move',a.handle))
        self.assertTrue(any(x['event']=='sleep_wake_observed' and x['hp_delta']==-25 for x in events))

    def test_timeout_stops_attack_and_two_attempts_bound_one_sleep(self):
        g,w,a,t,b,o,locks,events=self.make()
        for now in (10,14):
            w.start(g,[a,t],now,locks);w.observe(g,now+2,locks)
            self.assertEqual(o[-1],('stop',a.handle));self.assertFalse(locks)
        w.start(g,[a,t],20,locks)
        self.assertEqual(len([x for x in o if x[0]=='attack']),2)
        self.assertFalse(any(x['event']=='sleep_wake_observed' for x in events))
        b[t.handle]=[];w.start(g,[a,t],21,locks)
        b[t.handle]=['BUsl'];w.start(g,[a,t],22,locks)
        self.assertEqual(len([x for x in o if x[0]=='attack']),3)

    def test_protected_sleep_low_hp_distant_disabled_and_reserved_actor_wait(self):
        for condition in ('protected','fragile','distant','disabled','pulling','casting'):
            with self.subTest(condition=condition):
                g,w,a,t,b,o,locks,events=self.make();blocked=set()
                if condition=='protected':b[t.handle].append('BUsp')
                if condition=='fragile':t.hp=100
                if condition=='distant':t.x=1000
                if condition=='disabled':b[a.handle]=['BUim']
                if condition=='pulling':blocked={a.handle}
                if condition=='casting':locks[a.handle]=20
                w.start(g,[a,t],10,locks,blocked);self.assertFalse(o)

    def test_safety_cancellation_releases_actor_for_immediate_escape(self):
        g,w,a,t,b,o,locks,events=self.make();w.start(g,[a,t],10,locks)
        w.cancel(g,10.2,locks,'emergency_portal')
        self.assertEqual(o[-1],('stop',a.handle));self.assertNotIn(a.handle,locks)
        self.assertIsNone(w.active)

    def test_new_damage_interrupts_pending_hit_to_allow_retreat(self):
        g,w,a,t,b,o,locks,events=self.make();w.start(g,[a,t],10,locks)
        a.hp=100;w.observe(g,10.5,locks)
        self.assertEqual(o[-1],('stop',a.handle));self.assertFalse(locks)
        self.assertTrue(any(x.get('reason')=='health_priority' for x in events))

    def test_no_hero_or_statue_used_as_waker_and_no_attack_on_awake_ally(self):
        g,w,a,t,b,o,locks,events=self.make();a.type='Udea'
        w.start(g,[a,t],10,locks);self.assertFalse(o)
        a.type='uobs';w.start(g,[a,t],11,locks);self.assertFalse(o)
        a.type='ucry';b[t.handle]=[];w.start(g,[a,t],12,locks);self.assertFalse(o)

    def test_target_disappearance_stops_friendly_attack_without_success_claim(self):
        g,w,a,t,b,o,locks,events=self.make();w.start(g,[a,t],10,locks)
        g.unit=lambda h:a if h==a.handle else None
        w.observe(g,11,locks);self.assertEqual(o[-1],('stop',a.handle));self.assertFalse(locks)
        self.assertFalse(any(x['event']=='sleep_wake_observed' for x in events))

if __name__=='__main__':unittest.main()
