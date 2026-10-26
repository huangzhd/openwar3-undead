"""Training formation, rear dispel safety and shared ranged fire behavior."""
import unittest
from math import hypot
from types import SimpleNamespace as N
from unittest.mock import Mock

from training import TrainingController
from test_baseline import unit


def distance(a,b):
    a = (a.x,a.y) if hasattr(a,'x') else a
    b = (b.x,b.y) if hasattr(b,'x') else b
    return hypot(a[0]-b[0],a[1]-b[1])


class TrainingOrcFocusTests(unittest.TestCase):
    def scene(self):
        own = [unit('ucry',i,owner=0) for i in range(1,7)]
        own += [unit('Ulic',7,owner=0),unit('Nbrn',8,owner=0),
                unit('ubsp',9,owner=0,x=-260),unit('uobs',10,owner=0,x=-240)]
        foes = [unit('otbk',20,x=400),unit('otbk',21,x=450),unit('Otch',22,x=400)]
        for u in own+foes:
            u.hp=u.hp_max=600;u.mana=300;u.has_detail=True
        foes[0].hp=110;foes[1].hp=180;foes[2].hp=1000
        orders=[];events=[];targets={};effects={}
        def attack(u,t,**kw):
            orders.append(('attack',u.handle,t.handle));targets[u.handle]=t;return True
        g=N(dist=distance,my_units=lambda:own,my_heroes=lambda:[u for u in own if u.is_hero],
            enemies=lambda:foes,units=lambda owner,kinds:[u for u in own if u.type in kinds],
            unit=lambda handle:next((u for u in own+foes if u.handle==handle),None),
            map=lambda:N(walkable=lambda *p:True),path_distance=distance,
            buffs=lambda u:effects.get(u.handle,[]),abilities=lambda u:[],me=lambda:0,
            cooldown=lambda u,a:0,inventory=lambda u:[],clock=lambda:10,
            current_target=lambda u:targets.get(u.handle),attack=attack,
            move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True,
            hold=lambda u,queue=None:orders.append(('hold_after' if queue else 'hold',u.handle)) or True,
            attack_move=lambda u,x,y:orders.append(('attack_move',u.handle,(x,y))) or True,
            cast=lambda u,spell,**kw:orders.append(('cast',u.handle,spell,kw)) or True,
            observe_coil=lambda *a:None)
        b=TrainingController(None,lambda e,**kw:events.append((e,kw)),2);b.g=g
        b.hero_pressure.prefer_key_heroes=False # Preserve the legacy adaptive-plan regression suite.
        return b,g,own,foes,orders,events,effects

    def test_six_fiends_spread_and_destroyer_starts_behind_all_ground_roles(self):
        b,g,own,foes,orders,events,effects=self.scene()
        b.prepare(1)
        points=[b.prep_points[u.handle] for u in own if u.type=='ucry']
        self.assertEqual(len(points),6)
        self.assertGreaterEqual(min(distance(a,c) for i,a in enumerate(points) for c in points[i+1:]),159)
        destroyer=next(u for u in own if u.type=='ubsp')
        self.assertLess(b.prep_points[destroyer.handle][0],min(p[0] for h,p in b.prep_points.items() if h!=destroyer.handle))
        count=len(orders);b.prepare(2)
        self.assertEqual(len(orders),count)  # No repeated countdown move spam.

    def test_full_health_destroyer_retreats_from_headhunter_fire(self):
        b,g,own,foes,orders,events,effects=self.scene();d=own[8];d.x=100
        g.current_target=lambda u:d if u.type=='otbk' else None
        pulls={};blocked=b.rear_destroyers(own,foes,10,pulls,None)
        self.assertIn(d.handle,blocked)
        goal=pulls[d.handle]
        self.assertLess(goal[0],0)
        self.assertTrue(all(distance(goal,e)>=590 for e in foes if e.type=='otbk'))
        self.assertFalse(orders)

    def test_rear_destroyer_dispels_in_range_and_preserves_cast_windup(self):
        b,g,own,foes,orders,events,effects=self.scene()
        d=own[8];foes[2].x=300;effects[foes[2].handle]=['Broa']
        pulls={};blocked=b.rear_destroyers(own,foes,10,pulls,None)
        self.assertNotIn(d.handle,blocked)
        b.destroyer.tick(b,own,foes,10,blocked)
        self.assertTrue(any(o[:3]==('cast',d.handle,'devourmagic') for o in orders))
        orders.clear();b.rear_destroyers(own,foes,10.5,{},None)
        self.assertFalse(orders)

    def test_rear_destroyer_does_not_move_into_aa_to_get_dispel_range(self):
        b,g,own,foes,orders,events,effects=self.scene()
        for e in foes:e.x=1000
        effects[foes[2].handle]=['Broa']
        pulls={};blocked=b.rear_destroyers(own,foes,10,pulls,None)
        b.destroyer.tick(b,own,foes,10,blocked)
        self.assertFalse(any(o[0] in {'cast','move','attack','attack_move'} for o in orders))

    def test_fiends_lich_and_dark_share_target_and_keep_it_until_dead(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes[2].type='Hpal' # Preserve generic targeting coverage outside Orc priorities.
        group={u.handle for u in own if u.type in {'ucry','Ulic','Nbrn'}}
        self.assertEqual(b.focus_ranged(own,foes,10),group)
        self.assertEqual({o[1] for o in orders},group)
        self.assertEqual({o[2] for o in orders},{foes[0].handle})
        foes[1].hp=1;orders.clear();b.focus_ranged(own,foes,12)
        self.assertEqual(b.ranged_focus,foes[0].handle);self.assertFalse(orders)
        foes[0].hp=0;b.focus_ranged(own,foes,14)
        self.assertEqual({o[2] for o in orders},{foes[1].handle})

    def test_group_switches_to_killable_hero_but_not_invulnerable_hero(self):
        for immune in (False,True):
            b,g,own,foes,orders,events,effects=self.scene()
            foes[2].type='Hpal' # Preserve generic targeting coverage outside Orc priorities.
            b.focus_ranged(own,foes,10);orders.clear();foes[2].hp=15
            if immune:effects[foes[2].handle]=['Bvul']
            b.focus_ranged(own,foes,12)
            self.assertEqual(b.ranged_focus,foes[0 if immune else 2].handle)
            if not immune:self.assertEqual(len(orders),8)

    def test_active_spell_finisher_turns_the_entire_ranged_group_onto_hero(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes[2].type='Hpal' # Preserve generic targeting coverage outside Orc priorities.
        b.focus_ranged(own,foes,10);orders.clear()
        b.nc_combo.pending=dict(target=foes[2].handle,clock=11)
        b.focus_ranged(own,foes,12)
        self.assertEqual(len(orders),8)
        self.assertEqual({o[2] for o in orders},{foes[2].handle})

    def test_disappeared_target_is_replaced_and_busy_caster_is_not_interrupted(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes[2].type='Hpal' # Preserve generic targeting coverage outside Orc priorities.
        b.focus_ranged(own,foes,10);foes.pop(0);orders.clear()
        lich=own[6];b.cast_until[lich.handle]=20
        b.focus_ranged(own,foes,12)
        self.assertEqual(b.ranged_focus,foes[0].handle)
        self.assertNotIn(lich.handle,{o[1] for o in orders})
        self.assertEqual({o[2] for o in orders},{foes[0].handle})

    def test_outlying_fiend_regroups_without_attacking_a_different_target(self):
        b,g,own,foes,orders,events,effects=self.scene();own[0].x=-1100
        foes[2].type='Hpal' # Preserve generic targeting coverage outside Orc priorities.
        b.focus_ranged(own,foes,10)
        self.assertEqual([o[0] for o in orders if o[1]==own[0].handle],['move'])
        self.assertEqual({o[2] for o in orders if o[0]=='attack'},{foes[0].handle})

    def test_unreachable_regroup_does_not_send_fiend_on_a_long_detour(self):
        b,g,own,foes,orders,events,effects=self.scene();own[0].x=-1100
        g.path_distance=lambda a,c:5000
        b.focus_ranged(own,foes,10)
        self.assertEqual([o[0] for o in orders if o[1]==own[0].handle],['hold'])

    def test_tick_reserves_dispeller_and_group_from_generic_attack_and_advance(self):
        b,g,own,foes,orders,events,effects=self.scene()
        for u in own:u.mana=0
        b.skills=Mock();b.observe_rod_corpses=Mock();b.observe_rod_skeletons=Mock()
        b.rescue_coil_ready=Mock(return_value=False)
        b.micro.plan=Mock(return_value={});b.shields.plan=Mock(return_value={})
        b.combat_spells=Mock()
        b.consumables.tick=Mock();b.frost_armor=Mock();b.statue_support.tick=Mock()
        b.focus_siege=Mock(return_value=False);b.stop_hero_chases=Mock()
        b.skeleton_opening=Mock(return_value=False);b.battle_formation.step=Mock(return_value=set())
        b.tick()
        b.combat_spells.assert_called_once()
        self.assertTrue(b.micro.plan.call_args.kwargs['aggressive_battle'])
        self.assertFalse(any(o[0] in {'attack','attack_move'} and o[1]==own[8].handle for o in orders))
        self.assertEqual(len([o for o in orders if o[0]=='attack']),8)

    def test_survivor_search_destroyer_follows_ground_force_instead_of_leading(self):
        b,g,own,foes,orders,events,effects=self.scene()
        foes.clear();own[8].x=800
        pulls={};b.rear_destroyers(own,foes,10,pulls,(1500,0))
        self.assertLess(pulls[own[8].handle][0],0)


if __name__=='__main__':unittest.main()
