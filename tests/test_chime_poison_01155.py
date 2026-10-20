import unittest
from test_micro_loot import unit
import test_battle_shop_0163 as shop
import test_drop_priority_0185 as drops
import test_opening_safety_0131 as ticks
from undead.controller import Controller
from undead.policy import Action


class ChimeCourierTests(unittest.TestCase):
    def scene(self):
        g,b,s,events=shop.ShoppingTests().make()
        g.dk.x=2000;g.lich.x=1900;g.dark.x=1950;g.shop.x=5000
        g.bags[g.dk.handle][1]='sbch'
        def sell(hero,slot,target):
            code=g.bags[hero.handle][slot];g.bags[hero.handle][slot]=None
            g.gold+=200;g.orders.append(('sell',hero.type,code));return True
        g.sell_item=sell
        return g,b,s,events

    def test_dk_travels_sells_with_refund_then_rejoins_moving_main_body(self):
        g,b,s,ev=self.scene()
        self.assertEqual(s.bone_chime_tick(b,g.heroes,[],580),{g.dk.handle})
        self.assertEqual(g.orders,[('move','Udea',(0,0))])
        g.dk.x=0
        s.bone_chime_tick(b,g.heroes,[],590);s.observe(g,591)
        self.assertNotIn('sbch',g.inventory(g.dk))
        self.assertTrue(any(e['event']=='shop_transaction_confirmed' and e['refund_excluding_gathering']==200 for e in ev))
        g.lich.x=g.dark.x=2200
        s.bone_chime_tick(b,g.heroes,[],594)
        self.assertEqual(g.orders[-1],('move','Udea',(2200,0)))
        g.dk.x=2100
        self.assertFalse(s.bone_chime_tick(b,g.heroes,[],600))
        self.assertTrue(any(e.get('reason')=='rejoined' for e in ev))
        self.assertFalse(any(o[0]=='group' for o in g.orders))

    def test_actual_removal_without_refund_is_not_confirmed_sale(self):
        g,b,s,ev=self.scene();g.dk.x=0
        def lost(hero,slot,target):
            g.bags[hero.handle][slot]=None;g.gold+=10;g.gathered+=10;return True
        g.sell_item=lost
        s.bone_chime_tick(b,g.heroes,[],10);s.observe(g,14)
        self.assertFalse(any(e['event']=='shop_transaction_confirmed' for e in ev))
        self.assertEqual(s.bone_chime_tick(b,g.heroes,[],14),{g.dk.handle})
        self.assertEqual(g.orders[-1],('move','Udea',(1900,0)))

    def test_safety_and_unreachable_shop_do_not_dispatch(self):
        for why in ('enemy','hurt','pulling','defend','path'):
            g,b,s,ev=self.scene();hostiles=[]
            if why=='enemy':hostiles=[unit('hfoo',90,2100)]
            if why=='hurt':g.dk.hp=1
            if why=='pulling':b.micro.pulling.add(g.dk.handle)
            if why=='defend':b.action=Action.DEFEND
            if why=='path':g.path_distance=lambda *a:None
            self.assertFalse(s.bone_chime_tick(b,g.heroes,hostiles,10),why)
            self.assertFalse(g.orders,why)

    def test_travel_stalls_stop_after_three_trips_without_periodic_reset(self):
        g,b,s,ev=self.scene()
        for start in (10,50,90):
            self.assertTrue(s.bone_chime_tick(b,g.heroes,[],start))
            self.assertFalse(s.bone_chime_tick(b,g.heroes,[],start+26))
        before=list(g.orders)
        for now in (130,250,500):self.assertFalse(s.bone_chime_tick(b,g.heroes,[],now))
        self.assertEqual(g.orders,before)

    def test_rejected_sales_are_bounded_and_do_not_claim_removal(self):
        g,b,s,ev=self.scene();g.dk.x=0
        g.sell_item=lambda *a:g.orders.append(('rejected',)) or False
        for now in (10,14,18,22,150):
            s.observe(g,now);s.bone_chime_tick(b,g.heroes,[],now)
        self.assertEqual(g.orders,[('rejected',)]*3)
        self.assertIn('sbch',g.inventory(g.dk))
        self.assertFalse(any(e['event']=='bone_chime_removed' for e in ev))

    def test_attack_rally_cannot_redirect_the_seller(self):
        g,b,s,ev=self.scene();s.bone_chime_tick(b,g.heroes,[],10)
        bot=Controller(g,lambda *a,**k:None);bot.battle_shop=s;bot.battle_enemies=[]
        bot.go_raw=b.go_raw;bot.go=lambda army,p,t:b.go(army,p,t)
        g.orders.clear()
        self.assertFalse(bot.prepare_attack(g.heroes,11))
        self.assertTrue(g.orders)
        self.assertFalse(any(o[1]=='Udea' for o in g.orders))

    def test_controller_keeps_main_creeping_without_overwriting_seller(self):
        g,b,dk,allies,orders,clock=ticks.EmergencyTests().controller()
        for u in [dk,*allies]:u.hp=u.hp_max
        g.enemies=lambda:[];g.current_target=lambda u:None
        g.inventory=lambda u:['sbch'] if u is dk else []
        store=unit('utom',88,-5000);store.owner=0
        g.my_units().append(store)
        b.economy.ready=lambda g,c:[store] if c=='utom' else []
        g.walk_path=lambda a,z:[a,z]
        g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        b.micro.plan=lambda *a,**k:{};b.shields.plan=lambda *a:{}
        b.frost_armor=lambda *a:None;b.combat_spells=lambda *a:None
        b.hero_support_pullbacks=lambda *a:{};b.recruit_tavern=lambda *a:set()
        b.recover_missing_heroes=lambda *a:False;b.collect_loot=lambda *a:False
        b.escort_tavern=lambda *a:False;b.stop_hero_chases=lambda *a:None
        b.battle_shop.rod_tick=lambda *a:set();b.battle_shop.orb_tick=lambda *a:set()
        b.first_attack_supply.tick=lambda *a:set()
        b.creep=lambda army,center,now:orders.append(('creep',[u.handle for u in army]))
        b.tick(forced=Action.CREEP)
        self.assertIn(('creep',[u.handle for u in allies]),orders)
        self.assertEqual([o for o in orders if o[0]=='move'],[('move',dk.handle,(-5000,0))])


