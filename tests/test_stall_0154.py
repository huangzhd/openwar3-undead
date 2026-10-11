import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.policy import Action,Situation,choose_rule
from undead.targeting import can_engage,in_weapon_range
from undead.siege import SiegeFocus
from undead.combat_progress import CombatProgress


class StallTests(unittest.TestCase):
    def bot(self):
        orders=[];events=[]
        g=N(dist=dist,me=lambda:0,path_distance=dist,walk_path=lambda a,b:[b],
            move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True,
            attack_move=lambda u,x,y:orders.append(('attack_move',u.handle,(x,y))) or True,
            hold=lambda u:orders.append(('hold',u.handle,None)) or True,
            current_target=lambda u:None)
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)))
        b.action=Action.ATTACK;b.attack_committed=True
        b.situation=Situation(100,tier=3,lich=True,orb=True,third_hero=True)
        return b,orders,events

    def fixture(self):
        data=json.loads((Path(__file__).parent/'fixtures/burrow-stall-234536.json').read_text(encoding='utf-8'))
        def convert(row,owner):
            row=dict(row);row['handle']=tuple(row['handle']);row['owner']=owner
            row['is_hero']=row['type'][0].isupper()
            return N(**row)
        return data,[convert(u,0) for u in data['frame']['army']],[convert(e,1) for e in data['frame']['enemies']]

    def test_archived_burrow_frame_resumes_route_instead_of_combat_dispatch(self):
        data,army,foes=self.fixture();b,orders,_=self.bot();b.battle_enemies=foes
        fought=[];b.fight=lambda *args:fought.append(args)
        b.go(army,tuple(data['goal']),data['frame']['clock'],attack=True)
        self.assertFalse(fought)
        self.assertTrue(any(o[0]=='attack_move' for o in orders))
        self.assertTrue(all(o[0]!='hold' for o in orders))

    def test_burrow_is_not_combat_target_and_surfacing_restores_same_handle(self):
        b,_,events=self.bot();f=unit('ucrm',9,300);f.owner=1
        self.assertEqual(b.active_foes([f],1),[])
        self.assertFalse(in_weapon_range(b.g,unit('ucry',1,0),f))
        b.active_foes([f],2);self.assertEqual(len(events),1)
        f.type='ucry'
        self.assertEqual(b.active_foes([f],3),[f]);self.assertTrue(can_engage(f))
        self.assertTrue(in_weapon_range(b.g,unit('ucry',1,0),f))

    def test_fight_does_not_attack_or_cast_on_burrow(self):
        b,orders,_=self.bot();f=unit('ucrm',9,300)
        b.fight([unit('Udea',1,0),unit('ucry',2,10)],[f],10)
        self.assertFalse(orders)

    def test_mixed_live_threat_still_interrupts_route(self):
        b,_,_=self.bot();f=unit('ucry',8,300);hidden=unit('ucrm',9,250)
        b.battle_enemies=[hidden,f];fought=[];b.fight=lambda a,e,n:fought.extend(e)
        b.go([unit('ucry',1,0),unit('ucry',2,10)],(2000,0),1,True)
        self.assertEqual(fought,[f])

    def test_burrow_does_not_block_building_siege(self):
        b,_,_=self.bot();f=unit('ucrm',9,150);tower=unit('uzg1',10,200)
        f.owner=tower.owner=1
        self.assertIs(SiegeFocus(lambda *a,**kw:None).choose(b.g,[unit('ucry',1,0)],[f,tower],1),tower)

    def test_third_hero_separation_after_departure_does_not_flip_to_creeping(self):
        b,_,_=self.bot();h=unit('Nbrn',1,1800)
        b.attack_committed=False;self.assertFalse(b.third_hero_ready([h],(0,0)))
        h.x=500;self.assertTrue(b.third_hero_ready([h],(0,0)))
        b.attack_committed=True
        for x in (1190,1210,1800,1150,2400):
            h.x=x;b.situation.third_hero=b.third_hero_ready([h],(0,0))
            self.assertEqual(choose_rule(b.situation),Action.ATTACK)

    def test_dead_missing_or_unjoined_third_hero_still_blocks_readiness(self):
        b,_,_=self.bot();h=unit('Nbrn',1,100)
        self.assertFalse(b.third_hero_ready([],(0,0)))
        h.hp=0;self.assertFalse(b.third_hero_ready([h],(0,0)))
        h.hp=500;b.tavern_joiners.add(h.handle)
        self.assertFalse(b.third_hero_ready([h],(0,0)))


class ProgressTests(unittest.TestCase):
    def setup(self):
        events=[];p=CombatProgress(lambda e,**kw:events.append(dict(event=e,**kw)))
        own=[unit('ucry',1,0),unit('ucry',2,20)];foe=unit('hfoo',3,300)
        return p,own,foe,events

    def stalled(self):
        p,a,f,ev=self.setup()
        for t in range(9):p.observe(a,[f],t,True)
        return p,a,f,ev

    def test_no_effect_for_eight_seconds_defers_but_not_permanently(self):
        p,a,f,ev=self.stalled();self.assertFalse(p.allowed(f,8))
        self.assertEqual(ev[0]['reason'],'no_motion_or_observed_damage')
        p.observe(a,[f],18,True);self.assertTrue(p.allowed(f,18))

    def test_outgoing_damage_incoming_damage_and_motion_each_prevent_bypass(self):
        for mode in ('outgoing','incoming','motion'):
            p,a,f,_=self.setup()
            for t in range(20):
                if mode=='outgoing':f.hp-=5
                elif mode=='incoming':a[0].hp-=5
                else:
                    for u in a:u.x+=30
                p.observe(a,[f],t,True)
            self.assertFalse(p.deferred,mode)

    def test_damage_new_threat_and_surface_each_release_deferral(self):
        for mode in ('damage','new_threat','surface'):
            p,a,f,_=self.stalled();foes=[f]
            if mode=='damage':a[0].hp-=10
            elif mode=='new_threat':foes.append(unit('hfoo',4,350))
            else:f.type='hrif'
            p.observe(a,foes,9,True);self.assertTrue(p.allowed(f,9),mode)

    def test_missing_samples_defense_and_structures_do_not_trigger_bypass(self):
        for mode in ('gap','defense','building'):
            p,a,f,_=self.setup()
            if mode=='building':f.type='uzg1'
            for t in range(0,40,5) if mode=='gap' else range(20):
                p.observe(a,[f],t,mode!='defense')
            self.assertFalse(p.deferred,mode)

    def test_deferred_target_cannot_reacquire_via_fight_or_attack_move(self):
        b,orders,_=StallTests().bot();p,a,f,_=self.stalled()
        b.combat_progress=p;b.battle_enemies=[f]
        b.go(a,(2000,0),9,attack=True);b.fight(a,[f],9)
        self.assertTrue(orders);self.assertTrue(all(o[0]=='move' for o in orders))
