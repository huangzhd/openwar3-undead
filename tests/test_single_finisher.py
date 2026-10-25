import unittest
import test_nc_combo as nc_tests

class SingleFinisherTests(unittest.TestCase):
    def test_coil_alone_uses_cheaper_skill_and_preserves_nova(self):
        b,d,l,h,f,own,foes,orders,events,*_=nc_tests.NCTests().make();h.hp=65
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertEqual([r for r in orders if r[1] in ('deathcoil','frostnova')],[('Udea','deathcoil',h.handle)])
        self.assertEqual(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['estimated_damage'],70)
        self.assertEqual(b.nc_combo.pending['spells'],('AUdc',))

    def test_nova_alone_does_not_require_dk_or_his_mana(self):
        for absent in (False,True):
            b,d,l,h,f,own,foes,orders,events,*_=nc_tests.NCTests().make();h.hp=95;d.mana=0
            if absent:own.remove(d)
            b.combat_spells(own,foes,10)
            self.assertEqual(orders,[('Ulic','frostnova',h.handle)])
            b.nc_combo.observe(b.g,13)
            self.assertEqual(events[-1]['event'],'hero_finisher_observed')
            self.assertEqual(len(events[-1]['cooldowns']),1)

    def test_coil_alone_does_not_require_lich_ready_or_present(self):
        b,d,l,h,f,own,foes,orders,events,*_=nc_tests.NCTests().make();h.hp=65;own.remove(l)
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Udea','deathcoil',h.handle)])

    def test_bracers_and_actual_level_control_single_skill_boundary(self):
        b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=nc_tests.NCTests().make()
        skills[h.handle]=[dict(code='AIsr',level=1)];h.hp=65;d.mana=0
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Ulic','frostnova',h.handle)])
        self.assertAlmostEqual(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['estimated_damage'],70.35)
        b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=nc_tests.NCTests().make()
        h.hp=135;d.mana=0;skills[l.handle][0]['level']=2
        b.combat_spells(own,foes,10);self.assertEqual(orders,[('Ulic','frostnova',h.handle)])

    def test_unready_or_unsafe_single_skill_is_not_used(self):
        for reason in ('bracers','cooldown','unknown','unlearned','blocked','range','immune'):
            b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=nc_tests.NCTests().make();h.hp=100;d.mana=0
            if reason=='bracers':skills[h.handle]=[dict(code='AIsr',level=1)]
            if reason=='cooldown':cd[(l.handle,'AUfn')]=1
            if reason=='unknown':cd[(l.handle,'AUfn')]=None
            if reason=='unlearned':skills[l.handle]=[]
            if reason=='blocked':b.micro.pulling.add(l.handle)
            if reason=='range':h.x=800
            if reason=='immune':buffs[h.handle]=['Bvul']
            b.combat_spells(own,foes,10)
            with self.subTest(reason=reason):self.assertFalse(orders)

    def test_critical_hero_save_still_precedes_single_finisher(self):
        b,d,l,h,f,own,foes,orders,*_=nc_tests.NCTests().make();h.hp=65;l.hp=80
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Udea','deathcoil',l.handle)])

    def test_nova_can_finish_undead_hero_but_coil_cannot(self):
        b,d,l,h,f,own,foes,orders,*_=nc_tests.NCTests().make();h.type='Ulic';h.hp=60
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Ulic','frostnova',h.handle)])

    def test_single_rejection_and_accepted_no_effect_are_bounded(self):
        for accepted in (False,True):
            b,d,l,h,f,own,foes,orders,events,*_=nc_tests.NCTests().make();h.hp=65;l.mana=0
            b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or accepted
            for now in (10,13,16,19,22,100):b.combat_spells(own,foes,now)
            self.assertEqual(orders,[('Udea','deathcoil',h.handle)]*3)
            self.assertTrue(all(r[1]=='deathcoil' for r in orders))

    def test_exhausted_single_attempts_never_fall_back_to_wasteful_combo(self):
        b,d,l,h,f,own,foes,orders,events,*_=nc_tests.NCTests().make();h.hp=65
        b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or False
        for now in (10,12,14,16,18,20,22,30):b.combat_spells(own,foes,now)
        self.assertEqual([r[1] for r in orders],['deathcoil']*3+['frostnova']*3)
        self.assertFalse(any(e['event']=='nc_attempt' for e in events))

if __name__=='__main__':unittest.main()
