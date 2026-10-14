import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller,ground_attack_range
from undead.policy import Action,Situation


class CreepPortalTests(unittest.TestCase):
    def make(self):
        data=json.loads((Path(__file__).parent/'fixtures/tr-creep-portal-0198.json').read_text(encoding='utf-8'))
        frame=data['combat'];army=[];foes=[]
        for row in frame['army']:
            u=unit(row['type'],row['handle'][0],row['x'],row['hp'])
            u.handle=tuple(row['handle']);u.y=row['y'];u.hp_max=row['hp_max'];u.owner=0
            army.append(u)
        for row in frame['enemies']:
            e=unit(row['type'],row['handle'][0],row['x'],row['hp'])
            e.handle=tuple(row['handle']);e.y=row['y'];e.owner=data['owners'][str(row['handle'])]
            e.target=tuple(row['target']) if row['target'] else None;foes.append(e)
        dk=next(u for u in army if u.type=='Udea');orders=[];events=[]
        g=N(dist=dist,path_distance=dist,buffs=lambda u:[],enemies=lambda:[],
            current_target=lambda e:next((u for u in army if u.handle==e.target),None),
            inventory=lambda u:['stwp'] if u is dk else [],
            use_item=lambda u,*a,**kw:orders.append(u.handle) or True)
        b=Controller(g,lambda ev,**kw:events.append(dict(event=ev,**kw)),first_attack_all_in=False)
        b.home=unit('unpl',999,-5000);b.action=Action.CREEP;b.situation=Situation(390.13)
        b.battle_enemies=foes;b.micro.damage.rates[dk.handle]=45.390625
        b.portal_pulls[dk.handle]=next(r['pull'] for r in frame['army'] if r['type']=='Udea')
        clearance=min(dist(dk,e)-ground_attack_range(e.type) for e in foes)
        sig=tuple(sorted(e.handle for e in foes))
        # The real caster had not moved before pulling began. That is attack
        # history, not evidence that the new escape order has already failed.
        b.escape_history[dk.handle]=[(388.13,dk.x,dk.y,415,clearance,sig)]
        return b,g,army,dk,foes,orders,events

    def test_real_stationary_pre_pull_frame_tries_walking_without_spending_tp(self):
        b,g,army,dk,foes,orders,events=self.make()
        self.assertFalse(b.emergency_portal(army,390.13))
        self.assertFalse(orders);self.assertIn(dk.handle,b.portal_escaping)
        self.assertEqual(events[-1]['evidence'],'bounded_initial_retreat')

    def test_stalled_neutral_trial_does_not_override_user_portal_ban(self):
        b,g,army,dk,foes,orders,events=self.make()
        b.emergency_portal(army,390.13)
        self.assertFalse(b.escape_available(dk,foes,391.23))
        self.assertFalse(b.emergency_portal(army,391.23))
        self.assertFalse(orders);self.assertIsNone(b.teleport)

    def test_real_motion_and_opening_gap_continue_escape(self):
        b,g,army,dk,foes,orders,events=self.make()
        b.emergency_portal(army,390.13);dk.y-=200;dk.hp-=20
        self.assertFalse(b.emergency_portal(army,390.93))
        self.assertFalse(orders);self.assertIn(dk.handle,b.portal_escaping)
        dk.y-=350
        self.assertFalse(b.emergency_portal(army,392.23));self.assertFalse(orders)

    def test_root_or_player_pursuit_does_not_gain_stationary_grace(self):
        for reason in ('root','player'):
            b,g,army,dk,foes,orders,events=self.make()
            if reason=='root':g.buffs=lambda u:['BEer'] if u is dk else []
            else:foes[0].owner=1
            self.assertEqual(b.emergency_portal(army,390.13),reason=='player')
            self.assertEqual(bool(orders),reason=='player')

    def test_damage_budget_prevents_trial_that_cannot_survive(self):
        b,g,army,dk,foes,orders,events=self.make();b.micro.damage.rates[dk.handle]=200
        self.assertFalse(b.escape_available(dk,foes,390.13))
        self.assertFalse(b.emergency_portal(army,390.13));self.assertFalse(orders)

    def test_missing_or_unsafe_route_does_not_delay_rescue(self):
        for reason in ('missing','unsafe'):
            b,g,army,dk,foes,orders,events=self.make()
            if reason=='missing':g.path_distance=lambda *a:None
            else:b.portal_pulls[dk.handle]=(dk.x,dk.y+30)
            self.assertFalse(b.escape_available(dk,foes,390.13))
            self.assertFalse(b.emergency_portal(army,390.13),reason);self.assertFalse(orders)

    def test_old_sample_expiry_cannot_restart_stalled_trial(self):
        b,g,army,dk,foes,orders,events=self.make()
        b.emergency_portal(army,390.13)
        self.assertFalse(b.escape_available(dk,foes,394.13))
        self.assertFalse(b.emergency_portal(army,394.13));self.assertFalse(orders)

if __name__=='__main__':unittest.main()
