import unittest
import test_rescue_web_march_0144 as rescue

class CoilWaitTests(unittest.TestCase):
    def scene(self):
        g,b,d,h,army,bags,orders,given,events,e=rescue.EmergencyHandoffTests().make('Nbrn')
        h.hp=352.55;h.hp_max=550;d.mana=199
        b.micro.damage.rates[h.handle]=46.89
        cd=[1.25];casts=[]
        g.cooldown=lambda *a:cd[0]
        g.abilities=lambda u:[{'code':'AUdc','level':2}] if u is d else []
        g.buffs=lambda u:[]
        g.cast=lambda u,spell,target:casts.append((spell,target.handle)) or True
        g.unit=lambda handle:next((u for u in army if u.handle==handle),None)
        return g,b,d,h,army,bags,orders,given,events,e,cd,casts

    def test_bounded_wait_bridges_to_real_heal_instead_of_tp(self):
        g,b,d,h,army,bags,orders,given,events,e,cd,casts=self.scene()
        self.assertFalse(b.emergency_portal(army,649.43))
        self.assertFalse(orders);self.assertFalse(given)
        cd[0]=0;h.hp=315
        self.assertTrue(b.emergency_portal(army,650.8))
        self.assertEqual(casts,[('deathcoil',h.handle)])
        self.assertFalse(orders);self.assertFalse(given)

    def test_unknown_long_cooldown_critical_health_unreachable_or_disabled_caster_do_not_wait(self):
        for case in ('unknown','long','low','damage','mana','range','disabled'):
            with self.subTest(case=case):
                g,b,d,h,army,bags,orders,given,events,e,cd,casts=self.scene()
                if case=='unknown':cd[0]=None
                if case=='long':cd[0]=3
                if case=='low':h.hp=150
                if case=='damage':b.micro.damage.rates[h.handle]=150
                if case=='mana':d.mana=74
                if case=='range':d.x=900
                if case=='disabled':g.buffs=lambda u:['BPSE'] if u is d else []
                self.assertTrue(b.emergency_portal(army,649.43))
                self.assertTrue(orders or given)

    def test_unchanged_cooldown_cannot_extend_wait_forever(self):
        g,b,d,h,army,bags,orders,given,events,e,cd,casts=self.scene()
        self.assertFalse(b.emergency_portal(army,649.43))
        self.assertTrue(b.emergency_portal(army,652.5))
        self.assertTrue(orders or given)
