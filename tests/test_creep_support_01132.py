import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_coil as coil_tests
import test_support_fan_01122 as fan_tests
from undead.controller import Controller
from undead.ch_resummon import CHResummon


class CreepManaTests(unittest.TestCase):
    def scene(self):
        dk=unit('Udea',1,0,600);lich=unit('Ulic',2,40,600)
        army=[dk,lich]+[unit('ucry',10+i,i*30,600) for i in range(4)]
        foe=unit('ngnw',90,150,157);foe.owner=12
        b,casts,attacks=coil_tests.CoilTests().game(army)
        b.g.raw.my_heroes=lambda:[dk,lich];b.g.me=lambda:0
        b.g.creeps=lambda:[foe];b.g.buffs=lambda u:[];b.g.enemies=lambda:[]
        return b,army,dk,lich,foe,casts

    def test_two_heroes_do_not_dump_mana_into_last_creep(self):
        b,a,dk,l,e,casts=self.scene();b.fight(a,[e],500)
        self.assertFalse(casts)

    def test_full_mana_allows_one_cast_then_requires_real_drop_and_refill(self):
        b,a,dk,l,e,casts=self.scene();dk.mana=0;l.mana=l.mana_max
        b.fight(a,[e],500);self.assertEqual(casts,[('frostnova','ngnw')])
        b.fight(a,[e],502);self.assertEqual(len(casts),1) # Stale full-mana observation.
        l.mana=175;b.fight(a,[e],504);self.assertEqual(len(casts),1)
        l.mana=l.mana_max;b.fight(a,[e],510);self.assertEqual(len(casts),2)

    def test_full_dk_mana_gets_one_coil_not_a_repeat_on_same_snapshot(self):
        b,a,dk,l,e,casts=self.scene();dk.mana=dk.mana_max
        b.fight(a,[e],500);b.fight(a,[e],502)
        self.assertEqual(casts,[('deathcoil','ngnw')])

    def test_distant_lich_does_not_restore_unrestricted_dk_creep_spending(self):
        b,a,dk,l,e,casts=self.scene();l.x=2000
        b.fight([u for u in a if u is not l],[e],500)
        self.assertFalse(casts)

    def test_urgent_rescue_and_player_combat_keep_their_exception(self):
        b,a,dk,l,e,casts=self.scene()
        self.assertTrue(b.creep_mana.allow(b,l,a,[e],500,125,rescue=True))
        e.owner=1
        self.assertTrue(b.creep_mana.allow(b,l,a,[e],500,125))

    def test_ordinary_neutral_armor_requires_full_mana(self):
        b,a,dk,l,e,casts=self.scene();e.type='nogr';e.x=80
        b.g.current_target=lambda u:dk if u is e else None
        b.g.abilities=lambda u:[dict(code='AUfu',level=1)]
        b.frost_armor(a,[e],500);self.assertFalse(casts)
        l.mana=l.mana_max;b.frost_armor(a,[e],502)
        self.assertEqual(casts,[('frostarmor','Udea')])


