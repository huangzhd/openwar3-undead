import unittest
from itertools import product, combinations
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_nc_combo as nc_tests
from undead.targeting import HeroPressure
from undead.nc_combo import spell_damage

class NCFTests(unittest.TestCase):
    def make(self):
        fixture=nc_tests.NCTests().make()
        b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        naga=unit('Nngs',3,100,600);naga.owner=0;naga.has_detail=True;own.append(naga)
        skills[naga.handle]=[dict(code='ANfl',level=1)]
        return fixture,naga

    def test_all_seven_minimum_combinations(self):
        for expected,hp,disabled,undead in [('F',50,'CN',False),('C',65,'',False),('N',100,'',False),
                ('CF',120,'',False),('NC',160,'',False),('NF',155,'',True),('NCF',200,'',False)]:
            fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=hp
            if 'C' in disabled:d.mana=0
            if 'N' in disabled:l.mana=0
            if undead:h.type='Ulic'
            b.combat_spells(own,foes,10)
            with self.subTest(expected=expected):
                self.assertEqual(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['combination'],expected)
                self.assertEqual(len(orders),len(expected))
                self.assertTrue(all(order[2]==h.handle for order in orders))

    def test_mixed_levels_resistance_and_minimum_cost_oracle(self):
        for levels in product((1,2,3),repeat=3):
            for resist in (False,True):
                fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
                for u,level in zip((l,d,n),levels):skills[u.handle][0]['level']=level
                if resist:skills[h.handle]=[dict(code='AIsr',level=1)]
                parts=[spell_damage(code,level,resist) for code,level in zip(('AUfn','AUdc','ANfl'),levels)]
                for fraction in (.25,.6,.99):
                    orders.clear();events.clear();b.nc_combo.pending=None;b.cast_until.clear();b.nc_combo.retry_at.clear()
                    h.hp=sum(parts)*fraction
                    choices=[s for count in (1,2,3) for s in combinations(range(3),count) if sum(parts[i] for i in s)>=h.hp]
                    best=min(choices,key=lambda s:(len(s),sum((125,75,110)[i] for i in s),sum(parts[i] for i in s)-h.hp))
                    b.combat_spells(own,foes,10)
                    self.assertEqual(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['combination'],''.join('NCF'[i] for i in best))

    def test_fork_is_primary_damage_only(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        d.mana=l.mana=0;h.hp=60
        b.combat_spells(own,foes,10);self.assertFalse(orders)
        h.hp=59.5;b.combat_spells(own,foes,11)
        self.assertEqual(orders,[('Nngs','forkedlightning',h.handle)])

    def test_unavailable_fork_does_not_prevent_nc(self):
        for reason in ('absent','unlearned','mana','cooldown','unknown','range','protected','silenced'):
            fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=160
            if reason=='absent':own.remove(n)
            if reason=='unlearned':skills[n.handle]=[]
            if reason=='mana':n.mana=109
            if reason=='cooldown':cd[(n.handle,'ANfl')]=1
            if reason=='unknown':cd[(n.handle,'ANfl')]=None
            if reason=='range':n.x=-301
            if reason=='protected':b.micro.pulling.add(n.handle)
            if reason=='silenced':buffs[n.handle]=['BNsi']
            b.combat_spells(own,foes,10)
            self.assertEqual([o[1] for o in orders],['frostnova','deathcoil'],reason)

    def test_fork_range_boundary_and_actual_mana(self):
        for distance,expected in ((600,True),(600.01,False)):
            fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
            n.x=h.x-distance;n.mana=110;h.hp=200
            b.combat_spells(own,foes,10);self.assertEqual(len(orders)==3,expected)

    def test_critical_healing_precedes_three_spells(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=200;l.hp=100
        b.combat_spells(own,foes,10)
        self.assertEqual(orders,[('Udea','deathcoil',l.handle)])

    def test_revalidate_after_nova_before_unissued_spells(self):
        for change in ('healed','lost','immune','dead','landed'):
            fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=200
            def cast(u,s,target):
                orders.append((u.type,s,target.handle))
                if s=='frostnova':
                    if change=='healed':h.hp=500
                    if change=='lost':foes.remove(h)
                    if change=='immune':buffs[h.handle]=['Bvul']
                    if change=='dead':h.hp=0
                    if change=='landed':h.hp=95
                return True
            b.g.cast=cast;b.combat_spells(own,foes,10)
            if change=='landed':self.assertEqual([o[1] for o in orders],['frostnova','deathcoil','forkedlightning'])
            else:self.assertEqual([o[1] for o in orders],['frostnova'],change)

    def test_pending_three_spells_block_ordinary_damage(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=200
        b.combat_spells(own,foes,10);b.fight(own,foes,10);b.fight(own,foes,11)
        self.assertEqual([o[1] for o in orders if o[1]!='attack'],['frostnova','deathcoil','forkedlightning'])

    def test_fork_rejection_has_shared_bounded_retry(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        d.mana=l.mana=0;h.hp=50
        b.g.cast=lambda u,s,target:orders.append(s) or False
        for now in (10,10.1,12,14,16,100):b.combat_spells(own,foes,now)
        self.assertEqual(orders,['forkedlightning']*3)

    def test_failed_nova_allows_independent_cf_but_not_extra_spell(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        h.hp=150
        b.g.cast=lambda u,s,target:orders.append((u.type,s,target.handle)) or s!='frostnova'
        for now in (10,12,14,16):b.combat_spells(own,foes,now)
        self.assertEqual([o[1] for o in orders],['frostnova']*3)
        h.hp=120;b.combat_spells(own,foes,18)
        self.assertEqual([o[1] for o in orders][3:],['deathcoil','forkedlightning'])

    def test_fork_level_and_bracers_exact_boundaries(self):
        for level,base in ((1,59.5),(2,112),(3,175)):
            for resist in (False,True):
                for delta,expected in ((0,True),(.01,False)):
                    fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
                    d.mana=l.mana=0;skills[n.handle][0]['level']=level
                    if resist:skills[h.handle]=[dict(code='AIsr',level=1)]
                    h.hp=base*(.67 if resist else 1)+delta;b.combat_spells(own,foes,10)
                    self.assertEqual(bool(orders),expected,(level,resist,delta))

    def test_ordinary_fork_uses_110_mana_and_shared_target(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        h.hp=500;d.mana=l.mana=0;n.mana=110
        b.fight(own,foes,10)
        self.assertIn(('Nngs','forkedlightning',h.handle),orders)

    def test_immediate_support_is_logged_as_uncertain_not_confirmed_kill(self):
        fixture,n=self.make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture;h.hp=200
        w=unit('emow',20,320,600);w.owner=1;w.has_detail=True;foes.append(w)
        skills[w.handle]=[dict(code='Ambt',level=1)]
        b.combat_spells(own,foes,10)
        self.assertTrue(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['healing_window_uncertain'])
        self.assertFalse(next(e for e in events if e['event'] in {'nc_attempt','hero_finisher_attempt'})['damage_confirmed'])
        self.assertIsNotNone(b.nc_combo.pending)

class AdaptiveTargetTests(unittest.TestCase):
    def make(self):
        own=[unit('ucry',1,0,550),unit('ucry',2,50,550)]
        hero=unit('Ekee',10,300,500);foot=unit('ogru',11,200,20);well=unit('emow',12,400,600)
        visible=[hero,foot,well];skills={well.handle:[dict(code='Ambt',level=1)]};effects={};cd={}
        targets={u.handle:hero for u in own};events=[]
        for u in own+visible:u.owner=0 if u in own else 1;u.has_detail=True
        g=N(dist=dist,me=lambda:0,current_target=lambda u:targets.get(u.handle),enemies=lambda:visible,
            abilities=lambda u:skills.get(u.handle,[]),buffs=lambda u:effects.get(u.handle,[]),
            cooldown=lambda u,a:cd.get((u.handle,a),0))
        p=HeroPressure(lambda event,**kw:events.append(dict(event=event,**kw)))
        return p,g,own,hero,foot,well,visible,targets,skills,effects,cd,events

    def run_sequence(self,fixture,hps,start=0):
        p,g,own,h,f,w,visible,targets,*_=fixture
        result=None
        for now,hp in enumerate(hps,start):
            h.hp=hp;result=p.choose(g,own,visible,now)
        return result

    def test_one_unknown_large_recovery_without_support_keeps_hero(self):
        x=self.make();p,g,own,h,f,w,v,*_=x;w.mana=0
        self.assertIs(self.run_sequence(x,[500,420,580,540,500,460]),h)
        self.assertFalse(p.downgraded)

    def test_visible_potion_cast_resets_slope_without_assuming_exhausted(self):
        x=self.make();p,g,own,h,f,w,v,*_=x
        self.run_sequence(x,[500,450])
        p.observe_events([N(kind='spell.cast',handle=h.handle,spell='AIh1',clock=1.5,target_handle_lo=h.handle[0])])
        self.assertIs(self.run_sequence(x,[590,560,530,500],2),h)
        self.assertEqual(x[-1][-1]['source'],'consumable_cast')
        self.assertIsNone(x[-1][-1]['exhausted'])
        self.assertGreater(p.history[h.handle][0][1],500)

    def test_item_disappearance_alone_is_not_consumption(self):
        x=self.make();p,g,own,h,f,w,v,*_=x;w.mana=0
        g.inventory=lambda u:[]
        self.run_sequence(x,[500,420,580,560])
        self.assertEqual([e['source'] for e in x[-1] if e['event']=='hero_recovery_observed'],['unknown'])
        self.assertFalse(p.downgraded)

    def test_moonwell_with_reserve_and_recovery_switches_to_easy_unit(self):
        x=self.make();p,g,own,h,f,w,v,*_=x
        self.assertIs(self.run_sequence(x,[500,470,550]),f)
        self.assertIn(h.handle,p.downgraded)

    def test_empty_distant_or_unobserved_well_does_not_imply_support(self):
        for reason in ('empty','distant','detail','ability','no_recovery'):
            x=self.make();p,g,own,h,f,w,v,*_=x
            if reason=='empty':w.mana=0
            if reason=='distant':w.x=701
            if reason=='detail':w.has_detail=False
            if reason=='ability':x[8].clear()
            hps=[500,470,550] if reason!='no_recovery' else [500,450,400,350,300]
            self.assertIs(self.run_sequence(x,hps),h,reason)

    def test_repeated_unknown_recovery_is_evidence_not_source_identity(self):
        x=self.make();p,g,own,h,f,w,v,*_=x;w.mana=0
        self.assertIs(self.run_sequence(x,[500,530,490,540]),f)
        self.assertEqual(x[-1][-1]['sources'][0][0],'repeated_observed_recovery')

    def test_potion_regeneration_counts_only_while_effect_active(self):
        for active in (True,False):
            x=self.make();p,g,own,h,f,w,v,*_=x;w.mana=0
            if active:x[9][h.handle]=['BIrl']
            self.assertIs(self.run_sequence(x,[500,470,550]),f if active else h)

    def test_holy_light_needs_legal_target_mana_range_and_cooldown_window(self):
        for reason in ('ready','empty','range','cooldown','unlearned','self','undead','disabled'):
            x=self.make();p,g,own,h,f,w,v,targets,skills,effects,cd,_=x;w.mana=0
            pal=unit('Hpal',20,400,500);pal.owner=1;pal.has_detail=True;v.append(pal)
            skills[pal.handle]=[dict(code='AHhb',level=1)]
            if reason=='empty':pal.mana=64
            if reason=='range':pal.x=1101
            if reason=='cooldown':cd[(pal.handle,'AHhb')]=100
            if reason=='unlearned':skills[pal.handle]=[]
            if reason=='self':v.remove(pal);h.type='Hpal';skills[h.handle]=[dict(code='AHhb',level=1)]
            if reason=='undead':h.type='Ulic'
            if reason=='disabled':effects[pal.handle]=['BNsi']
            self.assertIs(self.run_sequence(x,[500,470,550]),f if reason=='ready' else h,reason)

    def test_no_alternative_continues_attacking(self):
        x=self.make();p,g,own,h,f,w,v,*_=x;v.remove(f);w.x=650
        self.assertIs(self.run_sequence(x,[500,470,550,500,550]),h)

    def test_insufficient_actual_attackers_or_gaps_do_not_infer_stall(self):
        for reason in ('one','lost_attacker','gap'):
            x=self.make();p,g,own,h,f,w,v,targets,*_=x
            if reason=='one':targets.pop(own[1].handle)
            self.run_sequence(x,[500,470])
            if reason=='lost_attacker':targets.pop(own[1].handle)
            self.assertIs(self.run_sequence(x,[550],3 if reason=='gap' else 2),h)

    def test_downgrade_sticks_past_timeout_without_automatic_reacquire(self):
        x=self.make();p,g,own,h,f,w,v,targets,*_=x
        self.assertIs(self.run_sequence(x,[500,470,550]),f)
        for u in own:targets[u.handle]=f
        for now in (3,7,9,20):self.assertIs(p.choose(g,own,v,now),f)
        v.remove(f);v.remove(w)
        self.assertIs(p.choose(g,own,v,21),h)

    def test_out_of_range_alternative_cannot_trigger_switch(self):
        x=self.make();p,g,own,h,f,w,v,*_=x;f.x=900;w.x=650
        self.assertIs(self.run_sequence(x,[500,470,550,500,550]),h)

    def test_faster_hero_kill_before_heal_cooldown_keeps_pressure(self):
        x=self.make();p,g,own,h,f,w,v,targets,skills,effects,cd,_=x;w.mana=0
        pal=unit('Hpal',20,400,500);pal.owner=1;pal.has_detail=True;v.append(pal)
        skills[pal.handle]=[dict(code='AHhb',level=1)];cd[(pal.handle,'AHhb')]=5
        self.assertIs(self.run_sequence(x,[30,20,35]),h)

    def test_offensive_spells_and_attacks_follow_downgraded_target(self):
        fixture=nc_tests.NCTests().make();b,d,l,h,f,own,foes,orders,events,skills,buffs,cd=fixture
        # Put casters in actual weapon reach; avoid spending spells until the decision.
        h.hp=500;h.x=80;d.mana=l.mana=0
        targets={d.handle:h,l.handle:h};b.g.current_target=lambda u:targets.get(u.handle)
        w=unit('emow',20,100,600);w.owner=1;w.has_detail=True;foes.append(w)
        skills[w.handle]=[dict(code='Ambt',level=1)]
        for now,hp in enumerate((500,470,550)):
            h.hp=hp;b.fight(own,foes,now)
        d.mana=l.mana=200;orders.clear();b.fight(own,foes,3)
        self.assertEqual([o for o in orders if o[1] in ('deathcoil','frostnova')],
                         [('Udea','deathcoil',f.handle),('Ulic','frostnova',f.handle)])

    def test_lethal_finish_overrides_downgrade(self):
        fixture=nc_tests.NCTests().make();b,d,l,h,f,own,foes,orders,*_=fixture
        b.hero_pressure.downgraded[h.handle]=dict(until=100,support=True,force=2)
        b.hero_pressure.preferred=f.handle;h.hp=160
        b.combat_spells(own,foes,10)
        self.assertEqual([o[1] for o in orders],['frostnova','deathcoil'])

    def test_ordinary_spell_does_not_select_hero_outside_shared_attack_reach(self):
        fixture=nc_tests.NCTests().make();b,d,l,h,f,own,foes,orders,*_=fixture
        own.remove(l);foes.remove(f);h.hp=500;h.x=500
        b.fight(own,foes,10)
        self.assertFalse(orders)

    def test_only_own_upgrade_query_is_used_for_cost(self):
        x=self.make();p,g,own,h,f,w,v,*_=x
        before=p.estimate(g,own,h);queries=[]
        def tech_many(codes):queries.append(codes);return {'Rura':3}
        g.tech_many=tech_many;p.choose(g,own,v,0)
        self.assertLess(p.estimate(g,own,h),before)
        self.assertTrue(queries)

    def test_cost_near_tie_prefers_siege_but_does_not_dive_for_building(self):
        x=self.make();p,g,own,h,f,w,v,*_=x
        siege=unit('ocat',20,350,100);siege.owner=1;siege.has_detail=True
        siege.hp=100/p.estimate(g,own,siege)*1.2
        f.hp=f.hp/p.estimate(g,own,f)*1.3
        v[:]=[siege,f,w];w.x=900;w.hp=1
        self.assertIs(p.choose(g,own,v,0),siege)

if __name__=='__main__':unittest.main()
