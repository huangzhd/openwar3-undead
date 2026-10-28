"""TC -> headhunters, Coil ownership, and efficient/last-resort group healing."""
import unittest
import test_battle_strategy_01201 as battle
import test_consumables as items
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController
from undead.consumables import Consumables
from undead.coil import heal_eligible


class TaurenSequenceTests(unittest.TestCase):
    def scene(self,kind=Controller):
        return battle.BattleStrategyTests().scene(kind,tc_opening=True)

    def test_nc_silence_then_heroes_and_ghouls_focus_tc_in_both_modes(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            for u in own:
                if u.type=='ugho':u.hp=1 # Dogs never steal opening Coil.
            b.combat_spells(own,foes,10)
            spells=[o for o in orders if o[0]=='cast']
            self.assertEqual([o[2] for o in spells],['silence'])
            effects[tc.handle]=['BNsi']
            b.combat_spells(own,foes,11)
            spells=[o for o in orders if o[0]=='cast']
            self.assertEqual([o[2] for o in spells],['silence','frostnova','deathcoil'])
            self.assertTrue(all(o[3]['target']==tc for o in spells))
            self.assertEqual(b.hero_pressure.tc_phase,'tauren')
            orders.clear();b.focus_ranged(own,foes,12)
            b.focus_ghouls([u for u in own if u.type=='ugho'],foes,12)
            self.assertEqual({o[2] for o in orders if o[0]=='attack'},{tc.handle})
            self.assertEqual(len([o for o in orders if o[0]=='attack']),9)

    def test_death_flight_loss_of_vision_and_invulnerability_switch_to_heads(self):
        for reason in ('dead','fled','hidden','invulnerable'):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene()
            self.assertIs(b.hero_pressure.orc_focus(g,own,foes,10),tc)
            fs=unit('Ofar',98,owner=1,x=300);fs.has_detail=True;fs.hp=1000;foes.append(fs)
            if reason=='dead':tc.hp=0
            if reason=='fled':tc.x=1800
            if reason=='hidden':foes.remove(tc)
            if reason=='invulnerable':effects[tc.handle]=['Bvul']
            target=b.hero_pressure.orc_focus(g,own,foes,11)
            self.assertIn(target.type,{'ohun','otbk'},reason)
            self.assertEqual(b.hero_pressure.tc_phase,'headhunters')
            if reason!='dead':self.assertNotIn(tc.handle,b.hero_pressure.dead_chiefs)
            orders.clear();b.focus_ghouls([u for u in own if u.type=='ugho'],foes,11)
            self.assertEqual({o[2] for o in orders if o[0]=='attack'},{target.handle})

    def test_clear_heads_before_other_units_then_keep_one_target(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.orc_focus(g,own,foes,10);tc.x=1800
        raider=unit('orai',97,owner=1,x=300);raider.has_detail=True;raider.hp=10;foes.append(raider)
        self.assertEqual(b.hero_pressure.orc_focus(g,own,foes,11).type,'otbk')
        foes[:]=[tc,raider]
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,12),raider)
        other=unit('ogru',96,owner=1,x=310);other.has_detail=True;other.hp=1;foes.append(other)
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,13),raider)
        raider.hp=0
        self.assertIs(b.hero_pressure.orc_focus(g,own,foes,14),other)

    def test_ghoul_approach_is_bounded_and_not_cancelled_by_generic_hold(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.orc_focus(g,own,foes,10)
        ghoul=own[0];g.current_target=lambda u:tc if u==ghoul else None
        b.stop_hero_chases([ghoul],10)
        self.assertFalse(orders)
        tc.x=1800;b.stop_hero_chases([ghoul],12)
        self.assertTrue(any(o[0]=='hold' for o in orders))
        orders.clear();tc.x=400;g.path_distance=lambda *a:None;effects[tc.handle]=['BNsi']
        b.focus_ghouls([ghoul],foes,13)
        self.assertFalse(orders)

    def test_wounded_heroes_then_destroyer_get_coil_never_ghouls(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=self.scene(kind)
            lich=own[6];dark=own[7];destroyer=own[8]
            lich.hp=200;dark.hp=200;destroyer.hp=200;own[0].hp=1
            for now,victim in ((10,lich),(12,dark),(14,destroyer)):
                b.heal_allies(own,now)
                self.assertIs([o for o in orders if o[0]=='cast'][-1][3]['target'],victim)
                victim.hp=victim.hp_max
            orders.clear();b.heal_allies(own,16,[own[0]])
            self.assertFalse(orders);self.assertFalse(heal_eligible(own[0]))

    def test_destroyer_rescue_precedes_opening_damage_coil(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();own[8].hp=200
        b.combat_spells(own,foes,10)
        coils=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil']
        self.assertEqual(len(coils),1);self.assertIs(coils[0][3]['target'],own[8])
        self.assertFalse(any(o[0]=='cast' and o[2]=='frostnova' for o in orders))
        effects[tc.handle]=['BNsi'];b.combat_spells(own,foes,11)
        self.assertTrue(any(o[0]=='cast' and o[2]=='frostnova' and o[3]['target']==tc for o in orders))

    def test_destroyer_under_fire_reserves_coil_before_half_health(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene();d=own[8];d.hp=.65*d.hp_max;d.x=0
        g.current_target=lambda u:d if u in foes[:2] else None
        self.assertTrue(b.reserve_coil_for_hero(dk,10))
        self.assertNotIn(d,b.heal_candidates(dk))

    def test_orc_sequence_does_not_carry_over_to_other_race(self):
        b,g,own,foes,orders,events,effects,dk,tc=self.scene()
        b.hero_pressure.select_strategy(g,own,foes,10)
        tc.type='Hmkg';foes[:]=[tc]
        self.assertIsNone(b.hero_pressure.select_strategy(g,own,foes,11))
        self.assertFalse(b.hero_pressure.tc_sequence)
        self.assertIsNone(b.hero_pressure.sequence_target)


class ScrollEfficiencyTests(unittest.TestCase):
    def scene(self):
        g=items.Game();events=[];locks={};c=Consumables(lambda e,**kw:events.append(dict(event=e,**kw)))
        for u in g.army:u.hp=u.hp_max
        carrier=g.heroes[1];g.bags[carrier.handle][0]='shea'
        return g,c,locks,events,carrier

    def test_some_wounds_and_only_two_half_health_units_do_not_use_scroll(self):
        for case in ('slight','two'):
            g,c,locks,events,h=self.scene()
            for u in g.army:u.hp=420
            if case=='two':g.army[0].hp=g.army[3].hp=250
            c.tick(g,g.army,[],10,locks)
            self.assertFalse(g.orders)

    def test_three_half_health_units_use_scroll_once_and_log_efficiency(self):
        g,c,locks,events,h=self.scene()
        for u in g.army[:3]:u.hp=300
        g.bags[g.heroes[0].handle][0]='shea'
        c.tick(g,g.army,[],10,locks)
        self.assertEqual(len(g.orders),1)
        self.assertEqual(events[-1]['half_health_units'],3)
        self.assertFalse(events[-1]['scroll_emergency'])
        self.assertEqual(events[-1]['effective_healing'],450)

    def test_large_group_requires_half_of_local_eligible_units(self):
        g,c,locks,events,h=self.scene()
        for i in range(6):
            u=unit('ugho',40+i,owner=0,x=100);u.hp=u.hp_max=340;g.army.append(u)
        for u in g.army[:3]:u.hp=200
        c.tick(g,g.army,[],10,locks);self.assertFalse(g.orders)
        for u in g.army[3:5]:u.hp=100
        c.tick(g,g.army,[],11,locks);self.assertEqual(len(g.orders),1)

    def test_restore_scroll_does_not_use_mana_as_excuse_or_waste_healing(self):
        g,c,locks,events,h=self.scene();g.bags[h.handle][0]='sres'
        for u in g.army:u.mana=0;u.hp=450
        c.tick(g,g.army,[],10,locks);self.assertFalse(g.orders)
        for u in g.army[:3]:u.hp_max=340;u.hp=170
        c.tick(g,g.army,[],11,locks);self.assertFalse(g.orders)
        for u in g.army[:3]:u.hp=50
        c.tick(g,g.army,[],12,locks);self.assertEqual(len(g.orders),1)

    def test_single_dying_hero_bypasses_group_delay_and_cast_lock(self):
        g,c,locks,events,h=self.scene();victim=g.heroes[0];victim.hp=20
        foe=unit('hfoo',90,owner=1,x=100)
        c.group_until=100;locks[h.handle]=100
        c.tick(g,g.army,[foe],10,locks)
        self.assertEqual(g.orders,[('use','Ulic','shea')])
        self.assertTrue(events[-1]['scroll_emergency']);self.assertTrue(events[-1]['overrode_cast_lock'])

    def test_personal_health_or_invulnerability_prevents_emergency_scroll(self):
        for item in ('phea','pnvl'):
            g,c,locks,events,h=self.scene();victim=g.heroes[0];victim.hp=100
            g.bags[victim.handle][0]=item
            c.tick(g,g.army,[unit('hfoo',90,owner=1,x=100)],10,locks)
            self.assertNotIn(('use','Ulic','shea'),g.orders)
            self.assertIn(('use','Udea',item),g.orders)

    def test_ready_coil_blocks_scroll_but_disabled_or_late_coil_does_not(self):
        for case in ('ready','stun','cooldown','late'):
            g,c,locks,events,h=self.scene();victim=g.heroes[2];victim.hp=100;dk=g.heroes[0]
            g.abilities=lambda u:[dict(code='AUdc',level=1)] if u==dk else []
            foe=unit('hfoo',90,owner=1,x=victim.x)
            if case=='stun':g.bs[dk.handle]=['BSTN']
            if case=='cooldown':g.cd[(dk.handle,'AUdc')]=5
            if case=='late':victim.hp=1;g.current_target=lambda u:victim
            c.tick(g,g.army,[foe],10,locks)
            self.assertEqual(('use','Ulic','shea') in g.orders,case!='ready',case)

    def test_emergency_does_not_override_engine_cooldown_or_reach(self):
        for case in ('cooldown','range','controlled','invulnerable'):
            g,c,locks,events,h=self.scene();victim=g.heroes[0];victim.hp=20
            if case=='cooldown':g.cd[(h.handle,'AIha')]=3
            if case=='range':h.x=1000
            if case=='controlled':g.bs[h.handle]=['BSTN']
            if case=='invulnerable':g.bs[victim.handle]=['Bvul']
            c.tick(g,g.army,[unit('hfoo',90,owner=1,x=100)],10,locks)
            self.assertFalse(g.orders,case)

    def test_pending_heal_has_short_observation_window_but_not_infinite_cover(self):
        g,c,locks,events,h=self.scene();victim=g.heroes[2];victim.hp=100
        pending=[dict(target=victim.handle,started=10,hp=100)]
        foe=unit('hfoo',90,owner=1,x=100)
        c.tick(g,g.army,[foe],10.2,locks,pending_heals=pending);self.assertFalse(g.orders)
        c.tick(g,g.army,[foe],11,locks,pending_heals=pending)
        self.assertEqual(g.orders,[('use','Ulic','shea')])

    def test_imminent_death_overrides_pending_heal_observation(self):
        g,c,locks,events,h=self.scene();victim=g.heroes[2];victim.hp=1
        pending=[dict(target=victim.handle,started=10,hp=100)]
        foe=unit('hfoo',90,owner=1,x=victim.x);g.current_target=lambda u:victim
        c.tick(g,g.army,[foe],10.2,locks,pending_heals=pending)
        self.assertEqual(g.orders,[('use','Ulic','shea')])

    def test_destroyers_count_but_statues_dead_and_distant_units_do_not(self):
        g,c,locks,events,h=self.scene()
        for code,key,x,hp in (('ubsp',80,100,300),('ubsp',81,100,300),('ucry',82,100,200),
                             ('uobs',83,100,1),('ugho',84,100,0),('ucry',85,2000,1)):
            u=unit(code,key,owner=0,x=x);u.hp=hp;u.hp_max=600;g.army.append(u)
        # Three hurt out of seven eligible is below the required half.
        c.tick(g,g.army,[],10,locks);self.assertFalse(g.orders)
        g.heroes[0].hp=200;c.tick(g,g.army,[],11,locks)
        self.assertEqual(len(g.orders),1)
        targets=events[-1]['targets']
        self.assertIn((80,0),targets)
        for key in (83,84,85):self.assertNotIn((key,0),targets)


if __name__=='__main__':unittest.main()