class EffectiveStatueTests(unittest.TestCase):
    def test_recorded_idle_mana_statue_moves_within_cast_range_of_lich(self):
        b,g,events=fan_tests.StatueTests().scene()
        data=json.loads((Path(__file__).parent/'fixtures/ch-statue-idle-01132.json').read_text(encoding='utf-8'))
        g.army=[N(**{**r,'handle':tuple(r['handle'])}) for r in data['own']]
        for u in g.army:
            key=':'.join(map(str,u.handle))
            if key in data['roles']:b.army_recovery.statue_modes[u.handle]={'mode':data['roles'][key]}
        b.army_recovery.safe_path=lambda b,start,end,hostiles,**kwargs:dist(start,end)
        b.statue_support.tick(b,g.army,[],data['clock'])
        lich=next(u for u in g.army if u.type=='Ulic')
        move=next(o for o in g.orders if o[0]=='move' and o[1]==(18737,81748))
        self.assertLessEqual(dist(lich,move[2]),220)

    def test_supply_cast_has_recipient_evidence_and_is_not_cancelled_by_hold(self):
        b,g,events=fan_tests.StatueTests().scene();u=g.statues[0];u.x=0
        g.army=[u,g.heroes[0]];g.heroes[0].x=0;g.heroes[0].hp=300
        b.army_recovery.statue_modes[u.handle]={'mode':'life'}
        b.statue_support.tick(b,g.army,[],10)
        self.assertIn(('cast',u.handle,'replenishlife'),g.orders)
        self.assertNotIn(('hold',u.handle),g.orders)
        self.assertFalse(any(e['event']=='statue_supply_recipients_observed' for e in events))
        g.heroes[0].hp+=10;g.buffs=lambda v:['Brpl'] if v is g.heroes[0] else []
        b.statue_support.tick(b,g.army,[],11)
        self.assertTrue(any(e['event']=='statue_supply_recipients_observed' for e in events))
        self.assertNotIn(('hold',u.handle),g.orders)

    def test_receipt_without_recipient_buff_is_not_counted_as_supply(self):
        b,g,events=fan_tests.StatueTests().scene();u=g.statues[0]
        g.army=[u,g.heroes[0]];u.x=g.heroes[0].x=0;g.heroes[0].hp=300
        b.army_recovery.statue_modes[u.handle]={'mode':'life'}
        b.statue_support.tick(b,g.army,[],10);b.statue_support.observe_supply(g,14)
        self.assertTrue(any(e['event']=='statue_supply_unconfirmed' for e in events))
        self.assertFalse(any(e['event']=='statue_supply_recipients_observed' for e in events))

    def test_low_health_under_threat_takes_priority_over_supply_cast(self):
        b,g,events=fan_tests.StatueTests().scene();u=g.statues[0];u.x=0
        u.hp=u.hp_max*.4
        b.army_recovery.statue_modes[u.handle]={'mode':'life'}
        foe=unit('hfoo',90,100);foe.owner=1
        b.statue_support.tick(b,g.army,[foe],10)
        self.assertFalse(any(o[0]=='cast' and o[1]==u.handle for o in g.orders))

    def test_fan_destinations_leave_real_dk_lane_and_separation(self):
        b,g,events=fan_tests.FanTests().scene()
        b.battle_formation.step(b,g.army,g.foes,g.foes[0],10)
        moves=[o for o in g.orders if o[0]=='move']
        self.assertEqual(len(moves),2);self.assertGreaterEqual(dist(moves[0][2],moves[1][2]),170)
        self.assertTrue(all(o[1] not in {u.handle for u in g.heroes+g.statues} for o in moves))


class CHResummonTests(unittest.TestCase):
    def scene(self):
        dk=unit('Udea',1,500,600);yard=unit('ugrv',9,0,900);skeleton=unit('uske',2,500)
        own=[dk,skeleton];events=[];orders=[];bag=['rnec']
        g=N(dist=dist,path_distance=dist,inventory=lambda u:bag,my_buildings=lambda codes:[yard],
            production=lambda u:None,cooldown=lambda *a:0,units=lambda side,codes:[u for u in own if u.type in codes])
        b=N(g=g,home=yard,attack_committed=False,battle_enemies=[],micro=N(pulling=set()),cast_until={},
            creeping=N(map_alias='CH',cleared={'turtle'},ch_home_opening=lambda home:[{'id':'turtle'},{'id':'ogre'}],
                       safe_route=lambda *a:True,pause=lambda *a:None),set_intent=lambda *a:None,
            go=lambda army,p,now:orders.append(('move',p)),use_rod=lambda *a:orders.append(('rod',)) or True)
        s=CHResummon(lambda e,**kw:events.append(dict(event=e,**kw)))
        return b,s,dk,own,orders,events

    def test_travel_cast_and_two_new_skeletons_required_before_second_camp(self):
        b,s,dk,own,orders,events=self.scene()
        self.assertTrue(s.tick(b,own,200));self.assertEqual(orders,[('move',(0,0))])
        dk.x=0;self.assertTrue(s.tick(b,own,205));self.assertEqual(orders[-1],('rod',))
        self.assertTrue(s.tick(b,own,206));self.assertFalse(s.done)
        own.extend([unit('uske',3,0),unit('uske',4,0)])
        self.assertFalse(s.tick(b,own,207));self.assertTrue(s.done)
        self.assertEqual(events[-1]['reason'],'two_new_skeletons_observed')

    def test_other_maps_player_threat_and_missing_rod_do_not_wait(self):
        b,s,dk,own,orders,_=self.scene();b.creeping.map_alias='TM'
        self.assertFalse(s.tick(b,own,200));self.assertFalse(orders)
        b.creeping.map_alias='CH';b.battle_enemies=[unit('hfoo',9,100)]
        self.assertFalse(s.tick(b,own,200));self.assertFalse(orders)
        b.battle_enemies=[];b.g.inventory=lambda h:[]
        self.assertFalse(s.tick(b,own,201));self.assertTrue(s.done)

    def test_failed_summon_has_bounded_exit_without_fake_confirmation(self):
        b,s,dk,own,orders,events=self.scene();dk.x=0
        for now in (200,204,208,212):s.tick(b,own,now)
        self.assertTrue(s.done);self.assertEqual(events[-1]['reason'],'bounded_timeout')
        self.assertEqual(len([o for o in orders if o[0]=='rod']),3)


if __name__=='__main__':unittest.main()
