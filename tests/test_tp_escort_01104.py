import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_creep_portal_0199 as portal
import test_tavern_0145 as tavern
from test_micro_loot import unit,dist
from undead.policy import Action,attack_ready,choose_rule


class EscapedCreepTests(unittest.TestCase):
    def make(self):
        b,g,army,dk,foes,orders,events=portal.CreepPortalTests().make()
        frame=json.loads((Path(__file__).parent/'fixtures/tr-escaped-creep-01103.json').read_text(encoding='utf-8'))['frame']
        row=next(u for u in frame['own'] if u['type']=='Udea')
        dk.x=row['x'];dk.y=row['y'];dk.hp=row['hp'];dk.hp_max=row['hp_max'];dk.handle=tuple(row['handle'])
        foes.clear()
        for row in frame['enemies']:
            e=unit(row['type'],row['handle'][0],row['x'],row['hp'])
            e.handle=tuple(row['handle']);e.y=row['y'];e.owner=row['owner']
            e.target=tuple(row['target']) if row['target'] else None;foes.append(e)
        b.micro.damage.rates={dk.handle:40.5353651431469}
        b.portal_pulls={dk.handle:(1051,2619)}
        # An unavailable coarse route must not force TP after actual escape.
        g.path_distance=lambda *a:None
        return b,g,army,dk,foes,orders,events

    def test_recorded_escaped_dk_ignores_neutral_stale_target_and_damage_trend(self):
        b,g,army,dk,foes,orders,events=self.make()
        self.assertFalse(b.emergency_portal(army,424.155))
        self.assertFalse(orders)
        self.assertTrue(any(e['event']=='teleport_neutral_disengaged' for e in events))

    def test_neutral_attack_range_cannot_override_user_portal_ban(self):
        b,g,army,dk,foes,orders,events=self.make()
        foes[0].x=dk.x-80;foes[0].y=dk.y
        self.assertFalse(b.emergency_portal(army,424.155));self.assertFalse(orders)

    def test_player_pursuit_retains_wider_danger_guard(self):
        b,g,army,dk,foes,orders,events=self.make();foes[0].owner=1
        self.assertTrue(b.emergency_portal(army,424.155));self.assertEqual(orders,[dk.handle])


class TavernEscortTests(unittest.TestCase):
    def make(self):
        b,a,shops,m,buys,ev,res=tavern.TavernTests().setup_game()
        b.action=Action.CREEP;b.situation.tier=3;b.situation.lich=True;b.situation.orb=True
        b.g.attack_move=lambda u,x,y:m.append((u.handle,(x,y))) or True
        b.g.current_target=lambda u:None
        return b,a,shops,m,buys,ev,res

    def recall_once(self,b,a):
        for now in (10,):
            b.recruit_tavern(a,[],now,3,set())
            self.assertIsNotNone(b.tavern_mission)
            h=b.tavern_mission['courier']
            b.recruit_tavern(a,[],now+1,3,{h})
        self.assertIsNone(b.tavern_mission)

    def test_first_unsafe_recall_switches_to_group_march_and_actual_hero_unlocks_attack(self):
        b,a,shops,m,buys,ev,res=self.make();self.recall_once(b,a);m.clear()
        self.assertTrue(b.escort_tavern(a,[],100,3))
        self.assertEqual({h for h,p in m},{u.handle for u in a})
        self.assertTrue(all(p==(0,0) for h,p in m))
        for u in a:u.x=0
        self.assertTrue(b.escort_tavern(a,[],110,3));self.assertEqual(buys,['Nbrn'])
        self.assertFalse(attack_ready(b.situation))
        hero=unit('Nbrn',77,0);a.append(hero)
        b.recruit_tavern(a,[],111,3,set())
        self.assertFalse(b.escort_tavern(a,[],111,3))
        b.situation.third_hero=b.third_hero_ready([u for u in a if u.is_hero],(0,0))
        self.assertEqual(choose_rule(b.situation),Action.ATTACK)

    def test_ordinary_solo_recruitment_and_real_path_failures_do_not_redirect_army(self):
        b,a,shops,m,buys,ev,res=self.make();b.recruit_tavern(a,[],10,3,set())
        self.assertFalse(b.escort_tavern(a,[],11,3))
        self.assertEqual(len({h for h,p in m}),1)
        b.tavern_trips=3;b.tavern_unsafe_returns=0
        self.assertFalse(b.escort_tavern(a,[],100,3))

    def test_escort_fights_actual_local_threat_before_buying(self):
        b,a,shops,m,buys,ev,res=self.make();b.tavern_unsafe_returns=3
        for u in a:u.x=0
        e=unit('ntrg',90,150);e.owner=12;fought=[]
        b.fight=lambda units,foes,now:fought.extend(foes)
        self.assertTrue(b.escort_tavern(a,[e],100,3))
        self.assertEqual(fought,[e]);self.assertFalse(buys)

    def test_defense_retreat_wounds_and_hero_revival_override_escort(self):
        for mode in ('defense','retreat','health','revive'):
            b,a,shops,m,buys,ev,res=self.make();b.tavern_unsafe_returns=3
            if mode=='defense':b.action=Action.DEFEND
            if mode=='retreat':b.action=Action.RETREAT
            if mode=='health':b.situation.army_health=.4
            if mode=='revive':b.economy.ever_heroes.add('Nbrn')
            self.assertFalse(b.escort_tavern(a,[],100,3));self.assertFalse(m);self.assertFalse(buys)

    def test_group_hire_receipts_are_bounded_and_never_fake_hero(self):
        b,a,shops,m,buys,ev,res=self.make();b.tavern_unsafe_returns=3
        for u in a:u.x=0
        for now in (100,109,118):self.assertTrue(b.escort_tavern(a,[],now,3))
        self.assertFalse(b.escort_tavern(a,[],127,3))
        self.assertFalse(b.escort_tavern(a,[],160,3))
        self.assertEqual(buys,['Nbrn']*3);self.assertFalse(b.situation.third_hero)

    def test_stalled_escort_is_bounded_and_exposes_failure(self):
        b,a,shops,m,buys,ev,res=self.make();b.tavern_unsafe_returns=3
        self.assertTrue(b.escort_tavern(a,[],100,3))
        self.assertFalse(b.escort_tavern(a,[],131,3))
        self.assertTrue(b.escort_tavern(a,[],200,3))
        self.assertTrue(any(e.get('reason')=='no_progress_or_time_limit' for e in ev))
