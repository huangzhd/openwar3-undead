import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
import test_battle_shop_0163 as shopping
import test_opening_safety_0131 as ticks
from undead.controller import Controller
from undead.policy import Action


class OrbContactTests(unittest.TestCase):
    def scene(self):
        g,old,shop,events=shopping.ShoppingTests().make()
        b=Controller(g,lambda ev,**kw:events.append(dict(event=ev,**kw)))
        b.home=g.home;b.action=Action.CREEP;b.situation=N(threatened=False)
        b.battle_shop=shop;b.economy=old.economy
        b.creep_aggro.step=lambda *a:None
        b.creeping.safe_route=lambda *a:True
        b.collective_retreat=lambda army,now:g.orders.append(('retreat',))
        g.dk.x=-1800;g.lich.x=0;g.dark.x=-40;g.home.x=-4000
        g.map=lambda:N(walkable=lambda *p:True)
        g.walk_path=lambda a,z:[a,z]
        g.move=lambda u,x,y:g.orders.append(('move',u.type,(x,y))) or True
        g.hold=lambda u:g.orders.append(('hold',u.type)) or True
        g.bags[g.dk.handle]=['ocor',None,None,None,None,None]
        enemy=unit('hfoo',99,450,600);enemy.owner=1
        b.player_contact=[enemy]
        shop.orb=dict(hero=g.dk.handle,shop=g.home.handle,started=500,progress_at=500,best=None,target=None)
        return g,b,shop,events,enemy

    def test_withdraw_then_deliver_then_resume_only_after_lich_bag_changes(self):
        g,b,s,events,e=self.scene()
        self.assertTrue(b.wait_for_orb(g.heroes,[e],537,3))
        rear=next(o[2] for o in g.orders if o[:2]==('move','Ulic'))
        self.assertGreater(dist(rear,e),dist(g.lich,e))
        self.assertIn(('move','Udea',rear),g.orders)
        self.assertIsNotNone(s.orb)
        g.lich.x,g.lich.y=rear;g.dk.x,g.dk.y=rear
        g.orders.clear();b.wait_for_orb(g.heroes,[e],540,3)
        self.assertIn('ocor',g.inventory(g.lich))
        self.assertIsNotNone(b.orb_rendezvous) # give receipt is not the observed next frame
        s.observe(g,542)
        self.assertFalse(b.wait_for_orb(g.heroes,[e],543,3))
        self.assertIsNone(b.orb_rendezvous);self.assertIsNone(s.orb)
        self.assertEqual(events[-1]['reason'],'delivered')

    def test_false_give_receipts_are_bounded_and_never_release_into_combat(self):
        g,b,s,events,e=self.scene();g.dk.x=g.lich.x=-1500
        g.give_item=lambda *a:g.orders.append(('fake-give',)) or True
        for now in (537,541,545,549):
            s.observe(g,now);b.wait_for_orb(g.heroes,[e],now,3)
        self.assertEqual(g.orders.count(('fake-give',)),3)
        self.assertIn(('retreat',),g.orders)
        self.assertNotIn('ocor',g.inventory(g.lich))
        self.assertFalse(any(ev.get('reason')=='lich_inventory_confirmed' for ev in events))

    def test_unreachable_receiver_does_not_send_dk_through_enemy_or_resume_attack(self):
        g,b,s,events,e=self.scene();g.path_distance=lambda a,z:None
        self.assertTrue(b.wait_for_orb(g.heroes,[e],537,3))
        self.assertFalse(any(o[:2]==('move','Udea') for o in g.orders))
        self.assertTrue(b.wait_for_orb(g.heroes,[e],628,3))
        self.assertIn(('retreat',),g.orders)
        self.assertIsNone(s.orb)

    def test_route_bending_into_enemy_is_rejected_even_with_safe_endpoint(self):
        g,b,s,events,e=self.scene();g.lich.x=-1500
        g.walk_path=lambda a,z:[a,(e.x,e.y),z]
        self.assertTrue(b.wait_for_orb(g.heroes,[e],537,3))
        self.assertFalse(any(o[:2]==('move','Udea') for o in g.orders))
        self.assertNotIn('ocor',g.inventory(g.lich))

    def test_ongoing_purchase_continues_while_main_withdraws_and_dk_danger_takes_priority(self):
        g,b,s,events,e=self.scene();g.bags[g.dk.handle]=[None]*6;g.dk.x=g.home.x
        b.wait_for_orb(g.heroes,[e],537,3)
        self.assertIn('ocor',g.inventory(g.dk))
        self.assertTrue(any(o[:2]==('move','Ulic') for o in g.orders))
        g.orders.clear();e.x=g.dk.x+100
        b.wait_for_orb(g.heroes,[e],541,3)
        moves=[o[2] for o in g.orders if o[:2]==('move','Udea')]
        self.assertTrue(moves);self.assertGreater(dist(moves[-1],e),dist(g.dk,e))
        self.assertFalse(any(o[0]=='give' for o in g.orders))

    def test_safe_return_continues_after_contact_disappears_and_casts_are_preserved(self):
        g,b,s,events,e=self.scene();b.wait_for_orb(g.heroes,[e],537,3)
        b.player_contact=[];g.orders.clear();b.cast_until[g.lich.handle]=550
        self.assertTrue(b.wait_for_orb(g.heroes,[],540,3))
        self.assertFalse(any(o[:2]==('move','Ulic') for o in g.orders))
        self.assertTrue(any(o[:2]==('move','Udea') for o in g.orders))

    def test_base_defense_finished_attack_missing_hero_and_unknown_bags(self):
        for reason in ('defense','committed','hero','bag'):
            g,b,s,events,e=self.scene()
            if reason=='defense':b.action=Action.DEFEND
            if reason=='committed':b.attack_committed=True
            if reason=='hero':g.heroes.remove(g.lich)
            if reason=='bag':g.bags[g.lich.handle]=None
            handled=b.wait_for_orb(g.heroes,[e],537,3)
            self.assertEqual(handled,reason=='bag')
            self.assertFalse(any(o[0]=='give' for o in g.orders))

    def test_real_contact_positions_withdraw_frontline_towards_rear_lich(self):
        g,b,s,events,e=self.scene()
        frame=json.loads((Path(__file__).parent/'fixtures/ch-orb-contact-01136.json').read_text(encoding='utf-8'))['frame']
        def convert(row,owner):
            u=unit(row['type'],row['handle'][0],row['x'],row['hp'])
            u.handle=tuple(row['handle']);u.y=row['y'];u.owner=owner
            return u
        army=[convert(r,0) for r in frame['army']];foes=[convert(r,1) for r in frame['enemies']]
        g.heroes=[u for u in army if u.is_hero];g.dk=next(u for u in g.heroes if u.type=='Udea');g.lich=next(u for u in g.heroes if u.type=='Ulic')
        g.bags={h.handle:[None]*6 for h in g.heroes};g.bags[g.dk.handle][0]='ocor'
        b.player_contact=foes;g.home.x=2176;g.home.y=4224
        before=min(dist(u,e) for u in army if u.type=='ucry' for e in foes)
        self.assertTrue(b.wait_for_orb(army,foes,537.505,3))
        fiend_moves=[o[2] for o in g.orders if o[:2]==('move','ucry')]
        self.assertTrue(fiend_moves)
        self.assertTrue(all(min(dist(p,e) for e in foes)>before for p in fiend_moves))
        self.assertTrue(any(o[:2]==('move','Udea') for o in g.orders))
        self.assertIsNotNone(s.orb)

    def test_full_tick_withdraws_before_offensive_spells_or_contact_response(self):
        g,b,dk,army,orders,clock=ticks.EmergencyTests().controller()
        lich=unit('Ulic',51,0);lich.owner=0;army.append(lich)
        dk.hp=dk.hp_max;dk.x=-1800
        for u in army:u.hp=u.hp_max
        own=[dk,*army,b.home] if b.home else [dk,*army,*g.my_buildings()]
        g.snapshot=lambda **kw:N(clock=clock[0],in_game=True,units=own)
        g.units=lambda side,codes:[u for u in own if u.type in codes]
        g.my_buildings()[0].type='unp2';g.my_heroes=lambda:[dk,lich]
        g.inventory=lambda h:['ocor',None,None,None,None,None] if h is dk else [None]*6
        g.resources=lambda:dict(gold=500,gold_gathered=0,food_used=0)
        g.map=lambda:N(starts=[],walkable=lambda *p:True);g.walk_path=lambda a,z:[a,z]
        g.move=lambda u,x,y:orders.append(('move',u.type,(x,y))) or True
        g.enemies()[0].hp=300;g.enemies()[0].x=450
        b.micro.plan=lambda *a,**kw:{};b.shields.plan=lambda *a:{}
        b.emergency_portal=lambda *a:False
        b.combat_spells=lambda *a:orders.append(('offense',))
        b.respond_player_contact=lambda *a:orders.append(('contact-fight',)) or True
        b.tick(forced=Action.CREEP)
        self.assertTrue(any(o[:2]==('move','Ulic') for o in orders))
        self.assertNotIn(('offense',),orders);self.assertNotIn(('contact-fight',),orders)


if __name__=='__main__':unittest.main()
