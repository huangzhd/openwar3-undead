import unittest
from unittest.mock import Mock
import test_dispel_priority_01142 as priority
import test_shared_battle_01181 as shared
from test_baseline import unit
from test_micro_loot import dist
from undead.controller import Controller
from training import TrainingController
from undead.policy import Action


class DispelFirstTests(unittest.TestCase):
    def scene(self,kind=Controller):
        b,g,own,foes,orders,events,effects=shared.SharedBattleTests().scene(kind)
        car=own[8];car.x=100;car.hp=100
        dk=unit('Udea',70,owner=0,x=-350);dk.hp=dk.hp_max=800;dk.mana=300;dk.has_detail=True
        own.append(dk);effects[dk.handle]=['BOhx']
        b.micro.pulling.add(car.handle)
        # Keep the TC far away so this test isolates dispel/retreat scheduling.
        foes[2].x=1800
        return b,g,own,foes,orders,events,effects,car,dk

    def test_low_hp_under_fire_dispels_before_retreat_and_moves_after_windup(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car,dk=self.scene(kind)
            pulls={car.handle:(-900,0)}
            b.battle_actions(own,foes,10,pulls)
            self.assertTrue(any(o[:3]==('cast',car.handle,'devourmagic') for o in orders))
            b.go_raw([car],pulls[car.handle],10)
            self.assertFalse(any(o[0]=='move' and o[1]==car.handle for o in orders))
            b.go_raw([car],pulls[car.handle],11.3)
            self.assertTrue(any(o[0]=='move' and o[1]==car.handle for o in orders))

    def test_unavailable_or_rejected_dispel_does_not_delay_retreat(self):
        for why in ('cooldown','range','rejected','protected_tc'):
            b,g,own,foes,orders,events,effects,car,dk=self.scene()
            if why=='cooldown':g.cooldown=lambda u,a:5 if a=='Advm' else 0
            if why=='range':dk.x=-2000
            if why=='rejected':
                old=g.cast
                g.cast=lambda u,spell,**kw:(old(u,spell,**kw) and spell!='devourmagic')
            if why=='protected_tc':
                foes[2].x=dk.x;effects[foes[2].handle]=['BNsi'];b.silence_protected_until={foes[2].handle:22}
            pulls={car.handle:(-900,0)};b.battle_actions(own,foes,10,pulls)
            b.go_raw([car],pulls[car.handle],10)
            self.assertTrue(any(o[0]=='move' and o[1]==car.handle for o in orders),why)

    def test_exclusive_block_and_teleport_still_protect_the_owner(self):
        for why in ('blocked','teleport'):
            b,g,own,foes,orders,events,effects,car,dk=self.scene()
            if why=='teleport':b.teleport={'hero':car.handle}
            b.battle_actions(own,foes,10,{car.handle:(-900,0)},blocked={car.handle} if why=='blocked' else ())
            self.assertFalse(any(o[:3]==('cast',car.handle,'devourmagic') for o in orders))

    def test_only_existing_destroyer_is_exempt_from_pullback_block(self):
        b,g,own,foes,orders,events,effects,car,dk=self.scene()
        statue=own[9];b.destroyer.tick=Mock()
        b.battle_actions(own,foes,10,{car.handle:(-900,0),statue.handle:(-900,0)})
        blocked=b.destroyer.tick.call_args.args[-1]
        self.assertNotIn(car.handle,blocked);self.assertIn(statue.handle,blocked)

    def test_existing_destroyer_can_eat_summon_while_army_retreats(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        effects.clear();b.action=Action.RETREAT;d.tick(b,own,foes,10)
        self.assertEqual(orders[-1][1],'devourmagic')
        self.assertEqual(events[-1]['reason'],'enemy_summon')

    def test_ally_unit_hex_beats_summon_and_other_hero_debuff(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        effects[hero.handle]=['Bslo']
        fiend=unit('ucry',90,owner=0,x=-500);fiend.has_detail=True;own.append(fiend)
        effects[fiend.handle]=['BOhx'];d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['target'],fiend.handle)
        self.assertEqual(events[-1]['reason'],'ally_hex')

    def test_summon_beats_nonhex_hero_debuff(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        effects[hero.handle]=['Bslo'];d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['reason'],'enemy_summon')

    def test_offset_frees_hex_without_touching_silenced_tc(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        hero.x=100;tc=unit('Otch',90,owner=1,x=450);tc.has_detail=True
        foes[:]=[tc];effects[tc.handle]=['BNsi']
        d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['reason'],'ally_hex')
        point=orders[-1][2];p=(point['x'],point['y'])
        self.assertLessEqual(dist(p,hero),192.001);self.assertLessEqual(dist(p,own[0]),600)
        self.assertGreater(dist(p,tc),events[-1]['protected_heroes'][0]['radius'])

    def test_unavoidable_silence_overlap_is_still_skipped(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        tc=unit('Otch',90,owner=1,x=hero.x+30);tc.has_detail=True
        foes[:]=[tc];effects[tc.handle]=['BNsi']
        d.tick(b,own,foes,10)
        self.assertFalse(orders)
        self.assertEqual(events[-1]['reason'],'no_safe_reachable_point')

    def test_blocked_diagnostics_are_rate_limited(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=priority.DispelPriorityTests().scene()
        for now in (10,10.25,11,12,15):d.tick(b,own,foes,now,{own[0].handle})
        self.assertEqual(sum(e['event']=='destroyer_dispel_deferred' for e in events),2)
        self.assertFalse(orders)


if __name__=='__main__':unittest.main()
