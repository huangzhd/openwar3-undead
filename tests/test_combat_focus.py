import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.targeting import in_weapon_range
import test_nc_combo as nc_tests

class CombatFocusTests(unittest.TestCase):
    def make(self):
        fiend=unit('ucry',1,0,550);dk=unit('Udea',2,0,675)
        siege=unit('ocat',10,500,425);hero=unit('Ekee',11,400,500);foot=unit('ogru',12,80,100)
        own=[fiend,dk];foes=[siege,hero,foot];commands=[];targets={};events=[]
        for u in own+foes:u.owner=0 if u in own else 1;u.mana=0
        def attack(u,e,**kw):commands.append(('attack',u.handle,e.handle));targets[u.handle]=e;return True
        def hold(u):commands.append(('hold',u.handle));targets.pop(u.handle,None);return True
        g=N(me=lambda:0,dist=dist,current_target=lambda u:targets.get(u.handle),attack=attack,hold=hold,
            unit=lambda h:next((u for u in own+foes if u.handle==h),None),
            units=lambda owner,codes:[u for u in own if u.type in codes],cooldown=lambda *a:0)
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        return b,fiend,dk,siege,hero,foot,own,foes,commands,targets,events

    def test_hero_pressure_continues_until_range_exit_then_cheaper_unit_wins(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make()
        b.fight(own,foes,10)
        self.assertIs(targets[f.handle],h);self.assertIs(targets[d.handle],e)
        b.fight(own,foes,13.1);self.assertIs(targets[f.handle],h)
        h.x=580
        b.fight(own,foes,15);self.assertIs(targets[f.handle],e);self.assertIs(targets[d.handle],e)
        self.assertFalse(any(c==('attack',d.handle,s.handle) for c in commands))

    def test_out_of_range_siege_cannot_override_local_hero_pressure(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();s.x=560
        b.fight(own,foes,10);self.assertIs(targets[f.handle],h)
        self.assertTrue(in_weapon_range(b.g,f,h));self.assertFalse(in_weapon_range(b.g,f,s))

    def test_pressure_has_no_timeout_or_retry_delay(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();foes.remove(s)
        b.fight(own,foes,10)
        for t in (13.1,20,40,100):
            b.fight(own,foes,t);self.assertIs(targets[f.handle],h)
        h.x=580;b.fight(own,foes,102);self.assertIs(targets[f.handle],e)
        h.x=400;b.fight(own,foes,104);self.assertIs(targets[f.handle],h)
        self.assertEqual([r['reason'] for r in events if r['event']=='hero_pressure_released'],['out_of_range_or_vision'])

    def test_outward_motion_within_range_keeps_pressure(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();foes.remove(s)
        b.fight(own,foes,10);h.x=510
        b.fight(own,foes,11.3);self.assertIs(targets[f.handle],h)
        self.assertTrue(in_weapon_range(b.g,f,h))
        self.assertFalse(any(r['event']=='hero_pressure_released' for r in events))

    def test_hero_leaving_range_cancels_old_chase_and_switches_to_other_unit(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();foes.remove(s);h.hp=60
        b.fight(own,foes,10);h.x=580
        b.fight(own,foes,11.3)
        self.assertIn(('hold',f.handle),commands);self.assertIs(targets[f.handle],e)
        self.assertNotEqual(commands[-1],('attack',f.handle,h.handle))

    def test_lost_vision_and_no_other_target_stops_instead_of_following(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();foes[:]=[h]
        b.fight(own,foes,10);foes.clear();targets.clear()
        b.fight(own,foes,11.3)
        self.assertIn(('hold',f.handle),commands);self.assertNotIn(f.handle,b.hero_attack_targets)

    def test_out_of_range_without_alternative_holds_and_protected_caster_is_untouched(self):
        b,f,d,s,h,e,own,foes,commands,targets,events=self.make();foes[:]=[h]
        b.fight(own,foes,10);b.cast_until[d.handle]=20;h.x=580
        b.fight(own,foes,13.1)
        self.assertIn(('hold',f.handle),commands);self.assertNotIn(f.handle,targets)
        self.assertFalse(any(c[0]=='hold' and c[1]==d.handle for c in commands))

    def test_lethal_nc_overrides_siege_without_pulling_melee(self):
        b,d,l,h,foot,own,foes,orders,events,*_=nc_tests.NCTests().make()
        f=unit('ucry',30,0,550);f.owner=0;own.append(f)
        siege=unit('ocat',31,400,425);siege.owner=1;foes.append(siege)
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertEqual(orders[:2],[('Ulic','frostnova',h.handle),('Udea','deathcoil',h.handle)])
        self.assertIn(('ucry','attack',h.handle),orders)

if __name__=='__main__':unittest.main()
