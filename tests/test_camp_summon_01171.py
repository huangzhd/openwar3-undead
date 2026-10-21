import unittest
from types import SimpleNamespace as N
import test_al_route_01166 as routes
from test_micro_loot import unit
from undead.policy import Action


class CampSummonTests(unittest.TestCase):
    def scene(self,index=1,north=False):
        b,g,army,c=routes.ALRouteTests().scene(north)
        route=c.al_route(b.home);c.cleared=set(route[:index]);c.active=None
        old=next(p for p in c.catalog if p['id']==route[index-1])
        for u in army:u.x=old['x'];u.y=old['y'];u.hp=u.hp_max
        dk=army[0];own=list(army);orders=[];events=[];cool=[0];accepted=[True]
        b.log=lambda e,**kw:events.append(dict(event=e,**kw));b.camp_summon.log=b.log
        b.action=Action.CREEP;b.ni_rod_stop.done=True
        b.go_raw=lambda us,p,n:orders.extend(('move',u.handle,p) for u in us)
        b.go=lambda us,p,n,attack=False:orders.extend(('route',u.handle,p) for u in us)
        g.current_target=lambda u:None;g.unit=lambda h:next((u for u in own if u.handle==h),None)
        g.units=lambda side,codes:[u for u in own if u.type in codes]
        g.inventory=lambda u:['rnec'] if u.type=='Udea' else []
        g.cooldown=lambda *a:cool[0]
        g.use_item=lambda h,i:orders.append(('rod',h.handle)) or accepted[0]
        g.map=lambda:N(starts=[],walkable=lambda *p:True)
        c.safe_route=lambda *a:True
        b.rod_corpses={(999,999):dict(clock=175,point=(dk.x+100,dk.y),code='nwwf')}
        for u in army[1:]:b.skeleton_expiry[u.handle]=230
        return b,g,army,c,own,orders,events,cool,accepted

    def spawn(self,b,own,now):
        dk=own[0]
        for i in (900,901):
            u=unit('uske',i,dk.x,180);u.y=dk.y;u.owner=0;u.hp_max=180;own.append(u)
        b.observe_rod_skeletons(now)

    def test_first_clear_waits_for_two_actual_new_skeletons_then_moves_same_tick(self):
        for north in (False,True):
            b,g,a,c,own,orders,ev,cool,ok=self.scene(north=north);center=(a[0].x,a[0].y)
            b.creep(a,center,178)
            self.assertTrue(any(o[0]=='rod' for o in orders));self.assertFalse(any(o[0]=='route' for o in orders))
            self.assertIsNone(c.active);self.assertTrue(b.camp_summon.active)
            # Existing skeletons cannot stand in for the requested new pair.
            b.creep(a,center,179);self.assertTrue(b.camp_summon.active)
            self.spawn(b,own,179.5);orders.clear();b.creep(own,center,180)
            target=next(p for p in c.catalog if p['id']==c.al_route(b.home)[1])
            self.assertEqual(c.active['id'],target['id'])
            self.assertTrue(any(o[0]=='route' and o[2]==(target['x'],target['y']) for o in orders))
            self.assertTrue(any(e['event']=='al_camp_summon_end' and e['confirmed'] for e in ev))
            count=sum(e['event']=='al_camp_summon_attempt' for e in ev)
            b.creep(own,center,181)
            self.assertEqual(sum(e['event']=='al_camp_summon_attempt' for e in ev),count)

    def test_first_clear_waits_short_cooldown_but_is_bounded(self):
        b,g,a,c,own,orders,ev,cool,ok=self.scene();cool[0]=4
        self.assertTrue(b.camp_summon.tick(b,a,178));self.assertFalse(orders)
        cool[0]=0;self.assertTrue(b.camp_summon.tick(b,a,182));self.assertIn(('rod',a[0].handle),orders)
        b,g,a,c,own,orders,ev,cool,ok=self.scene();cool[0]=100
        b.camp_summon.tick(b,a,178)
        self.assertFalse(b.camp_summon.tick(b,a,208));self.assertEqual(ev[-1]['reason'],'time_limit')

    def test_later_camp_counts_only_healthy_nearby_long_lived_non_scout_skeletons(self):
        for mode in ('healthy','expiring','wounded','far','scout','unknown'):
            b,g,a,c,own,orders,ev,cool,ok=self.scene(index=3)
            for u in a[1:]:b.skeleton_expiry[u.handle]=400
            if mode=='expiring':b.skeleton_expiry[a[1].handle]=183
            if mode=='wounded':a[1].hp=20
            if mode=='far':a[1].x+=2000
            if mode=='scout':b.skeleton_scouts.assignments[a[1].handle]={}
            if mode=='unknown':b.skeleton_expiry.pop(a[1].handle)
            result=b.camp_summon.tick(b,a,178)
            self.assertEqual(any(o[0]=='rod' for o in orders),mode!='healthy',mode)
            self.assertEqual(result,mode!='healthy',mode)

    def test_receipt_without_units_and_rejected_casts_cannot_release_as_success(self):
        for acceptance in (True,False):
            b,g,a,c,own,orders,ev,cool,ok=self.scene();ok[0]=acceptance
            for now in (178,181,184):self.assertTrue(b.camp_summon.tick(b,a,now))
            self.assertFalse(b.camp_summon.tick(b,a,187))
            self.assertEqual(sum(o[0]=='rod' for o in orders),3)
            self.assertFalse(ev[-1]['confirmed']);self.assertNotIn((999,999),b.rod_used)

    def test_missing_resources_unsafe_corpse_and_unknown_cooldown_do_not_stall(self):
        for mode in ('no_rod','no_corpse','used','expired','unsafe','unreachable','cooldown'):
            b,g,a,c,own,orders,ev,cool,ok=self.scene()
            if mode=='no_rod':g.inventory=lambda u:[]
            if mode=='no_corpse':b.rod_corpses={}
            if mode=='used':b.rod_used.add((999,999))
            if mode=='expired':b.rod_corpses[(999,999)]['clock']=100
            if mode=='unsafe':c.safe_route=lambda *a:False
            if mode=='unreachable':g.path_distance=lambda *a:None
            if mode=='cooldown':cool[0]=None
            self.assertFalse(b.camp_summon.tick(b,a,178),mode)
            self.assertFalse(any(o[0]=='rod' for o in orders),mode)

    def test_no_interrupt_to_actual_combat_safety_home_rebuy_or_other_map(self):
        for mode in ('guard_attacking','own_attacking','player','retreat','home_stop','other_map'):
            b,g,a,c,own,orders,ev,cool,ok=self.scene(index=2 if mode=='home_stop' else 1)
            guard=unit('ngnw',888,a[0].x+300,300);guard.y=a[0].y;guard.owner=12
            if mode.startswith('guard') or mode.startswith('own'):
                g.creeps=lambda:[guard]
                g.current_target=lambda u:a[0] if mode=='guard_attacking' and u is guard else guard if mode=='own_attacking' and u is a[0] else None
            if mode=='player':b.player_contact=[guard]
            if mode=='retreat':b.action=Action.RETREAT
            if mode=='home_stop':b.ni_rod_stop.done=False
            if mode=='other_map':c.map_alias='TH'
            self.assertFalse(b.camp_summon.tick(b,a,178),mode);self.assertFalse(orders,mode)

    def test_generic_summon_does_not_consume_the_corpse_ahead_of_preparation(self):
        b,g,a,c,own,orders,ev,cool,ok=self.scene()
        self.assertFalse(b.maintain_skeletons(a[0],0,178));self.assertFalse(orders)
        b.camp_summon.tick(b,a,178)
        self.assertEqual(sum(o[0]=='rod' for o in orders),1)

    def test_active_preparation_releases_carrier_when_shopping_or_retreat_takes_over(self):
        for mode in ('shopping','pulling','absent','low_health'):
            b,g,a,c,own,orders,ev,cool,ok=self.scene();cool[0]=4
            self.assertTrue(b.camp_summon.tick(b,a,178));orders.clear()
            if mode=='shopping':b.shopping.add(a[0].handle)
            if mode=='pulling':b.micro.pulling.add(a[0].handle)
            if mode=='low_health':a[0].hp=10
            party=a[1:] if mode=='absent' else a
            self.assertFalse(b.camp_summon.tick(b,party,179),mode)
            self.assertFalse(orders);self.assertIsNone(b.camp_summon.active)


if __name__=='__main__':unittest.main()
