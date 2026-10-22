import unittest
import test_orc_melee_01193 as melee
import test_blight_dispel_01194 as opening
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController


class WebFinishTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,car,troops,tc,fs=melee.OrcMeleeTests().scene(kind)
        wyvern=unit('owyv',140,owner=1,x=300);wyvern.hp=wyvern.hp_max=570;wyvern.has_detail=True;wyvern.mana=0
        foes.append(wyvern);effects[wyvern.handle]=['Bwea']
        return b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern

    def test_grounded_wyvern_then_grunt_then_raider_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern=self.scene(kind)
            for now,victim in ((10,wyvern),(12,troops[0]),(14,troops[2])):
                if now==12:foes.remove(wyvern)
                if now==14:foes[:]=[e for e in foes if e.type!='ogru']
                orders.clear();b.focus_ranged(own,foes,now);b.attack_destroyers(own,foes,now)
                shots=[o for o in orders if o[0]=='attack']
                self.assertTrue(shots);self.assertEqual({o[2] for o in shots},{victim.handle})
                self.assertIn(car.handle,{o[1] for o in shots})

    def test_web_expiry_hidden_invulnerability_or_distance_releases_target(self):
        for why in ('expired','hidden','invulnerable','distant'):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern=self.scene()
            b.focus_ranged(own,foes,10)
            if why=='expired':effects[wyvern.handle]=[]
            if why=='hidden':foes.remove(wyvern)
            if why=='invulnerable':effects[wyvern.handle].append('Bvul')
            if why=='distant':wyvern.x=1800
            orders.clear();b.focus_ranged(own,foes,12)
            self.assertEqual(b.ranged_focus,troops[0].handle)

    def test_low_tc_finisher_temporarily_overrides_webbed_wyvern(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern=self.scene(kind)
            tc.hp=30;b.focus_ranged(own,foes,10);b.attack_destroyers(own,foes,10)
            shots=[o for o in orders if o[0]=='attack']
            self.assertEqual({o[2] for o in shots},{tc.handle})
            tc.x=1800;orders.clear();b.focus_ranged(own,foes,12)
            self.assertEqual(b.ranged_focus,wyvern.handle)

    def test_available_lethal_nc_selects_tc_without_chasing_or_waiting(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern=self.scene(kind)
            for u in own:
                if u.type in {'ucry','Nbrn'} and u is not own[0]:u.x=-1500
            own[:]=[own[i] for i in (0,1,6,8,len(own)-1)]
            tc.hp=170
            self.assertGreater(b.hero_pressure.estimate(g,own,tc),2.5)
            b.combat_spells(own,foes,10)
            damage=[o for o in orders if o[0]=='cast' and o[2] in {'frostnova','deathcoil'}]
            self.assertEqual([o[2] for o in damage],['frostnova','deathcoil'])
            self.assertTrue(all(o[3]['target'] is tc for o in damage))
            self.assertFalse(b.opening_nc_waiting)

    def test_hero_rescue_or_spell_cooldown_prevents_false_nc_finisher(self):
        for why in ('rescue','cooldown'):
            b,g,own,foes,orders,events,effects,car,troops,tc,fs,wyvern=self.scene()
            for u in own:
                if u.type in {'ucry','Nbrn'} and u is not own[0]:u.x=-1500
            own[:]=[own[i] for i in (0,1,6,8,len(own)-1)]
            tc.hp=170
            if why=='rescue':next(u for u in own if u.type=='Ulic').hp=200
            else:g.cooldown=lambda u,code:5 if code=='AUdc' else 0
            b.combat_spells(own,foes,10)
            self.assertIsNone(b.hero_pressure.tc_burst)
            self.assertFalse(any(o[0]=='cast' and o[2]=='deathcoil' and o[3]['target'] is tc for o in orders))

    def test_waiting_spreads_laterally_and_queues_hold_without_advancing(self):
        for kind in (TrainingController,):
            b,g,own,foes,orders,events,effects,car,dk,bag,uses=opening.BlightDispelTests().scene(kind)
            center=(sum(u.x for u in own)/len(own),sum(u.y for u in own)/len(own))
            b.prepare_battle(10,army=own,target=(2000,center[1]),foes=foes)
            moves=[o for o in orders if o[0]=='move'];self.assertTrue(moves)
            self.assertTrue(all(o[2][0]<=center[0]+.001 for o in moves))
            self.assertGreater(len({round(o[2][1]) for o in moves}),3)
            self.assertTrue(all(('hold_after',o[1]) in orders for o in moves))
            orders.clear();b.go(own,(2000,0),11,attack=True);b.engage_battle(own,foes,11)
            self.assertFalse(any(o[0] in {'move','attack','attack_move'} for o in orders))
            self.assertFalse(any(o[0]=='hold' and o[1] in {m[1] for m in moves} for o in orders))

    def test_no_skull_preparation_also_waits_and_protected_units_do_not_move(self):
        b,g,own,foes,orders,events,effects,car,dk,bag,uses=opening.BlightDispelTests().scene(TrainingController)
        bag.clear();b.cast_until[own[6].handle]=20
        b.prepare_battle(10,army=own,foes=foes,blocked={own[0].handle})
        self.assertTrue(b.blight_waiting)
        self.assertFalse(any(o[1] in {own[0].handle,own[6].handle} for o in orders))
        self.assertFalse(any(o[0] in {'attack','attack_move'} for o in orders))


if __name__=='__main__':unittest.main()
