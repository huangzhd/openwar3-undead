import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.nc_combo import damage
from undead.policy import Action

class NCTests(unittest.TestCase):
    def make(self):
        dk=unit('Udea',1,0,600);lich=unit('Ulic',2,80,600)
        hero=unit('Obla',10,300,160);footman=unit('ogru',11,250,10)
        own=[dk,lich];foes=[hero,footman];orders=[];events=[];buffs={};cooldowns={}
        skills={dk.handle:[dict(code='AUdc',level=1)],lich.handle:[dict(code='AUfn',level=1)]}
        for u in own+foes:u.owner=0 if u in own else 1;u.has_detail=True
        g=N(dist=dist,me=lambda:0,enemies=lambda:foes,
            units=lambda side,codes:[u for u in own if u.type in codes],
            unit=lambda h:next((u for u in own+foes if u.handle==h),None),
            abilities=lambda u:skills.get(u.handle,[]),buffs=lambda u:buffs.get(u.handle,[]),
            cooldown=lambda u,a:cooldowns.get((u.handle,a),0),
            cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or True,
            attack=lambda u,t,**kw:orders.append((u.type,'attack',t.handle)) or True,
            current_target=lambda u:None,hold=lambda u:True)
        b=Controller(g,lambda event,**kw:events.append(dict(event=event,**kw)));b.action=Action.ATTACK
        return b,dk,lich,hero,footman,own,foes,orders,events,skills,buffs,cooldowns

    def test_combo_overrides_lower_hp_soldier_and_does_not_cancel_casts(self):
        b,d,l,h,f,own,foes,orders,*_=self.make()
        ally=unit('ucry',5,50,600);own.append(ally)
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertEqual(orders,[('Ulic','frostnova',h.handle),('Udea','deathcoil',h.handle),('ucry','attack',h.handle)])

    def test_only_critical_healable_hero_overrides_combo(self):
        for code,hp,expected in [('Ulic',150,'heal'),('Nbrn',140,'heal'),('ucry',10,'combo'),('Ulic',151,'combo'),('Nngs',10,'combo')]:
            with self.subTest(code=code,hp=hp):
                b,d,l,h,f,own,foes,orders,*_=self.make()
                patient=l if code=='Ulic' else unit(code,6,60,hp)
                patient.hp=hp
                if patient is not l:own.append(patient)
                b.combat_spells(own,foes,10)
                if expected=='heal':self.assertEqual(orders,[('Udea','deathcoil',patient.handle)])
                else:self.assertEqual(orders[:2],[('Ulic','frostnova',h.handle),('Udea','deathcoil',h.handle)])

    def test_regular_healing_returns_when_no_lethal_combo(self):
        b,d,l,h,f,own,foes,orders,*_=self.make();l.hp=300;h.hp=500
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Udea','deathcoil',l.handle)])

    def test_actual_skill_levels_and_reduction_change_lethal_target_choice(self):
        b,d,l,h,f,own,foes,orders,events,skills,*_=self.make();h.hp=250
        b.combat_spells(own,foes,10);self.assertFalse(orders)
        skills[d.handle][0]['level']=2;skills[l.handle][0]['level']=2
        b.combat_spells(own,foes,11)
        self.assertEqual([r[1] for r in orders],['frostnova','deathcoil'])
        self.assertGreater(events[0]['estimated_damage'],h.hp)

    def test_damage_boundary_not_raw_spell_sum(self):
        for hp,expected in [(sum(damage(1,1)),True),(sum(damage(1,1))+.01,False)]:
            b,d,l,h,f,own,foes,orders,*_=self.make();h.hp=hp
            b.combat_spells(own,foes,10);self.assertEqual(bool(orders),expected)

    def test_bracers_reduce_estimate(self):
        b,d,l,h,f,own,foes,orders,events,skills,*_=self.make()
        skills[h.handle]=[dict(code='AIsr',level=1)]
        b.combat_spells(own,foes,10);self.assertFalse(orders)
        h.hp=110;b.combat_spells(own,foes,11)
        self.assertEqual([r[1] for r in orders],['frostnova','deathcoil'])

    def test_invalid_or_unobservable_targets_do_not_start_combo(self):
        for reason in ('undead','neutral','own','not_hero','missing_detail','dead','out_of_range','lost_vision'):
            b,d,l,h,f,own,foes,orders,*_=self.make()
            if reason=='undead':h.type='Ulic'
            if reason=='neutral':h.owner=12
            if reason=='own':h.owner=0
            if reason=='not_hero':h.is_hero=False
            if reason=='missing_detail':h.has_detail=False
            if reason=='dead':h.hp=0
            if reason=='out_of_range':h.x=800
            if reason=='lost_vision':foes.remove(h)
            b.combat_spells(own,foes,10)
            with self.subTest(reason=reason):self.assertFalse(orders)

    def test_both_casters_must_be_ready_without_interrupting_safety(self):
        for reason in ('dk_mana','lich_mana','cooldown','unknown_cooldown','unlearned','missing_detail','pull','shield','cast','retreat','portal','disabled'):
            b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=self.make()
            if reason=='dk_mana':d.mana=74
            if reason=='lich_mana':l.mana=124
            if reason=='cooldown':cd[(l.handle,'AUfn')]=1
            if reason=='unknown_cooldown':cd[(d.handle,'AUdc')]=None
            if reason=='unlearned':skills[l.handle]=[]
            if reason=='missing_detail':d.has_detail=False
            if reason=='pull':b.micro.pulling.add(d.handle)
            if reason=='shield':b.shield_moves[l.handle]=(1000,0)
            if reason=='cast':b.cast_until[d.handle]=11
            if reason=='retreat':b.action=Action.RETREAT
            if reason=='portal':b.teleport=dict(hero=d.handle)
            if reason=='disabled':buffs[l.handle]=['BNsi']
            b.combat_spells(own,foes,10)
            with self.subTest(reason=reason):self.assertFalse(orders)

    def test_absorption_immunity_and_spell_block_are_excluded(self):
        for code in ('BHds','Bams','Bam2','BNms','BNss','Avul','Amim','ANss'):
            b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=self.make()
            if code.startswith('B'):buffs[h.handle]=[code]
            else:skills[h.handle]=[dict(code=code,level=1)]
            b.combat_spells(own,foes,10)
            with self.subTest(code=code):self.assertFalse(orders)

    def test_rejected_nova_stops_coil_and_retries_at_most_three_times(self):
        b,d,l,h,f,own,foes,orders,events,*_=self.make()
        b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or False
        for now in (10,10.5,12,14,16,20,100):b.combat_spells(own,foes,now)
        self.assertEqual(orders,[('Ulic','frostnova',h.handle)]*3)
        self.assertEqual(events[-1]['failures'],3)

    def test_partial_rejection_preserves_target_and_records_unconfirmed_effect(self):
        b,d,l,h,f,own,foes,orders,events,*_=self.make()
        b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or s=='frostnova'
        b.combat_spells(own,foes,10);b.combat_spells(own,foes,10.5)
        self.assertEqual(len(orders),2)
        foes.remove(h);b.nc_combo.observe(b.g,11)
        self.assertEqual(events[-1]['outcome'],'target_unavailable')
        self.assertFalse(events[0]['accepted'])

    def test_frost_armor_cannot_spend_reserved_nova_mana(self):
        b,d,l,h,f,own,foes,orders,events,skills,*_=self.make()
        skills[l.handle].append(dict(code='AUfu',level=1))
        b.g.current_target=lambda e:d
        b.combat_spells(own,foes,10);b.frost_armor(own,foes,10)
        self.assertEqual([r[1] for r in orders],['frostnova','deathcoil'])

    def test_nonlethal_spells_follow_shared_pressure_target(self):
        b,d,l,h,f,own,foes,orders,*_=self.make();h.hp=500
        b.combat_spells(own,foes,10);b.fight(own,foes,10)
        self.assertEqual(orders[:2],[('Udea','deathcoil',h.handle),('Ulic','frostnova',h.handle)])


    def test_full_tick_dispatches_nc_before_healing_and_frost_armor(self):
        b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=self.make()
        l.hp=300;skills[l.handle].append(dict(code='AUfu',level=1))
        home=unit('unpl',90,-4000,1000);home.owner=0
        g=b.g
        g.snapshot=lambda **kw:N(clock=100,in_game=True,units=own+foes+[home])
        g.my_buildings=lambda *a:[home]
        g.map=lambda:N(starts=[],walkable=lambda *p:True)
        g.my_heroes=lambda:[d,l];g.my_units=lambda:own+[home];g.creeps=lambda:[]
        g.inventory=lambda u:[];g.path_distance=dist
        b.memory.update=lambda *a:None
        b.clear_attack_sites=lambda *a:None;b.observe_air=lambda *a:None
        b.micro.plan=lambda *a,**kw:{}
        b.creeping.has_work=lambda *a:False
        b.economy.tick=lambda *a:None;b.scout=lambda *a:None
        b.skills=lambda *a:None;b.items=lambda *a:None
        b.consumables.tick=lambda *a,**kw:None
        b.emergency_portal=lambda *a:False
        b.shields.plan=lambda *a:{};b.creep_aggro.step=lambda *a:None
        b.support_dk=lambda *a:True
        b.tick(forced=Action.ATTACK)
        self.assertEqual(orders,[('Ulic','frostnova',h.handle),('Udea','deathcoil',h.handle)])

    def test_all_learned_level_pairs_choose_on_reduced_damage(self):
        for coil in (1,2,3):
            for nova in (1,2,3):
                for bracers in (False,True):
                    b,d,l,h,f,own,foes,orders,events,skills,*_=self.make()
                    skills[d.handle][0]['level']=coil;skills[l.handle][0]['level']=nova
                    if bracers:skills[h.handle]=[dict(code='AIsr',level=1)]
                    h.hp=sum(damage(coil,nova,bracers))-.1
                    b.combat_spells(own,foes,10)
                    with self.subTest(coil=coil,nova=nova,bracers=bracers):
                        self.assertEqual([r[1] for r in orders],['frostnova','deathcoil'])


    def test_accepted_but_unobserved_combo_has_bounded_retries(self):
        b,d,l,h,f,own,foes,orders,events,*_=self.make()
        for now in (10,13,16,19,22,100):b.combat_spells(own,foes,now)
        self.assertEqual([r[1] for r in orders],['frostnova','deathcoil']*3)
        self.assertEqual([e['outcome'] for e in events if e['event']=='nc_observed'],['unconfirmed']*3)

if __name__=='__main__':unittest.main()
