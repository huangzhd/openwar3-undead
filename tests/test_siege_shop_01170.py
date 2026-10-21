import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import unit
import test_stall_0154 as stalls
import test_first_attack_01132 as supplies_tests
import test_opening_safety_0131 as ticks
from undead.policy import Action


class SiegeProgressTests(unittest.TestCase):
    def test_controller_contact_proximity_cannot_cancel_bypass_but_actual_attack_can(self):
        class ObservedMicro(Exception):pass
        for attacking in (False,True):
            g,b,dk,a,orders,clock=ticks.EmergencyTests().controller()
            foe=g.enemies()[0];g.current_target=lambda u:dk if attacking and u is foe else None
            b.action=Action.ATTACK;b.attack_committed=True
            b.combat_progress.deferred[foe.handle]=(foe.type,110)
            seen=[]
            def micro(army,hostiles,*args,**kwargs):
                seen.extend(hostiles);raise ObservedMicro
            b.micro.plan=micro
            with self.assertRaises(ObservedMicro):b.tick()
            self.assertEqual(foe in b.player_contact,attacking)
            self.assertEqual(foe in seen,attacking)

    def test_two_ineffective_bouts_do_not_reacquire_unchanged_target_on_timer(self):
        p,a,f,ev=stalls.ProgressTests().setup()
        for now in range(40):p.observe(a,[f],now,True)
        for now in (60,600):
            p.observe(a,[f],now,True)
            self.assertFalse(p.allowed(f,now))
        f.x+=81;p.observe(a,[f],601,True)
        self.assertTrue(p.allowed(f,601))

    def test_quarantine_releases_for_actual_attack_health_type_or_new_visibility(self):
        for change in ('attacking','health','morph','new_visibility'):
            p,a,f,ev=stalls.ProgressTests().setup();p.quarantine(f,0,'test')
            if change=='health':f.hp-=3
            if change=='morph':f.type='hrif'
            if change=='new_visibility':p.observe(a,[],1,True)
            p.observe(a,[f],2,True,current_target=lambda e:a[0] if change=='attacking' else None)
            self.assertTrue(p.allowed(f,2),change)

    def test_new_nearby_threat_does_not_revive_unchanged_bad_target(self):
        p,a,f,ev=stalls.ProgressTests().setup();p.quarantine(f,0,'test')
        other=unit('hrif',99,350);a.append(unit('ucry',98,20))
        p.observe(a,[f,other],1,True)
        self.assertFalse(p.allowed(f,1));self.assertTrue(p.allowed(other,1))
        # Walking beyond the local 600 radius while still visible also keeps it excluded.
        p.observe(a,[other],2,True,visible=[f,other])
        self.assertFalse(p.allowed(f,2))

    def test_rejections_need_multiple_units_rounds_and_no_effect(self):
        p,a,f,ev=stalls.ProgressTests().setup()
        for u in a:p.attack_result(u,f,0,False)
        self.assertTrue(p.allowed(f,0))
        for now in (1.3,2.6):
            for u in a:p.attack_result(u,f,now,False)
        self.assertFalse(p.allowed(f,3))
        for mode in ('accepted','damage','single','defense'):
            p,a,f,ev=stalls.ProgressTests().setup()
            for now in (0,1.3,2.6):
                if mode=='damage':f.hp-=10
                for u in a[:1] if mode=='single' else a:
                    p.attack_result(u,f,now,mode=='accepted',enabled=mode!='defense')
            self.assertTrue(p.allowed(f,3),mode)

    def test_recorded_idle_hero_no_longer_blocks_visible_building_siege(self):
        data=json.loads((Path(__file__).parent/'fixtures/al_194054_siege.json').read_text(encoding='utf-8'))
        foes=[]
        for row in data['enemies']:
            r=row['unit'];u=unit(r['type'],r['handle_lo'],r['x'],r['hp']);u.y=r['y'];u.owner=r['owner']
            u.has_detail=False;foes.append(u)
        ghost=next(u for u in foes if u.type=='Ucrl');building=next(u for u in foes if u.type=='usep')
        b,orders,events=stalls.StallTests().bot();g=b.g
        army=[unit('ucry',800+i,2400+i*20,550) for i in range(3)]
        for u in army:u.y=3800
        g.enemies=lambda:foes;g.production=lambda u:None;g.order_of=lambda u:0
        g.attack=lambda u,t,**kw:orders.append(('attack',u.handle,t.type)) or True
        self.assertFalse(b.focus_siege(army,foes,0))
        for now in (0,1.3,2.6):
            for u in army:b.combat_progress.attack_result(u,ghost,now,False)
        b.battle_enemies=[]
        self.assertTrue(b.focus_siege(army,foes,4))
        self.assertTrue(any(o[0]=='attack' and o[2]=='usep' for o in orders))
        self.assertFalse(any(o[0]=='attack' and o[2]=='Ucrl' for o in orders))
        orders.clear();b.battle_enemies=[ghost]
        b.go(army,(3000,5000),5,attack=True)
        self.assertTrue(orders);self.assertTrue(all(o[0]=='move' for o in orders))


