import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.policy import Situation,Action

class Game:
    def __init__(self):
        self.fiends=[unit('ucry',i,0,100) for i in (1,2,3)]
        self.heroes=[unit('Udea',4,0,600),unit('Ulic',5,20,600)]
        self.statues=[unit('uobs',6,0,500),unit('uobs',7,0,500)]
        self.army=self.fiends+self.heroes+self.statues
        self.home=unit('unp2',80,-1800,1000);self.home_shop=unit('utom',81,-1700,600)
        self.goblin=unit('ngme',82,-600,600);self.crypt=unit('usep',83,-1900,600)
        self.slaughter=unit('uslh',84,-1800,600)
        self.buildings=[self.home,self.home_shop,self.crypt,self.slaughter]
        self.foes=[unit('Otch',90,600,900)];self.foes[0].owner=1
        self.skills={self.foes[0].handle:[dict(code='AOsh',level=2)]};self.cd={};self.gold=100
        self.gathered=1000;self.orders=[];self.targets={};self.refund=True;self.stock=True
        self.queue={self.crypt.handle:N(kind='queue',queue=['ucry'],progress=.3),
                    self.slaughter.handle:N(kind='queue',queue=['uobs'],progress=.8)}
        self.bags={h.handle:[None]*6 for h in self.heroes}
        for u in self.army+self.buildings+[self.goblin]+self.foes:
            u.has_detail=True;u.alive=True;u.visible_to=lambda _:True
            if not hasattr(u,'owner'):u.owner=0
    dist=staticmethod(dist)
    me=lambda self:0
    def unit(self,h):return next((u for u in self.army+self.buildings+[self.goblin]+self.foes if u.handle==h),None)
    def resources(self):return dict(gold=self.gold,gold_gathered=self.gathered,food_used=59)
    def my_heroes(self):return self.heroes
    def my_buildings(self,codes=None):return [u for u in self.buildings if codes is None or u.type in codes]
    def production(self,u):return self.queue.get(u.handle)
    def all_production(self,side):return [(self.unit(h),p) for h,p in self.queue.items()]
    def units(self,side,codes):return [u for u in self.army+self.buildings+([self.goblin] if side=='all' else []) if u.type in codes]
    def inventory(self,u):return self.bags[u.handle]
    def abilities(self,u):return self.skills.get(u.handle,[])
    def buffs(self,u):return []
    def cooldown(self,u,code):return self.cd.get((u.handle,code),0)
    def current_target(self,u):return self.targets.get(u.handle)
    def enemies(self):return self.foes
    def path_distance(self,a,b):return dist(a,b)
    def walk_path(self,a,b):return [a,b]
    def map(self):return N(walkable=lambda *a:True)
    def hold(self,u):self.orders.append(('hold',u.handle));return True
    def move(self,u,x,y):self.orders.append(('move',u.handle,(x,y)));return True
    def cast(self,u,spell,**kw):self.orders.append(('cast',u.handle,spell));return True
    def cancel(self,u):
        self.orders.append(('cancel',u.handle))
        if self.refund:
            code=self.queue[u.handle].queue.pop();self.gold+=215 if code=='ucry' else 200
            if not self.queue[u.handle].queue:self.queue.pop(u.handle)
        return True
    def buy(self,shop,code):
        self.orders.append(('buy',shop.handle,code))
        if self.stock:
            self.gold-=250;bag=self.bags[self.heroes[0].handle];bag[bag.index(None)]=code
        return self.stock

