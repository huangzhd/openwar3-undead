import unittest
import test_tc_pressure_01186 as battle
import test_safe_rejoin_01207 as rejoin
import test_tc_scroll_01203 as scroll
from test_baseline import unit
from undead.controller import Controller
from training import TrainingController


class DeliverySupportTests(unittest.TestCase):
    def test_delayed_real_bags_finish_before_layout_without_overwriting_give(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=battle.TcFirstTests().scene(kind)
            lich=own[6];own[:]=[u for u in own if not u.is_hero or u in (dk,lich)]
            foes.clear();g.current_target=lambda _:None
            dk.x,dk.y=-1648,208;lich.x,lich.y=-1936,240
            bags={dk.handle:['phea','rnec','shea','cnob','cnob',None],
                  lich.handle:['shea','pnvl','sror','rde2','rde1',None]}
            g.inventory=lambda u:list(bags[u.handle])
            before=sorted(c for bag in bags.values() for c in bag if c)
            clock=[1];pending=[];interruptions=[]
            def give(donor,slot,receiver):
                pending.append((clock[0],donor,slot,receiver));return True
            def move(u,x,y):
                if pending and u in (pending[0][1],pending[0][3]):interruptions.append(u.handle)
                u.x,u.y=x,y;return True
            g.give_item=give;g.move=move
            for i in range(50):
                clock[0]=1+i*.25
                if pending and clock[0]-pending[0][0]>=1.5:
                    _,donor,slot,receiver=pending.pop(0)
                    bags[receiver.handle][bags[receiver.handle].index(None)]=bags[donor.handle][slot]
                    bags[donor.handle][slot]=None
                b.equipment.tick(g,own,[],clock[0],b.cast_until)
                b.prepare_battle(clock[0],army=own,target=(2000,0))
            self.assertFalse(interruptions)
            self.assertTrue({'rde1','rde2'}<=set(bags[dk.handle]))
            self.assertEqual(bags[lich.handle].count('cnob'),2)
            self.assertEqual(before,sorted(c for bag in bags.values() for c in bag if c))
            self.assertEqual(sum(e=='equipment_transfer_confirmed' for e,_ in events),5)
            self.assertIn('sror',bags[lich.handle]);self.assertNotIn('sror',bags[dk.handle])
            self.assertFalse(b.equipment.reserved)

    def test_pending_delivery_releases_only_own_locks_on_danger(self):
        b,g,own,foes,orders,events,effects,dk,tc=battle.TcFirstTests().scene()
        lich=own[6];bags={h.handle:[None]*6 for h in own if h.is_hero};bags[dk.handle][0]='cnob'
        g.inventory=lambda u:bags[u.handle];g.give_item=lambda *a:True
        self.assertTrue(b.equipment.tick(g,own,[],1,b.cast_until))
        b.cast_until[lich.handle]=9 # A newer rescue spell owns this lock.
        b.equipment.tick(g,own,foes,2,b.cast_until)
        self.assertFalse(b.equipment.reserved);self.assertNotIn(dk.handle,b.cast_until)
        self.assertEqual(b.cast_until[lich.handle],9)

    def test_low_statue_returns_after_quiet_then_supplies_and_repulls_on_focus(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,car=rejoin.SafeRejoinTests().scene('uobs',kind)
            own[1].hp=200;pulls={car.handle:(car.x,car.y)}
            b.micro.hit[car.handle]=9
            b.rejoin_battle_units(own,foes,10,pulls)
            self.assertIsNone(b.battle_rejoin[car.handle]['quiet'])
            b.rejoin_battle_units(own,foes,11,pulls)
            b.rejoin_battle_units(own,foes,12,pulls)
            self.assertGreater(pulls[car.handle][0],car.x+300)
            car.x,car.y=pulls[car.handle]
            b.rejoin_battle_units(own,foes,13,pulls)
            b.statue_support.tick(b,own,foes,13,set(pulls))
            self.assertTrue(any(o[0]=='cast' and o[1]==car.handle and o[2]=='replenishlife' for o in orders))
            g.current_target=lambda e:car if e==foes[0] else None
            b.cast_until.clear();b.rejoin_battle_units(own,foes,15,pulls)
            self.assertIsNone(b.battle_rejoin[car.handle]['quiet'])

    def test_dk_waits_through_main_fight_and_only_joins_safe_cleanup(self):
        for kind in (Controller,TrainingController):
            b,g,own,foes,orders,events,effects,dk,tc=battle.TcFirstTests().scene(kind)
            foes.extend(unit('ogru',100+i,owner=1,x=400) for i in range(4))
            b.attack_dk(own,foes,10)
            self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders))
            foes[:]=[tc];tc.hp=100
            b.attack_dk(own,foes,12)
            self.assertIn(('attack',dk.handle,tc.handle),orders)
            for why in ('wounded_lich','low_dk','far_lich','danger_lane'):
                orders.clear();own[6].hp=own[6].hp_max;own[6].x=0;dk.hp=dk.hp_max;foes[:]=[tc]
                if why=='wounded_lich':own[6].hp=100
                if why=='low_dk':dk.hp=dk.hp_max*.5
                if why=='far_lich':own[6].x=-1500
                if why=='danger_lane':foes.append(unit('otbk',200,owner=1,x=tc.x+100))
                b.attack_dk(own,foes,15)
                self.assertFalse(any(o[0]=='attack' and o[1]==dk.handle for o in orders),why)


