import unittest
from types import SimpleNamespace as N
from test_baseline import FakeGame,unit
from test_micro_loot import dist
from undead.economy import Economy
from undead.controller import Controller
from undead.policy import Action,Situation

class UpgradeGame(FakeGame):
    def __init__(self):
        super().__init__(tier=3,gold=3000)
        self.own += [unit(c,100+i,owner=0) for i,c in enumerate(['uslh','Ulic','Nbrn']+['ucry']*5+['uobs']*2)]
        self.food=50;self.lumber=2000;self.levels={'Rura':0,'Rucr':0}
        self.invs={'Udea':['stwp']+[None]*5,'Ulic':['ocor']+[None]*5}
    def resources(self):return dict(gold=self.gold,lumber=self.lumber,food_used=self.food,food_cap=70)
    def inventory(self,u):return self.invs.get(u.type,[None]*6)
    def tech_many(self,codes):return dict(self.levels)
    def train(self,b,code):
        r=super().train(b,code)
        self.busy[b.handle]=N(kind='queue',queue=[code])
        return r

class UpgradeTests(unittest.TestCase):
    def make(self):
        g=UpgradeGame();e=Economy(lambda *a,**k:None)
        e.ever_heroes={h.type for h in g.my_heroes()}
        return g,e
    def test_real_population_threshold_and_spare_resources(self):
        g,e=self.make();g.food=47
        e.research_upgrades(g,1);self.assertFalse(g.commands)
        g.food=48;g.gold=149;e.mass_army=True
        e.research_upgrades(g,4);self.assertFalse(g.commands)
        g.gold=150;g.lumber=50
        self.assertTrue(e.research_upgrades(g,7))
        self.assertEqual(g.commands,['Rura'])
    def test_three_completed_attack_levels_before_any_armor(self):
        g,e=self.make()
        for level in range(3):
            g.levels['Rura']=level;g.busy.clear()
            self.assertTrue(e.research_upgrades(g,level*10+1))
            self.assertEqual(g.commands[-1],'Rura')
            self.assertFalse(e.research_upgrades(g,level*10+5))
        g.levels['Rura']=3;g.busy.clear()
        self.assertTrue(e.research_upgrades(g,35))
        self.assertEqual(g.commands,['Rura','Rura','Rura','Rucr'])
        g.busy.clear();g.levels['Rucr']=3
        self.assertFalse(e.research_upgrades(g,40))
    def test_unknown_levels_and_missing_tier_cannot_fall_back_to_armor(self):
        g,e=self.make();g.levels['Rura']=None
        self.assertFalse(e.research_upgrades(g,1))
        g.levels['Rura']=2;g.can_do=lambda *a:183
        self.assertFalse(e.research_upgrades(g,5))
        self.assertFalse(g.commands)
    def test_reserves_missing_scroll_and_core_composition(self):
        g,e=self.make();g.invs['Udea']=[None]*6
        g.gold=499
        self.assertFalse(e.research_upgrades(g,1))
        g.gold=500
        self.assertTrue(e.research_upgrades(g,5))
        g.busy.clear();g.own=[u for u in g.own if u.type!='Nbrn'];e.ever_heroes.remove('Nbrn')
        g.gold=924
        self.assertFalse(e.research_upgrades(g,9))
        g.gold=925;g.lumber=184
        self.assertFalse(e.research_upgrades(g,13))
        g.lumber=185
        self.assertTrue(e.research_upgrades(g,17))
    def test_research_precedes_extra_fiends_and_economy_saves_for_portal(self):
        g,e=self.make()
        e.tick(g,1000)
        self.assertEqual(g.commands,['Rura'])
        g,e=self.make();e.save_for_tp=True
        e.tick(g,1000)
        self.assertFalse(g.commands)
    def test_second_graveyard_cannot_duplicate_queued_research(self):
        g,e=self.make();g.own.append(unit('ugrv',999,owner=0))
        self.assertTrue(e.research_upgrades(g,1))
        self.assertFalse(e.research_upgrades(g,5))
        self.assertEqual(g.commands,['Rura'])