class RecoveryTests(unittest.TestCase):
    def make(self):
        g=Game();events=[];b=Controller(g,lambda event,**kw:events.append(dict(event=event,**kw)))
        b.home=g.home;b.attack_committed=True;b.action=Action.ATTACK;b.situation=Situation(780,tier=3)
        return b,g,events
    def observe(self,b,g,now=780,raid=False):b.army_recovery.observe(b,g.army,g.foes,now,raid)
    def test_same_hp_ready_wave_retreats_but_cooldown_or_no_mana_keeps_fighting(self):
        for state,want in [('ready',True),('cooldown',False),('mana',False),('unknown',True),('skill_unseen',False)]:
            with self.subTest(state=state):
                b,g,events=self.make();tc=g.foes[0]
                if state=='cooldown':g.cd[(tc.handle,'AOsh')]=7
                if state=='mana':tc.mana=50
                if state=='unknown':g.cd[(tc.handle,'AOsh')]=None
                if state=='skill_unseen':g.skills={}
                self.observe(b,g)
                self.assertEqual(b.army_recovery.active,want)
                self.assertTrue(b.army_recovery.heal_priority)
                if state=='unknown':self.assertTrue(events[0]['risk'][0]['cooldown_unknown'])
    def test_damage_level_and_formation_change_mass_loss_risk(self):
        b,g,_=self.make();g.skills[g.foes[0].handle][0]['level']=1
        self.observe(b,g);self.assertFalse(b.army_recovery.active)
        g.skills[g.foes[0].handle][0]['level']=2
        g.fiends[0].y=-350;g.fiends[2].y=350
        self.observe(b,g);self.assertFalse(b.army_recovery.active)
        for f in g.fiends:f.y=0
        self.observe(b,g);self.assertTrue(b.army_recovery.active)
    def test_two_hurt_fiends_do_not_recall_mostly_healthy_army(self):
        b,g,_=self.make()
        for i in range(10,17):
            f=unit('ucry',i,0,600);g.fiends.append(f);g.army.append(f)
        self.observe(b,g);self.assertFalse(b.army_recovery.active)
    def test_distant_healthy_reinforcements_do_not_hide_frontline_risk(self):
        b,g,_=self.make()
        for i in range(10,12):
            f=unit('ucry',i,-3000,600);g.fiends.append(f);g.army.append(f)
        self.observe(b,g);self.assertTrue(b.army_recovery.active)
        self.assertNotIn((10,0),b.army_recovery.members)
    def test_already_cast_wave_counts_even_after_mana_and_cooldown_spent(self):
        b,g,_=self.make();tc=g.foes[0];tc.mana=0;g.cd[(tc.handle,'AOsh')]=8
        b.hero_pressure.events=[N(handle=tc.handle,spell='AOsh',clock=779.5)]
        self.observe(b,g);self.assertTrue(b.army_recovery.active)
    def test_flamestrike_uses_short_damage_window_not_entire_duration(self):
        b,g,_=self.make();tc=g.foes[0];tc.type='Hblm';g.skills[tc.handle]=[dict(code='AHfs',level=1)]
        self.observe(b,g);self.assertFalse(b.army_recovery.active) # first second 60, not total 270
        for f in g.fiends:f.hp=50
        self.observe(b,g);self.assertTrue(b.army_recovery.active)
    def test_current_attacks_can_make_two_deaths_imminent(self):
        b,g,_=self.make();g.skills={};g.foes=[]
        for i,f in enumerate(g.fiends[:2]):
            f.hp=10;e=unit('otau',90+i,60,1000);e.owner=1;e.has_detail=True
            g.foes.append(e);g.targets[e.handle]=f
        self.observe(b,g);self.assertTrue(b.army_recovery.active)
    def test_live_economy_upgrade_tuple_does_not_crash_recovery(self):
        # AZ 20261013-003657 crashed on the first group-health risk check:
        # Economy.upgrade_levels stores (attack, armor), not an SDK tech dict.
        b,g,_=self.make();b.economy.upgrade_levels=(1,0)
        self.observe(b,g)
        self.assertTrue(b.army_recovery.active)
    def test_observed_armor_upgrade_changes_next_attack_survival(self):
        from openwar3 import combat
        b,g,_=self.make();g.skills={};g.foes=[]
        base=combat.stats('ucry');armored=combat.stats('ucry',tech={'Rucr':3})
        weapon=combat.stats('otau').weapon_vs(base)
        raw=weapon.dmg_avg*combat.damage_multiplier(weapon.attack_type,base.armor_type)
        hp=raw*(combat.armor_factor(base.armor)+combat.armor_factor(armored.armor))/2
        for i,f in enumerate(g.fiends[:2]):
            f.hp=hp;e=unit('otau',90+i,60,1000);e.owner=1;e.has_detail=True
            g.foes.append(e);g.targets[e.handle]=f
        b.economy.upgrade_levels=(3,0)
        self.assertTrue(b.army_recovery.next_volley(b,g.fiends,g.foes,780))
        b.economy.upgrade_levels=(0,3)
        self.assertFalse(b.army_recovery.next_volley(b,g.fiends,g.foes,780))
    def test_post_battle_badly_hurt_army_recovers_without_mana_recall(self):
        b,g,_=self.make();g.foes=[];self.observe(b,g);self.assertTrue(b.army_recovery.active)
        for f in g.fiends:f.hp=600
        for h in g.heroes:h.mana=0
        self.observe(b,g,785);self.assertFalse(b.army_recovery.active)
    def test_only_low_hp_treatment_switches_statues_without_retreat(self):
        b,g,_=self.make();g.cd[(g.foes[0].handle,'AOsh')]=7
        self.observe(b,g);b.army_recovery.statues(b,780)
        self.assertFalse(b.army_recovery.active)
        self.assertTrue(all(('cast',s.handle,'replenishlifeon') in g.orders for s in g.statues))
        for f in g.fiends:f.hp=600
        self.observe(b,g,790);b.army_recovery.statues(b,790)
        self.assertIn(('cast',g.statues[1].handle,'replenishmanaon'),g.orders)
    def test_choose_nearest_safe_shop_and_switch_when_route_unsafe(self):
        b,g,_=self.make();self.observe(b,g)
        self.assertIs(b.army_recovery.shop,g.goblin)
        b.creeping.safe_route=lambda game,start,end:end!=(g.goblin.x,g.goblin.y)
        self.observe(b,g,781);self.assertIs(b.army_recovery.shop,g.home_shop)
    def test_recovery_destination_clears_spell_range_and_overrides_stale_pull_hold(self):
        b,g,_=self.make();self.observe(b,g);r=b.army_recovery
        pulls={u.handle:(u.x,u.y) for u in g.fiends}
        r.tick(b,g.army,g.foes,780,pulls)
        for f in g.fiends:
            moves=[o for o in g.orders if o[0]=='move' and o[1]==f.handle]
            self.assertTrue(moves)
            self.assertGreater(dist(moves[-1][2],g.foes[0]),1125)
        g.goblin.x=-200;self.observe(b,g,781)
        self.assertIs(r.shop,g.home_shop) # Nearer but inside the next wave's danger zone.
    def test_no_cancellation_until_buyer_arrives_then_actual_refund_and_purchase(self):
        b,g,events=self.make();self.observe(b,g);r=b.army_recovery
        r.tick(b,g.army,g.foes,780,{})
        self.assertFalse(any(o[0]=='cancel' for o in g.orders))
        for h in g.heroes:h.x=-600
        self.observe(b,g,781);r.tick(b,g.army,g.foes,781,{})
        self.assertEqual([o for o in g.orders if o[0]=='cancel'],[('cancel',g.crypt.handle)])
        self.observe(b,g,782);r.tick(b,g.army,g.foes,782,{})
        self.assertIn('shea',g.bags[g.heroes[0].handle]);self.assertEqual(g.gold,65)
        self.observe(b,g,783)
        self.assertTrue(any(e['event']=='recovery_refund_observed' and e['refund_excluding_gathering']==215 for e in events))
        self.assertTrue(any(e['event']=='recovery_scroll_observed' for e in events))
        self.assertTrue(r.active) # Buying is not healing.
        for f in g.fiends:f.hp=500
        self.observe(b,g,784);self.assertFalse(r.active)
    def test_purchased_scroll_is_used_and_real_heal_is_required_before_resume(self):
        b,g,events=self.make();g.gold=250
        for u in g.army:u.x=-600
        self.observe(b,g);r=b.army_recovery;r.tick(b,g.army,g.foes,780,{})
        def use(hero,slot):
            g.bags[hero.handle][slot]=None
            for f in g.fiends:f.hp+=150
            return True
        g.use_item=use
        self.observe(b,g,782)
        b.consumables.tick(g,g.army,[],782,b.cast_until)
        b.consumables.observe(g,783)
        self.observe(b,g,783)
        self.assertTrue(any(e['event']=='consumable_effect_observed' and e['code']=='shea' for e in events))
        self.assertTrue(r.active)
        for f in g.fiends:f.hp=500
        self.observe(b,g,790);self.assertFalse(r.active)
    def test_enough_gold_no_cancel_and_research_tail_never_cancelled(self):
        b,g,_=self.make();g.gold=250
        for h in g.heroes:h.x=-600
        self.observe(b,g);b.army_recovery.tick(b,g.army,g.foes,780,{})
        self.assertFalse(any(o[0]=='cancel' for o in g.orders))
        b,g,_=self.make();g.queue[g.crypt.handle].queue.append('Ruwb');g.queue.pop(g.slaughter.handle)
        b.army_recovery.active=True;b.army_recovery.started=780;b.army_recovery.fund_scroll(b,780)
        self.assertFalse(g.orders)
    def test_rejected_cancel_and_gathering_are_not_refund_and_attempts_are_bounded(self):
        b,g,events=self.make();g.refund=False
        for h in g.heroes:h.x=-600
        for t in (780,781,784,788,792):
            g.gold+=1;g.gathered+=1;self.observe(b,g,t);b.army_recovery.tick(b,g.army,g.foes,t,{})
        self.assertEqual(sum(o[0]=='cancel' for o in g.orders),2)
        self.assertFalse(any(e['event']=='recovery_refund_observed' for e in events))
    def test_missing_stock_releases_budget_and_tries_other_shop(self):
        b,g,_=self.make();g.gold=300;g.stock=False
        for h in g.heroes:h.x=-600
        self.observe(b,g);b.army_recovery.tick(b,g.army,g.foes,780,{})
        self.observe(b,g,784);self.assertIs(b.army_recovery.shop,g.home_shop)
        b.creeping.safe_route=lambda *a:False
        self.observe(b,g,785);self.assertFalse(b.army_recovery.reserve)
    def test_base_defense_and_teleport_override_group_shopping(self):
        for reason in ('raid','portal'):
            b,g,_=self.make()
            if reason=='raid':b.situation.threatened=True
            else:b.teleport=dict(hero=g.heroes[0].handle)
            self.observe(b,g,raid=reason=='raid')
            self.assertFalse(b.army_recovery.tick(b,g.army,g.foes,780,{}))
            self.assertFalse(b.army_recovery.reserve);self.assertFalse(g.orders)

if __name__=='__main__':unittest.main()