class BurstScrollTests(unittest.TestCase):
    def scene(self):
        g,c,locks,events,h=scroll.ScrollEfficiencyTests().scene()
        tc=unit('Otch',100,owner=1,x=100);fs=unit('Ofar',101,owner=1,x=150)
        for e in (tc,fs):e.has_detail=True
        cds={'AOws':0.,'AOcl':0.}
        g.abilities=lambda e:[dict(code=code,level=2,cooldown=cds[code])] if (code:=('AOws' if e==tc else 'AOcl' if e==fs else None)) else []
        return g,c,locks,events,h,[tc,fs],cds

    def test_stomp_chain_round_heals_three_above_half_without_waiting_for_majority(self):
        g,c,locks,events,h,foes,cds=self.scene()
        for i in range(5):
            u=unit('ucry',200+i,owner=0,x=100);u.hp=u.hp_max=600;g.army.append(u)
        c.tick(g,g.army,foes,10,locks)
        cds['AOws']=6
        for u in g.army[:3]:u.hp-=100
        c.tick(g,g.army,foes,10.5,locks);self.assertFalse(g.orders)
        cds['AOws']=5.5;cds['AOcl']=9
        for u in g.army[:3]:u.hp-=50
        c.tick(g,g.army,foes,11,locks)
        self.assertEqual(g.orders,[('use','Ulic','shea')])
        self.assertTrue(events[-1]['after_aoe']);self.assertEqual(events[-1]['half_health_units'],0)
        self.assertEqual(events[-1]['aoe_abilities'],['AOcl','AOws'])
        c.tick(g,g.army,foes,15,locks);self.assertEqual(len(g.orders),1)

    def test_no_fake_round_from_initial_cooldown_visibility_gap_or_no_damage(self):
        for why in ('initial','gap','no_damage','out_of_range','healed','unknown'):
            g,c,locks,events,h,foes,cds=self.scene()
            if why=='initial':cds.update(AOws=6,AOcl=9)
            c.tick(g,g.army,foes,10,locks)
            if why=='gap':c.tick(g,g.army,[],10.25,locks)
            cds.update(AOws=6,AOcl=9)
            for u in g.army[:3]:u.hp=450
            if why=='no_damage':
                for u in g.army[:3]:u.hp=600
            if why=='out_of_range':h.x=3000
            if why=='healed':
                for u in g.army[:3]:u.hp=590
            if why=='unknown':g.abilities=lambda _:[]
            c.tick(g,g.army,foes,10.5,locks)
            self.assertFalse(g.orders,why)

    def test_engine_cooldown_control_and_spell_lock_still_block_noncritical_burst(self):
        for why in ('cooldown','controlled','casting'):
            g,c,locks,events,h,foes,cds=self.scene();c.tick(g,g.army,foes,10,locks)
            cds.update(AOws=6,AOcl=9)
            for u in g.army[:3]:u.hp=450
            if why=='cooldown':g.cd[(h.handle,'AIha')]=3
            if why=='controlled':g.bs[h.handle]=['BSTN']
            if why=='casting':locks[h.handle]=12
            c.tick(g,g.army,foes,10.5,locks);self.assertFalse(g.orders,why)

    def test_three_pressured_wounds_are_timely_but_two_or_light_wounds_are_not(self):
        for hp,count,want in ((350,3,True),(350,2,False),(520,3,False)):
            g,c,locks,events,h,foes,cds=self.scene()
            for u in g.army[:count]:u.hp=hp
            g.current_target=lambda e:g.army[0] if e==foes[0] else g.army[1]
            c.tick(g,g.army,foes,10,locks)
            self.assertEqual(bool(g.orders),want,(hp,count))


if __name__=='__main__':unittest.main()