class PortalGame:
    def __init__(self):
        self.dk=unit('Udea',1,owner=0);self.lich=unit('Ulic',2,owner=0)
        self.shop=unit('utom',3,owner=0);self.home=unit('unp2',4,owner=0)
        self.dk.mana=200;self.lich.mana=200
        self.heroes=[self.dk,self.lich];self.inv={self.dk.handle:[None]*6,self.lich.handle:[None]*6}
        self.gold=1000;self.purchases=[];self.transfers=[];self.shops=[self.shop]
    def my_heroes(self):return self.heroes
    def inventory(self,u):return self.inv[u.handle]
    def resources(self):return {'gold':self.gold}
    def nearest(self,units,p):return units[0] if units else None
    def dist(self,a,b):return dist(a,b)
    def buy(self,shop,code):self.purchases.append(code);return N(reason='accepted')
    def give_item(self,donor,slot,receiver):
        self.transfers.append((donor.handle,slot,receiver.handle));return True

class PortalTests(unittest.TestCase):
    def make(self):
        g=PortalGame();events=[];b=Controller(g,lambda e,**kw:events.append((e,kw)))
        b.home=g.home;b.action=Action.ATTACK
        b.economy.ready=lambda *a:g.shops
        self.moves=[];self.fights=[]
        b.go=lambda *a,**kw:self.moves.append(a)
        b.fight=lambda *a,**kw:self.fights.append(a)
        return g,b,events
    def test_purchase_receipt_does_not_allow_attack_until_dk_has_scroll(self):
        g,b,events=self.make()
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertEqual(g.purchases,['stwp'])
        self.assertFalse(b.prepare_attack(g.heroes,2))
        g.inv[g.dk.handle][0]='stwp'
        self.assertTrue(b.prepare_attack(g.heroes,3))
        self.assertIn('attack_portal_ready',[e for e,_ in events])
        g.inv[g.dk.handle][0]=None
        self.assertFalse(b.prepare_attack(g.heroes,5))
        self.assertEqual(g.purchases,['stwp','stwp'])
    def test_teammate_scroll_allows_departure_without_duplicate_purchase(self):
        g,b,_=self.make();b.prepare_attack(g.heroes,1)
        g.inv[g.lich.handle][0]='stwp'
        self.assertTrue(b.prepare_attack(g.heroes,5))
        self.assertFalse(g.transfers)
        self.assertEqual(g.purchases,['stwp'])
    def test_full_inventory_preserves_items_and_blocks_departure(self):
        g,b,_=self.make();g.inv[g.dk.handle]=['rnec','rat6','rat6','rat6','rat6','rat6']
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertEqual(g.transfers,[(g.dk.handle,1,g.lich.handle)])
        self.assertFalse(g.purchases)
        g.inv[g.lich.handle]=['rat6']*6
        self.assertFalse(b.prepare_attack(g.heroes,5))
        self.assertFalse(g.purchases)
    def test_local_combat_is_not_interrupted_by_shopping(self):
        g,b,_=self.make();b.battle_enemies=[unit('hfoo',9)]
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertTrue(self.fights)
        self.assertFalse(self.moves)
        self.assertFalse(g.purchases)
    def test_stock_retry_burst_is_bounded_and_missing_shop_does_not_allow_attack(self):
        g,b,_=self.make()
        for t in (1,4,7,10,20,50,100):b.prepare_attack(g.heroes,t)
        self.assertEqual(len(g.purchases),3)
        b.prepare_attack(g.heroes,127)
        self.assertEqual(len(g.purchases),4)
        g.shops=[]
        self.assertFalse(b.prepare_attack(g.heroes,131))
        self.assertEqual(len(g.purchases),4)
    def test_confirmed_scroll_resets_retry_delay_for_next_departure(self):
        g,b,_=self.make()
        for t in (1,4,7):b.prepare_attack(g.heroes,t)
        g.inv[g.dk.handle][0]='stwp'
        self.assertTrue(b.prepare_attack(g.heroes,8))
        g.inv[g.dk.handle][0]=None
        self.assertFalse(b.prepare_attack(g.heroes,11))
        self.assertEqual(len(g.purchases),4)

    def test_absent_dk_never_allows_attack(self):
        g,b,_=self.make();g.heroes=[g.lich]
        self.assertFalse(b.prepare_attack(g.heroes,1))
        self.assertFalse(g.purchases)

if __name__=='__main__':unittest.main()