class PoisonGnollTests(unittest.TestCase):
    def scene(self):
        b,own,carrier,other,orders,targets=drops.DropPriorityTests().make()
        b.creeping.map_alias='TH'
        poison=unit('ngns',82,640,320);poison.owner=12
        b.creeping.catalog[0]['spawns'].append(dict(code='ngns',x=640,y=0,poison_abilities=['ACvs']))
        b.creeping.observe_drop_carriers(b.g,[poison])
        b.g.creeps=lambda:[carrier,other,poison]
        lich=unit('Ulic',83,0,475);lich.owner=0;lich.mana=140;lich.mana_max=300
        own.append(lich);dk=next(u for u in own if u.type=='Udea')
        dk.mana=100;dk.mana_max=300
        casts=[];b.g.cast=lambda h,code,**kw:casts.append((h.type,code,kw['target'].type)) or True
        b.heal_candidates=lambda *a:[];b.coil_rescue_needed=lambda *a:False
        b.creep_mana.allow=lambda *a,**kw:False
        return b,own,carrier,other,poison,orders,targets,casts

    def test_poison_target_gets_coil_nova_and_spider_focus_despite_mana_reserve(self):
        b,a,c,o,p,orders,targets,casts=self.scene()
        b.fight(a,[o],10)
        self.assertEqual(casts,[('Udea','deathcoil','ngns'),('Ulic','frostnova','ngns')])
        self.assertIs(targets[a[0].handle],p)

    def test_hidden_distant_other_camp_and_other_map_cannot_trigger_exception(self):
        for why in ('hidden','distant','camp','map'):
            b,a,c,o,p,orders,targets,casts=self.scene()
            if why=='hidden':b.g.creeps=lambda:[c,o]
            if why=='distant':p.x=1600
            if why=='camp':b.creeping.drop_camps[p.handle]=99
            if why=='map':b.creeping.map_alias='NI'
            b.fight(a,[o],10)
            self.assertFalse(casts,why)
            self.assertIs(targets[a[0].handle],c)

    def test_healing_cooldown_and_mana_guards_still_apply(self):
        for why in ('heal','cooldown','mana'):
            b,a,c,o,p,orders,targets,casts=self.scene()
            if why=='heal':b.heal_candidates=lambda *a:[p]
            if why=='cooldown':b.g.cooldown=lambda *a:5
            if why=='mana':
                for h in a:h.mana=0
            b.fight(a,[p],10)
            self.assertFalse(any(x[1]=='deathcoil' for x in casts),why)
            if why!='heal':self.assertFalse(casts,why)

    def test_enemy_player_preempts_poison_creep(self):
        b,a,c,o,p,orders,targets,casts=self.scene()
        for u in a:u.mana=0
        enemy=unit('hfoo',90,50,400);enemy.owner=1
        b.fight(a,[p,enemy],10)
        self.assertTrue(all(t is enemy for t in targets.values()))


if __name__=='__main__':unittest.main()
