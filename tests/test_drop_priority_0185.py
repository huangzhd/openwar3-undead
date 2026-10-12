import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_combat_focus as focus
from undead.controller import Controller
from undead.policy import Action

class DropPriorityTests(unittest.TestCase):
    def make(self):
        b,f,d,*rest=focus.CombatFocusTests().make()
        own=rest[3];orders=rest[5];targets=rest[6]
        carrier=unit('nftb',80,735,450);other=unit('nftt',81,590,50)
        carrier.owner=other.owner=12
        b.creeping.catalog=[dict(spawns=[dict(code='nftb',x=735,y=0,drops_items=True),dict(code='nftt',x=590,y=0)])]
        b.creeping.observe_drop_carriers(b.g,[carrier,other])
        b.g.creeps=lambda:[carrier,other]
        return b,own,carrier,other,orders,targets

    def test_visible_carrier_outside_center_filter_beats_near_low_hp_creep(self):
        b,own,c,o,orders,targets=self.make()
        b.fight(own,[o],10)
        self.assertTrue(all(targets.get(u.handle) is c for u in own))

    def test_fog_or_distant_carrier_does_not_create_chase(self):
        for hidden in (False,True):
            b,own,c,o,orders,targets=self.make()
            if hidden:b.g.creeps=lambda:[o]
            else:c.x=1600
            b.fight(own,[o],10)
            self.assertTrue(all(targets.get(u.handle) is o for u in own))

    def test_other_camp_carrier_does_not_steal_current_fight(self):
        b,own,c,o,orders,targets=self.make()
        b.creeping.drop_camps[c.handle]=99
        b.fight(own,[o],10)
        self.assertTrue(all(targets.get(u.handle) is o for u in own))

    def test_unengaged_visible_camp_does_not_stop_attack_march(self):
        b,own,c,o,orders,targets=self.make()
        b.action=Action.ATTACK;b.go_raw=lambda *a,**k:None
        b.g.path_distance=dist;b.g.walk_path=lambda a,z:[z]
        b.go(own,(2000,0),10,attack=True)
        self.assertFalse(any(row[0]=='attack' for row in orders))

    def test_player_contact_overrides_carrier_and_cast_is_protected(self):
        b,own,c,o,orders,targets=self.make()
        enemy=unit('hfoo',90,50,400);enemy.owner=1
        b.cast_until[own[1].handle]=20
        b.fight(own,[o,enemy],10)
        self.assertIs(targets[own[0].handle],enemy)
        self.assertNotIn(own[1].handle,targets)

    def test_actual_619_second_roadside_encounter_focuses_carrier(self):
        frame=json.loads((Path(__file__).parent/'fixtures/az-drop-priority-0184.json').read_text())
        def convert(row,owner):
            data=dict(row);data['handle']=tuple(data['handle']);data['owner']=owner
            data.update(alive=True,is_hero=data['type'][0].isupper(),level=1)
            data.setdefault('hp_max',data['hp']);data.setdefault('mana',0)
            return N(**data)
        own=[convert(u,0) for u in frame['army'] if not u['pulling']]
        creeps=[convert(e,12) for e in frame['enemies']]
        by={u.handle:u for u in own+creeps};targets={};orders=[]
        def attack(u,e,**kw):targets[u.handle]=e;orders.append((u.handle,e.handle));return True
        g=N(me=lambda:0,dist=dist,path_distance=dist,walk_path=lambda a,b:[b],
            creeps=lambda:creeps,enemies=lambda:[],unit=lambda h:by.get(h),
            current_target=lambda u:targets.get(u.handle) or by.get(tuple(getattr(u,'target',[]) or [])),
            attack=attack,hold=lambda u:True,units=lambda owner,codes:[u for u in own if u.type in codes],cooldown=lambda *a:1)
        b=Controller(g,lambda *a,**k:None);b.action=Action.ATTACK;b.attack_committed=True
        b.focus_siege=lambda *a:False;b.go_raw=lambda *a,**k:None
        b.creeping.catalog=[dict(spawns=[dict(code=e.type,x=e.x,y=e.y,drops_items=e.type=='nftb') for e in creeps])]
        b.creeping.observe_drop_carriers(g,creeps)
        b.go(own,(-3392,-3456),frame['clock'],attack=True)
        carrier=next(e for e in creeps if e.type=='nftb')
        self.assertTrue(orders)
        self.assertTrue(all(target is carrier for target in targets.values()))
        self.assertGreater(dist(carrier,frame['center']),650)

if __name__=='__main__':unittest.main()
