import unittest
from types import SimpleNamespace as N
from undead.equipment import Equipment,LICH_ITEMS,can_receive
from undead.loot import Loot
from test_micro_loot import unit,dist
from test_upgrades_portal import PortalGame
from undead.controller import Controller

class EquipmentTests(unittest.TestCase):
    def setup_game(self):
        g=PortalGame();events=[];equipment=Equipment(lambda e,**kw:events.append((e,kw)))
        g.dk.is_hero=g.lich.is_hero=True
        return g,equipment,events

    def observed_transfer(self,g):
        donor,slot,receiver=g.transfers[-1]
        bag=g.inv[donor];other=g.inv[receiver]
        other[other.index(None)]=bag[slot];bag[slot]=None

    def test_every_claw_circle_and_boot_transfers_and_requires_inventory_confirmation(self):
        for code in LICH_ITEMS:
            with self.subTest(code=code):
                g,e,events=self.setup_game();g.inv[g.dk.handle][0]=code
                self.assertTrue(e.tick(g,g.heroes,[],1,{}))
                self.assertFalse(any(n=='equipment_transfer_confirmed' for n,_ in events))
                self.observed_transfer(g)
                e.tick(g,g.heroes,[],4,{})
                self.assertNotIn(code,g.inv[g.dk.handle]);self.assertIn(code,g.inv[g.lich.handle])
                self.assertTrue(any(n=='equipment_transfer_confirmed' for n,_ in events))

    def test_existing_items_stay_and_overflow_waits_on_allies_with_orb_slot_reserved(self):
        g,e,_=self.setup_game()
        wanted=['ratf','ratc','rat9','cnob','bspd']
        g.inv[g.dk.handle]=wanted+[None];g.inv[g.lich.handle]=['rlif','rin1']+[None]*4
        for now in range(1,50,4):
            if e.tick(g,g.heroes,[],now,{}):self.observed_transfer(g)
        self.assertCountEqual(g.inv[g.lich.handle],['rlif','rin1','ratf','ratc','rat9',None])
        self.assertCountEqual([c for c in g.inv[g.dk.handle] if c],['cnob','bspd'])
        self.assertTrue(can_receive(g.lich,g.inv[g.lich.handle],'ocor'))
        self.assertFalse(can_receive(g.lich,g.inv[g.lich.handle],'rat3'))

    def test_capacity_preserves_equipped_items_instead_of_upgrading_or_dropping(self):
        g,e,_=self.setup_game()
        g.inv[g.dk.handle]=['ratf','ratc','rat9','rat6','bspd',None]
        g.inv[g.lich.handle]=['ocor','bspd','cnob','rat3',None,None]
        before=sorted(c for bag in g.inv.values() for c in bag if c)
        for now in range(1,70,4):
            if e.tick(g,g.heroes,[],now,{}):self.observed_transfer(g)
        self.assertCountEqual(g.inv[g.lich.handle],['ocor','bspd','cnob','rat3','ratf','ratc'])
        self.assertEqual(sorted(c for bag in g.inv.values() for c in bag if c),before)

    def test_already_full_lich_frees_the_orb_slot(self):
        g,e,_=self.setup_game();g.inv[g.lich.handle]=['rat6']*6
        self.assertTrue(e.tick(g,g.heroes,[],1,{}));self.observed_transfer(g)
        e.tick(g,g.heroes,[],4,{})
        self.assertEqual(g.inv[g.lich.handle].count(None),1)
        self.assertIn('rat6',g.inv[g.dk.handle])

    def test_no_space_on_any_hero_keeps_items_and_does_not_claim_success(self):
        g,e,events=self.setup_game();g.inv[g.lich.handle]=['cnob']*6;g.inv[g.dk.handle]=['ratf']*6
        self.assertFalse(e.tick(g,g.heroes,[],1,{}));self.assertFalse(g.transfers)
        self.assertFalse(events)

    def test_danger_distance_and_cast_do_not_cancel_combat_or_send_solo_item_delivery(self):
        for block in ('enemy','distance','cast','pulling'):
            g,e,_=self.setup_game();g.inv[g.dk.handle][0]='rat6'
            heroes=g.heroes;foes=[];cast={}
            if block=='enemy':foes=[unit('ogru',20,100)]
            if block=='distance':g.lich.x=1000
            if block=='cast':cast[g.dk.handle]=5
            if block=='pulling':heroes=[g.lich]
            self.assertFalse(e.tick(g,heroes,foes,1,cast));self.assertFalse(g.transfers)

    def test_unconfirmed_or_rejected_transfer_is_bounded(self):
        for accepted in (True,False):
            g,e,events=self.setup_game();g.inv[g.dk.handle][0]='rat6'
            g.give_item=lambda donor,slot,receiver:g.transfers.append((donor.handle,slot,receiver.handle)) or accepted
            for now in range(1,80):e.tick(g,g.heroes,[],now,{})
            self.assertEqual(len(g.transfers),3)
            self.assertFalse(any(n=='equipment_transfer_confirmed' for n,_ in events))
            self.assertIn('rat6',g.inv[g.dk.handle])

    def test_loot_prefers_lich_and_will_not_fill_its_reserved_slot(self):
        dk=unit('Udea',1,0);lich=unit('Ulic',2,100)
        inv={dk.handle:[None]*6,lich.handle:[None]*6};picked=[]
        item=N(type='ratc',handle_lo=10,handle_hi=0,addr=10,x=10,y=0,life=75)
        g=N(dist=dist,inventory=lambda h:inv[h.handle],items_on_ground=lambda:[item],
            path_distance=dist,pick_up=lambda h,it:picked.append(h.type) or True)
        Loot({},lambda *a,**kw:None).tick(g,[dk,lich],[],1)
        self.assertEqual(picked,['Ulic'])
        inv[lich.handle]=['rat6']*5+[None];picked.clear()
        Loot({},lambda *a,**kw:None).tick(g,[dk,lich],[],1)
        self.assertEqual(picked,['Udea'])
        inv[lich.handle]=['rat6']*4+['ocor',None];picked.clear()
        Loot({},lambda *a,**kw:None).tick(g,[dk,lich],[],1)
        self.assertEqual(picked,['Ulic'])

    def test_portal_and_rod_room_making_cannot_consume_lich_orb_slot(self):
        g,e,_=self.setup_game();b=Controller(g,lambda *a,**kw:None)
        g.inv[g.dk.handle]=['stwp','rat6','rat9','cnob','bspd','rlif']
        g.inv[g.lich.handle]=['rat6']*5+[None]
        self.assertFalse(b.shop_item(g.heroes,g.dk,g.shop,'rnec',1))
        self.assertFalse(g.transfers)

    def test_full_dk_can_deliver_orb_to_reserved_slot_before_buying_portal(self):
        from test_upgrades_portal import PortalTests
        g,b,_=PortalTests().make()
        g.inv[g.dk.handle]=['rnec','rat6','ocor','cnob','bspd','rlif']
        g.inv[g.lich.handle]=['rat6']*5+[None]
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertEqual(g.transfers,[(g.dk.handle,2,g.lich.handle)])
        self.observed_transfer(g)
        self.assertIn('ocor',g.inv[g.lich.handle])
        g.lich.x=1200
        b.prepare_attack(g.heroes,4)
        self.assertEqual(g.purchases,['stwp'])

    def test_portal_room_making_does_not_fill_reserved_slot_with_non_orb(self):
        from test_upgrades_portal import PortalTests
        g,b,_=PortalTests().make()
        g.inv[g.dk.handle]=['rnec','rat6','rat9','cnob','bspd','rlif']
        g.inv[g.lich.handle]=['rat6']*5+[None]
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertFalse(g.transfers)
        self.assertFalse(g.purchases)

    def test_full_lich_moves_out_without_giving_up_equipment_then_dk_buys_portal(self):
        from test_upgrades_portal import PortalTests
        g,b,_=PortalTests().make();moves=[]
        g.map=lambda:N(walkable=lambda *p:True);g.path_distance=dist
        g.move=lambda h,x,y:moves.append((h.handle,x,y)) or True
        g.inv[g.dk.handle]=['rnec']+[None]*5;g.inv[g.lich.handle]=['rat6']*5+['ocor']
        before=g.inv[g.lich.handle][:]
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertFalse(g.purchases);self.assertFalse(g.transfers)
        self.assertEqual(g.inv[g.lich.handle],before)
        self.assertEqual(moves[-1][0],g.lich.handle)
        self.assertGreater(dist(moves[-1][1:],g.shop),1050)
        g.lich.x,g.lich.y=moves[-1][1:]
        b.prepare_attack(g.heroes,4)
        self.assertEqual(g.purchases,['stwp'])

    def test_shopping_clearance_cannot_exclude_full_hero_from_retreat_or_defense(self):
        from undead.policy import Action
        lich=unit('Ulic',1,0);lich.mana=0;foe=unit('ogru',2,100);foe.owner=1
        moves=[];attacks=[]
        g=N(me=lambda:0,dist=dist,move=lambda h,*p:moves.append(h.handle) or True,
            current_target=lambda u:None,is_building=lambda u:False,
            attack=lambda h,*a,**kw:attacks.append(h.handle) or True)
        for action in (Action.RETREAT,Action.DEFEND):
            b=Controller(g,lambda *a,**kw:None);b.shopping={lich.handle};b.action=action;b.attack_committed=True
            b.go([lich],(-1000,0),1)
            b.fight([lich],[foe],1)
        self.assertEqual(moves,[lich.handle,lich.handle])
        self.assertEqual(attacks,[lich.handle,lich.handle])

if __name__=='__main__':unittest.main()
