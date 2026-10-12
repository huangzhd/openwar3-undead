import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist,FakeLootGame
import test_combat_focus as focus
import test_opening_safety_0131 as tick_fixture
from undead.controller import Controller
from undead.creeping import Creeping
from undead.loot import Loot
from undead.policy import Action
from extract_map_pool import placements

class ContactTests(unittest.TestCase):
    def test_contact_immediately_cancels_camp_march_and_targets_enemy(self):
        b,f,d,s,h,e,own,foes,orders,targets,events=focus.CombatFocusTests().make()
        creep=unit('nogr',80,100,1);creep.owner=12;foes.append(creep)
        b.action=Action.CREEP;b.creeping.active=dict(id='camp')
        targets[f.handle]=creep;targets[d.handle]=creep
        b.player_contact=b.detect_player_contact(own,foes,(0,0))
        self.assertTrue(b.respond_player_contact(own,10))
        self.assertIsNone(b.creeping.active)
        self.assertTrue(any(o[0]=='hold' for o in orders))
        self.assertTrue(any(o[0]=='attack' for o in orders))
        self.assertTrue(all(o[2]!=creep.handle for o in orders if o[0]=='attack'))
        b.player_contact=[];self.assertFalse(b.respond_player_contact(own,11))

    def test_mixed_targets_cannot_choose_low_health_creep(self):
        b,f,d,s,h,e,own,foes,orders,targets,events=focus.CombatFocusTests().make()
        creep=unit('nogr',80,100,1);creep.owner=12
        b.creeping.drop_bindings[creep.handle]=True
        b.fight(own,[*foes,creep],10)
        self.assertTrue(orders)
        self.assertFalse(any(o[0]=='attack' and o[2]==creep.handle for o in orders))

    def test_archived_568_second_ambush_is_detected_beyond_old_600_radius(self):
        frame=json.loads((Path(__file__).parent/'fixtures/lr-ambush-0166.json').read_text())
        def convert(row,owner=0):
            data=dict(row);data['handle']=tuple(data['handle']);data.setdefault('owner',owner)
            data['alive']=True;data['is_hero']=data['type'][0].isupper()
            return N(**data)
        army=[convert(u) for u in frame['army']];foes=[convert(e) for e in frame['enemies']]
        by={u.handle:u for u in army+foes}
        g=N(dist=dist,me=lambda:0,current_target=lambda u:by.get(tuple(u.target)) if getattr(u,'target',None) else None)
        b=Controller(g,lambda *a,**k:None);contact=b.detect_player_contact(army,foes,frame['center'])
        self.assertTrue(contact);self.assertTrue(all(e.owner==1 for e in contact))
        self.assertTrue(any(dist(e,frame['center'])>600 for e in contact))

    def test_distant_scout_contact_does_not_drag_main_army(self):
        b,f,d,s,h,e,own,foes,orders,targets,events=focus.CombatFocusTests().make()
        scout=unit('uske',99,5000);own.append(scout);e.x=5100;targets[e.handle]=scout
        self.assertFalse(b.detect_player_contact(own,[e],(0,0)))

    def test_full_tick_interrupts_creeping_before_macro_interval(self):
        g,b,dk,allies,orders,clock=tick_fixture.EmergencyTests().controller()
        dk.hp=dk.hp_max;dk.mana=0;g.abilities=lambda u:[]
        for u in allies:u.hp=u.hp_max
        g.enemies()[0].hp=300;g.hold=lambda u:orders.append(('hold',u.handle)) or True
        b.micro.plan=lambda *a,**kw:{};b.shields.plan=lambda *a:{}
        b.emergency_portal=lambda *a:False;b.combat_spells=lambda *a:None;b.frost_armor=lambda *a:None
        b.recruit_tavern=lambda *a:set();b.stop_hero_chases=lambda *a:None
        b.fight=lambda army,foes,now:orders.append(('fight',[e.type for e in foes]))
        b.creep=lambda *a:orders.append(('creep',));b.support_dk=lambda *a:orders.append(('support',)) or True
        b.last_decide=clock[0]-.1;b.action=Action.CREEP
        b.tick()
        self.assertIn(('fight',['hfoo']),orders);self.assertNotIn(('creep',),orders);self.assertNotIn(('support',),orders)

class DropTests(unittest.TestCase):
    def test_jass_death_trigger_identifies_only_carrier(self):
        script="""function Test_DropItems takes nothing returns nothing
        call RandomDistAddItem('rat6',100)
        call UnitDropItem(u, itemID)
        endfunction
        function CreateNeutralHostile takes nothing returns nothing
        set u=CreateUnit(p, 'nogr', 0, 0, 0)
        call TriggerRegisterUnitEvent(t, u, EVENT_UNIT_DEATH)
        call TriggerAddAction(t, function Test_DropItems)
        set u=CreateUnit(p, 'nftt', 100, 0, 0)
        endfunction"""
        rows=placements(script,'CreateNeutralHostile')
        self.assertTrue(rows[0]['drops_items']);self.assertNotIn('drops_items',rows[1])

    def test_bound_visible_carrier_keeps_priority_after_moving(self):
        b,f,d,s,h,e,own,foes,orders,targets,events=focus.CombatFocusTests().make()
        carrier=unit('nogr',80,100,1000);other=unit('nftt',81,120,10)
        carrier.owner=other.owner=12
        b.creeping.catalog=[dict(spawns=[dict(code='nogr',x=100,y=0,drops_items=True),dict(code='nftt',x=120,y=0)])]
        b.creeping.observe_drop_carriers(b.g,[carrier,other]);carrier.x=200
        b.fight(own,[carrier,other],10)
        self.assertIs(targets[f.handle],carrier);self.assertIs(targets[d.handle],carrier)

    def test_ambiguous_same_type_does_not_guess_treasure_holder(self):
        c=Creeping(lambda *a,**k:None,[dict(spawns=[dict(code='nogr',x=-50,y=0,drops_items=True),dict(code='nogr',x=50,y=0)])])
        u=unit('nogr',1,0);c.observe_drop_carriers(N(dist=dist),[u]);self.assertFalse(c.carries_drop(u))

    def test_pickup_visible_drop_before_remaining_creep_dies(self):
        g=FakeLootGame();g.hero.hp=g.hero.hp_max
        creep=unit('nftt',90,300);creep.owner=12
        loot=Loot({},lambda *a,**k:None)
        self.assertIsNotNone(loot.tick(g,[g.hero],[creep],1,camp_combat=True));self.assertTrue(g.pickups)
        g.ground=[];g.inv[0]='ratf';g.hero.item_addrs=[99]
        loot.tick(g,[g.hero],[creep],2,camp_combat=True)
        self.assertTrue(loot.done);self.assertGreater(creep.hp,0)

    def test_enemy_or_wounded_hero_prevents_mid_camp_loot(self):
        for enemy in (False,True):
            g=FakeLootGame();g.hero.hp=g.hero.hp_max if enemy else g.hero.hp_max*.4
            foe=unit('hfoo' if enemy else 'nftt',90,300);foe.owner=1 if enemy else 12
            self.assertIsNone(Loot({},lambda *a,**k:None).tick(g,[g.hero],[foe],1,camp_combat=True))
            self.assertFalse(g.pickups)

if __name__=='__main__':unittest.main()
