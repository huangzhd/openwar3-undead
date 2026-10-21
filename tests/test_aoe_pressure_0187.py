import unittest
import test_nc_combo as nc
from test_micro_loot import unit

class AOEPressureTests(unittest.TestCase):
    def make(self):
        values=nc.NCTests().make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=values
        h.type='Otch';h.hp=600
        fiend=unit('ucry',30,0,600);fiend.owner=0;fiend.has_detail=True;own.append(fiend)
        return values
    def test_nonlethal_nc_pressures_aoe_hero_with_followup_attackers(self):
        b,d,l,h,f,own,foes,orders,events,*_=self.make()
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertEqual(orders[:2],[('Ulic','frostnova',h.handle),('Udea','deathcoil',h.handle)])
        self.assertIn(('ucry','attack',h.handle),orders)
        self.assertTrue(any(e.get('intent')=='aoe_pressure' and not e['damage_confirmed'] for e in events))
    def test_higher_aoe_hero_precedes_lower_health_other_hero(self):
        b,d,l,h,f,own,foes,orders,*_=self.make();other=unit('Obla',40,350,300);other.owner=1;other.has_detail=True;foes.append(other)
        choice=b.hero_pressure.choose(b.g,own,foes,10);self.assertIs(choice,h)
        h.x=900;choice=b.hero_pressure.choose(b.g,own,foes,11);self.assertIs(choice,other)
    def test_wounded_ally_or_no_support_keeps_heal_and_no_nonlethal_combo(self):
        b,d,l,h,f,own,foes,orders,*_=self.make();l.hp=250
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Udea','deathcoil',l.handle),('Ulic','frostnova',h.handle)])
        b,d,l,h,f,own,foes,orders,*_=self.make();own[:]=[d,l]
        b.combat_spells(own,foes,10);self.assertFalse(orders)
    def test_immunity_cooldown_and_rejected_nova_do_not_waste_coil(self):
        for reason in ('immune','cooldown','reject'):
            b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=self.make()
            if reason=='immune':buffs[h.handle]=['Bams']
            elif reason=='cooldown':cd[(l.handle,'AUfn')]=5
            else:b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or False
            b.combat_spells(own,foes,10)
            self.assertFalse(any(o[1]=='deathcoil' for o in orders))
    def test_group_recovery_protects_healing_mana(self):
        b,d,l,h,f,own,foes,orders,*_=self.make();b.army_recovery.active=True
        b.combat_spells(own,foes,10);self.assertFalse(orders)

if __name__=='__main__':unittest.main()
