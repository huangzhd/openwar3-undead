import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller,ground_attack_range
from undead.policy import Action,Situation

class CreepEscapeTests(unittest.TestCase):
    def scene(self):
        f=json.loads((Path(__file__).parent/'fixtures/tm-creep-escape-01115.json').read_text(encoding='utf-8'))
        frame=next(r for r in f['events'] if r['event']=='combat_state' and r['clock']==404.975)
        before=next(r for r in f['events'] if r['event']=='combat_state' and r['clock']==402.38)
        army=[];enemies=[]
        for r in frame['army']:
            u=unit(r['type'],r['handle'][0],r['x'],r['hp']);u.handle=tuple(r['handle']);u.y=r['y'];u.hp_max=r['hp_max'];u.owner=0;u.mana=r['mana'];army.append(u)
        for r in frame['enemies']:
            e=unit(r['type'],r['handle'][0],r['x'],r['hp']);e.handle=tuple(r['handle']);e.y=r['y'];e.owner=12;e.target=tuple(r['target']) if r['target'] else None;enemies.append(e)
        dk=next(u for u in army if u.type=='Udea');events=[];orders=[]
        g=N(dist=dist,path_distance=dist,walk_path=lambda a,b:[b],buffs=lambda u:[],enemies=lambda:[],
            current_target=lambda e:next((u for u in army if u.handle==e.target),None),
            inventory=lambda u:['stwp'] if u is dk else [],use_item=lambda u,*a,**kw:orders.append(u.handle) or True)
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)),first_attack_all_in=False)
        b.home=unit('unpl',999,-4672);b.home.y=-3840;b.action=Action.CREEP;b.situation=Situation(404.975)
        b.battle_enemies=enemies;b.micro.damage.rates[dk.handle]=45.40988247753041
        b.portal_pulls[dk.handle]=next(r['pull'] for r in frame['army'] if r['type']=='Udea')
        old=next(r for r in before['army'] if r['type']=='Udea')
        start=(old['x'],old['y']);clearance=min(dist(start,e)-ground_attack_range(e.type) for e in enemies)
        b.escape_started[dk.handle]=403.805
        b.escape_history[dk.handle]=[(403.805,*start,355.8638610839844,clearance,tuple(sorted(e.handle for e in enemies)))]
        return b,g,army,dk,enemies,orders,events

    def test_actual_tm_moving_uncontrolled_dk_does_not_spend_portal_after_one_second(self):
        b,g,army,dk,enemies,orders,events=self.scene()
        self.assertFalse(b.emergency_portal(army,404.975));self.assertFalse(orders)
        self.assertIn(dk.handle,b.portal_escaping)
        self.assertTrue(any(e['event']=='teleport_deferred_escape' and e['evidence']=='observed_motion' for e in events))

    def test_current_stun_or_unsurvivable_damage_cannot_override_neutral_tp_ban(self):
        for case in ('stun','damage'):
            b,g,army,dk,enemies,orders,events=self.scene()
            if case=='stun':g.buffs=lambda u:['BPSE'] if u is dk else []
            else:b.micro.damage.rates[dk.handle]=300
            self.assertFalse(b.escape_available(dk,enemies,404.975))
            self.assertFalse(b.emergency_portal(army,404.975));self.assertFalse(orders)

    def test_same_motion_does_not_relax_player_pursuit_guard(self):
        b,g,army,dk,enemies,orders,events=self.scene()
        for e in enemies:e.owner=1
        self.assertTrue(b.emergency_portal(army,404.975));self.assertEqual(orders,[dk.handle])

if __name__=='__main__':unittest.main()
