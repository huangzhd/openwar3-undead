import unittest
from unittest.mock import Mock
from test_baseline import unit
import test_tc_pressure_01186 as pressure
import test_banshee_link_dust_01208 as banshee
import test_safe_rejoin_01207 as rejoin
from training import TrainingController
from undead.controller import Controller
from undead.frontline import impale,attack_frontline
from undead.hero_spell_telemetry import HERO_CODES,ORDERS


class FrontlineTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects,dk,tc=pressure.TcFirstTests().scene(kind)
        cl=unit('Ucrl',81,owner=0,x=100);abo=unit('uabo',82,owner=0,x=100)
        for u in (cl,abo):u.hp=u.hp_max=1000;u.mana=300;u.mana_max=300;u.has_detail=True
        own.extend([cl,abo]);old=g.abilities
        g.abilities=lambda u:([dict(code='AUim',level=1),dict(code='AUts',level=1)] if u.type=='Ucrl' else
                              [dict(code='AUfu',level=1),dict(code='AUfn',level=1)] if u.type=='Ulic' else old(u))
        g.current_target=lambda _:None
        return b,g,own,foes,orders,events,effects,dk,cl,abo

    def test_shared_hero_skill_order_and_telemetry_support(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            for u in own:u.skill_points=0
            g.learn=Mock(return_value=True)
            for n in range(1,11):
                cl.level=n;cl.skill_points=1;b.skills(n*2)
            self.assertEqual([c.args[1] for c in g.learn.call_args_list],
                             ['AUim','AUts','AUim','AUts','AUim','AUls','AUts','AUcb','AUcb','AUcb'])
            self.assertIn('AUim',HERO_CODES['Ucrl']);self.assertEqual(ORDERS['impale'],'AUim')

    def test_coil_priority_and_health_gates_in_both_controllers(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            expected=['Ulic','Nbrn','Ucrl','ubsp','uabo','ucry']
            patients=[next(u for u in own if u.type==code) for code in expected]
            for u in patients:u.hp=u.hp_max*.3
            # Only one fiend is hurt, and a full-mana DK cannot heal himself.
            for i,victim in enumerate(patients):
                b.heal_allies(own,10+i*2)
                coil=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil'][-1]
                self.assertIs(coil[3]['target'],victim)
                victim.hp=victim.hp_max
            for u in (cl,abo):
                u.hp=u.hp_max*.51;self.assertNotIn(u,b.heal_candidates(dk))
                u.hp=u.hp_max*.5;self.assertIn(u,b.heal_candidates(dk))
            self.assertNotIn(dk,b.heal_candidates(dk))

    def test_shell_covers_crypt_lord_and_abominations_before_contact(self):
        b,g,own,foes,orders,events,effects,dk,tc,caster=banshee.BansheeLinkDustTests().scene()
        extra=[unit('Ucrl',81,owner=0),unit('uabo',82,owner=0)]
        for u in extra:u.hp=u.hp_max=1000;u.has_detail=True
        own.extend(extra)
        for now in range(1,7):
            b.banshee_support.tick(b,own,[],now,True)
            for o in orders:
                if o[0]=='cast' and o[2]=='antimagicshell':effects[o[3]['target'].handle]=['Bams']
        targets=[o[3]['target'] for o in orders if o[0]=='cast' and o[2]=='antimagicshell']
        self.assertTrue(all(u in targets for u in extra));self.assertEqual(len(targets),len({u.handle for u in targets}))
        orders.clear();b.banshee_support.tick(b,own,foes,10,False)
        self.assertFalse(any(o[0]=='cast' and o[2]=='antimagicshell' for o in orders))

    def test_impale_prefers_multiple_valid_ground_targets_without_moving(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            foes[:]=[unit('ogru',100+i,x=x) for i,x in enumerate((280,430,570))]
            for i,e in enumerate(foes):e.owner=1;e.y=(-80,20,70)[i];e.has_detail=True
            hero=unit('Otch',110,x=100);hero.y=450;hero.has_detail=True;foes.append(hero)
            behind=unit('ogru',111,x=-150);behind.has_detail=True;foes.append(behind)
            impale(b,own,foes,10)
            casts=[o for o in orders if o[0]=='cast' and o[2]=='impale']
            self.assertEqual(len(casts),1)
            prediction=next(data for event,data in events if event=='battle_impale_attempt')
            self.assertEqual(prediction['predicted_count'],3)
            self.assertNotIn(hero.handle,prediction['predicted_targets'])
            self.assertNotIn(behind.handle,prediction['predicted_targets'])
            self.assertFalse(any(o[0] in ('move','attack_move') for o in orders))
            impale(b,own,foes,11);self.assertEqual(len(orders),1)

    def test_impale_rejects_air_mechanical_immune_hidden_and_out_of_range(self):
        for code,why in (('owyv','air'),('ocat','mechanical'),('ogru','immune'),('ogru','hidden'),('ogru','far')):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene()
            e=unit(code,101,x=400);e.has_detail=True
            if why=='immune':effects[e.handle]=['Bvul']
            if why=='hidden':e.visible_to=lambda _:False
            if why=='far':e.x=1200
            foes[:]=[e];impale(b,own,foes,10)
            self.assertFalse(orders,why)

    def test_impale_respects_mana_cooldown_pull_cast_lock_and_control(self):
        for reason in ('mana','cooldown','pull','blocked','lock','silence','low','unknown'):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene();blocked=set()
            if reason=='mana':cl.mana=99
            if reason=='cooldown':g.cooldown=lambda *a:5
            if reason=='pull':b.micro.pulling.add(cl.handle)
            if reason=='blocked':blocked.add(cl.handle)
            if reason=='lock':b.cast_until[cl.handle]=12
            if reason=='silence':effects[cl.handle]=['BNsi']
            if reason=='low':cl.hp=400
            if reason=='unknown':g.abilities=lambda u:[]
            impale(b,own,foes,10,blocked);self.assertFalse(orders,reason)

    def test_lich_armors_frontline_lord_and_never_overwrites_rescue_or_buff(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            b.frost_armor(own,foes,10)
            armor=[o for o in orders if o[0]=='cast' and o[2]=='frostarmor']
            self.assertEqual(len(armor),1);self.assertIs(armor[0][3]['target'],cl)
            effects[cl.handle]=['BUfa'];b.frost_armor(own,foes,12)
            self.assertEqual(len([o for o in orders if o[0]=='cast']),1)
            effects.clear();lich=next(u for u in own if u.type=='Ulic')
            lich.hp=100;foes[0].type='ogru';foes[0].x=60
            g.current_target=lambda u:lich if u is foes[0] else None
            b.frost_armor(own,foes,14)
            self.assertIs([o for o in orders if o[0]=='cast'][-1][3]['target'],lich)

    def test_tanks_use_attack_move_without_reinforcement_or_focus_overwrites(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            b.engage_battle([cl,abo],foes,10)
            self.assertEqual({o[1] for o in orders if o[0]=='attack_move'},{cl.handle,abo.handle})
            self.assertFalse(any(o[0] in ('move','attack','hold') for o in orders))
            before=len(orders);b.engage_battle([cl,abo],foes,10.5);self.assertEqual(len(orders),before)
            b.micro.pulling.add(abo.handle);b.cast_until[cl.handle]=30;orders.clear()
            b.fight([cl,abo],foes,20);self.assertFalse(orders)

    def test_healthy_tanks_stay_and_low_tanks_escape_even_with_ready_coil(self):
        for code in ('Ucrl','uabo'):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene()
            u=cl if code=='Ucrl' else abo
            foes[0].x=150
            target=lambda e:u.handle if e is foes[0] else None
            args=(own,foes,10,target,g.path_distance,lambda *p:True,(-1500,0))
            moves=b.micro.plan(*args,attack_range=lambda _:550,aggressive_battle=True)
            self.assertNotIn(u.handle,moves)
            u.hp=400
            moves=b.micro.plan(*args,attack_range=lambda _:550,aggressive_battle=True)
            self.assertIn(u.handle,b.micro.pulling);self.assertIn(u.handle,moves)

    def test_tanks_return_to_support_after_danger_clears(self):
        helper=rejoin.SafeRejoinTests()
        for code in ('Ucrl','uabo'):
            b,g,own,foes,orders,events,effects,u=helper.scene(code)
            u.is_hero=code=='Ucrl'
            pulls=helper.ready(b,own,foes,u)
            self.assertGreater(pulls[u.handle][0],u.x+300)
            g.current_target=lambda e:u if e in foes else None
            b.rejoin_battle_units(own,foes,14,pulls)
            self.assertIsNone(b.battle_rejoin[u.handle]['quiet'])

    def test_wounded_frontline_returns_to_melee_only_behind_a_healthy_tank(self):
        helper=rejoin.SafeRejoinTests()
        for code in ('Ucrl','uabo'):
            b,g,own,foes,orders,events,effects,u=helper.scene(code);u.is_hero=code=='Ucrl'
            foe=foes[0];foe.type='ogru';foes[:]=[foe]
            tank=own[1];tank.x=foe.x-50
            g.current_target=lambda v:tank if v is foe else None
            pulls=helper.ready(b,own,foes,u);u.x,u.y=pulls[u.handle]
            b.rejoin_battle_units(own,foes,14,pulls)
            self.assertIn(('attack',u.handle,foe.handle),orders)
            escape=(u.x-500,u.y);pulls={u.handle:escape};orders.clear()
            g.current_target=lambda v:u if v is foe else None
            b.rejoin_battle_units(own,foes,15,pulls)
            self.assertEqual(pulls[u.handle],escape);self.assertFalse(orders)

    def test_shared_combat_entry_casts_impale_and_reserves_coil_for_abomination(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene(kind)
            abo.hp=abo.hp_max*.4
            b.combat_spells(own,foes,10)
            self.assertTrue(any(o[0]=='cast' and o[2]=='impale' for o in orders))
            coils=[o for o in orders if o[0]=='cast' and o[2]=='deathcoil']
            self.assertTrue(coils);self.assertIs(coils[0][3]['target'],abo)

    def test_tanks_receive_front_slots_only_before_combat(self):
        b,g,own,foes,orders,events,effects,dk,cl,abo=self.scene()
        b.enemy_main=(2000,0);b.prepare_battle(1,army=own,foes=[])
        lich=next(u for u in own if u.type=='Ulic')
        self.assertGreater(b.prep_points[cl.handle][0],b.prep_points[lich.handle][0])
        self.assertGreater(b.prep_points[abo.handle][0],b.prep_points[lich.handle][0])
        b.battle_started=True;b.battle_last_enemy=2;orders.clear()
        b.prepare_battle(2,army=own,foes=foes)
        self.assertFalse(orders)


if __name__=='__main__':unittest.main()
