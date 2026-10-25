import unittest
from test_baseline import unit
import test_tc_pressure_01186 as pressure
import test_equipment as equipment
import test_safe_rejoin_01207 as rejoin
from undead.controller import Controller
from undead.equipment import gear_owner,AGILITY_ITEMS,DK_RINGS
from training import TrainingController


class WyvernArmyTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene(kind)
        foes[:]=[tc]
        birds=[unit('owyv',200+i,owner=1,x=300+i*10) for i in range(4)]
        for e in birds:e.hp=e.hp_max=570;e.has_detail=True;e.mana=0
        foes.extend(birds);effects[birds[1].handle]=['Bwea'];effects[birds[2].handle]=['Bwea']
        birds[1].hp=300;g.current_target=lambda _:None
        return b,g,own,foes,orders,events,effects,dk,tc,birds

    def test_default_key_hero_policy_is_overridden_and_nova_and_attacks_share_webbed_bird(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene(kind)
            tc.hp=1 # Even a tempting TC finisher must not consume the anti-air opening.
            b.combat_spells(own,foes,10)
            novas=[o for o in orders if o[0]=='cast' and o[2]=='frostnova']
            self.assertEqual(len(novas),1);self.assertIs(novas[0][3]['target'],birds[1])
            b.focus_ranged(own,foes,11)
            shots=[o for o in orders if o[0]=='attack']
            self.assertTrue(shots);self.assertEqual({o[2] for o in shots},{birds[1].handle})
            self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))

    def test_finish_one_webbed_target_then_next_and_return_to_heroes_after_air_is_gone(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene()
        first=b.hero_pressure.choose(g,own,foes,10);self.assertIs(first,birds[1])
        birds[2].hp=1
        self.assertIs(b.hero_pressure.choose(g,own,foes,11),first)
        first.hp=0;first.alive=False
        self.assertIs(b.hero_pressure.choose(g,own,foes,12),birds[2])
        foes[:]=[tc]
        self.assertIs(b.hero_pressure.choose(g,own,foes,13),tc)
        self.assertFalse(b.hero_pressure.wyvern_priority)

    def test_web_expiry_or_immunity_releases_target_without_turning_to_tc(self):
        for why in ('expired','immune','hidden','distant'):
            b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene()
            self.assertIs(b.hero_pressure.choose(g,own,foes,10),birds[1])
            if why=='expired':effects[birds[1].handle]=[]
            if why=='immune':effects[birds[1].handle]=['Bwea','Bvul']
            if why=='hidden':foes.remove(birds[1])
            if why=='distant':birds[1].x=1800
            self.assertIs(b.hero_pressure.choose(g,own,foes,12),birds[2])

    def test_single_wyvern_does_not_override_normal_core_hero_policy(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene()
        foes[:]=[tc,birds[0]]
        self.assertIs(b.hero_pressure.choose(g,own,foes,10),tc)
        self.assertFalse(b.hero_pressure.wyvern_priority)

    def test_heal_lich_then_half_health_fiend_and_keep_coil_for_rescue(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene(kind)
            lich=next(u for u in own if u.type=='Ulic');fiend=own[0]
            lich.hp=lich.hp_max*.45;fiend.hp=fiend.hp_max*.45
            b.combat_spells(own,foes,10)
            coils=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil']
            self.assertIs(coils[0][3]['target'],lich)
            lich.hp=lich.hp_max;b.combat_spells(own,foes,12)
            coils=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil']
            self.assertIs(coils[-1][3]['target'],fiend)
            fiend.hp=fiend.hp_max;orders.clear();b.combat_spells(own,foes,14)
            self.assertTrue(b.reserve_coil_for_hero(dk,14))
            self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' for o in orders))

    def test_blocked_or_cooling_lich_cannot_spend_nova_on_another_target(self):
        for why in ('blocked','cooldown','silence','mana','range'):
            b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene();lich=own[6];blocked=set()
            if why=='blocked':blocked.add(lich.handle)
            if why=='cooldown':g.cooldown=lambda u,c:5 if c=='AUfn' else 0
            if why=='silence':effects[lich.handle]=['BNsi']
            if why=='mana':lich.mana=0
            if why=='range':
                for bird in birds:bird.x=1400
            b.combat_spells(own,foes,10,blocked)
            self.assertFalse(any(o[0]=='cast' and o[2]=='frostnova' for o in orders),why)

    def test_generic_fight_does_not_resume_hero_burst_and_dk_stays_support(self):
        b,g,own,foes,orders,events,effects,dk,tc,birds=self.scene()
        tc.hp=1;b.fight(own,foes,10);b.attack_dk(own,foes,10)
        self.assertFalse(any(o[0]=='cast' and o[3].get('target') is tc for o in orders))
        self.assertFalse(any(o[0]=='attack' and o[2]==tc.handle for o in orders))

    def test_opening_ring_circlet_swap_matches_real_bags_without_dropping(self):
        fixture=equipment.EquipmentTests();g,e,events=fixture.setup_game()
        g.inv[g.dk.handle]=['phea','rnec','shea','cnob','cnob',None]
        g.inv[g.lich.handle]=['shea','pnvl','sror','rde2','rde1',None]
        before=sorted(c for bag in g.inv.values() for c in bag if c)
        for now in range(1,60,3):
            if e.tick(g,g.heroes,[],now,{}):fixture.observed_transfer(g)
        self.assertIn('rde1',g.inv[g.dk.handle]);self.assertIn('rde2',g.inv[g.dk.handle])
        self.assertEqual(g.inv[g.lich.handle].count('cnob'),2)
        self.assertEqual(before,sorted(c for bag in g.inv.values() for c in bag if c))

    def test_agility_goes_to_dark_ranger_and_int_damage_to_lich(self):
        for code in ('rag1','belv','rin1','rat6','cnob'):
            fixture=equipment.EquipmentTests();g,e,events=fixture.setup_game()
            dark=unit('Nbrn',30,owner=0);g.heroes.append(dark);g.inv[dark.handle]=[None]*6
            g.inv[g.dk.handle][0]=code
            for now in (1,4,7):
                if e.tick(g,g.heroes,[],now,{}):fixture.observed_transfer(g)
            receiver=dark if code in AGILITY_ITEMS else g.lich
            self.assertIn(code,g.inv[receiver.handle])
        for code in DK_RINGS:self.assertEqual(gear_owner(code),'Udea')

    def test_no_gear_transfer_in_combat_or_without_the_correct_hero(self):
        fixture=equipment.EquipmentTests();g,e,_=fixture.setup_game()
        g.inv[g.dk.handle][0]='rag1'
        self.assertFalse(e.tick(g,g.heroes,[],1,{}));self.assertFalse(g.transfers)
        g.inv[g.lich.handle][0]='rde2'
        self.assertFalse(e.tick(g,g.heroes,[unit('owyv',90,owner=1,x=200)],4,{}))
        self.assertFalse(e.tick(g,g.heroes,[],5,{},potions_only=True));self.assertFalse(g.transfers)

    def test_dk_rejoins_after_one_safe_second_with_lich_and_fiends_in_coil_range(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk=rejoin.SafeRejoinTests().scene(kind=kind)
            b.hero_pressure.wyvern_priority=True
            pulls={dk.handle:(dk.x,dk.y)};b.rejoin_battle_units(own,foes,10,pulls)
            self.assertEqual(pulls[dk.handle],(dk.x,dk.y))
            b.rejoin_battle_units(own,foes,11,pulls);point=pulls[dk.handle]
            self.assertGreater(point[0],dk.x+300)
            self.assertLessEqual(g.dist(point,own[6]),700)
            fiends=[u for u in own if u.type=='ucry']
            self.assertGreaterEqual(sum(g.dist(point,u)<=700 for u in fiends),len(fiends)/2)
            g.current_target=lambda u:dk if u in foes else None
            b.rejoin_battle_units(own,foes,12,pulls)
            self.assertIsNone(b.battle_rejoin[dk.handle]['point'])


if __name__=='__main__':unittest.main()