class SingleShopTripTests(unittest.TestCase):
    def test_portal_sale_and_orb_purchase_complete_before_returning_to_lich(self):
        g,b,ev=supplies_tests.SuppliesTests().scene();g.dk.x=2000;g.dk.mana=200;g.gold=250
        s=b.battle_shop;supplies=b.first_attack_supply
        # Not enough cash without TP proceeds: still one bounded shop mission.
        self.assertFalse(supplies.tick(b,g.heroes,[],450,3));self.assertFalse(g.orders)
        self.assertEqual(s.orb_tick(b,g.heroes,[],451,3),{g.dk.handle})
        self.assertEqual(g.orders[-1],('move','Udea',(0,0)))
        g.dk.x=0;s.orb_tick(b,g.heroes,[],460,3);s.observe(g,461)
        self.assertNotIn('stwp',g.inventory(g.dk));self.assertTrue(s.orb)
        mark=len(g.orders);s.orb_tick(b,g.heroes,[],464,3);s.observe(g,465)
        self.assertIn('ocor',g.inventory(g.dk))
        self.assertFalse(any(o[0]=='move' for o in g.orders[mark:]))
        s.orb_tick(b,g.heroes,[],468,3)
        self.assertEqual(g.orders[-1],('move','Udea',(g.lich.x,0)))
        g.dk.x=g.lich.x;s.orb_tick(b,g.heroes,[],472,3);s.observe(g,473)
        s.orb_tick(b,g.heroes,[],476,3)
        self.assertIn('ocor',g.inventory(g.lich));self.assertIsNone(s.orb)
        self.assertFalse(supplies.tick(b,g.heroes,[],477,3));self.assertTrue(supplies.done)
        self.assertFalse(any(o[:2]==('buy','pman') for o in g.orders))

    def test_effectless_portal_sale_never_returns_as_success_or_buys_into_full_inventory(self):
        g,b,ev=supplies_tests.SuppliesTests().scene();s=b.battle_shop
        g.bags[g.dk.handle]=['stwp','cnob','rag1','rin1','rnec','will']
        g.sell_item=lambda *a:True
        for now in (500,504,508,512):
            s.observe(g,now);s.orb_tick(b,g.heroes,[],now,3)
        self.assertNotIn('ocor',g.inventory(g.dk));self.assertIn('stwp',g.inventory(g.dk))
        self.assertFalse(any(o[0]=='move' for o in g.orders))
        s.orb_tick(b,g.heroes,[],621,3);self.assertIsNone(s.orb)
        self.assertFalse(any(e['event']=='orb_courier_end' and e['reason']=='delivered' for e in ev))


if __name__=='__main__':unittest.main()
