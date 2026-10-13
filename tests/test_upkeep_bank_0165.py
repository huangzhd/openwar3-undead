import unittest
from types import SimpleNamespace as N
from undead.economy import Economy
from test_baseline import unit
import test_growth_expansion_0149 as growth
import test_lr_recovery_0162 as revival

class UpkeepTests(unittest.TestCase):
    def make(self):
        g=growth.GrowthGame(6);g.food=50;g.gold=399;events=[]
        e=Economy(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        e.ever_heroes={h.type for h in g.my_heroes()};e.scout=(9999,0)
        return g,e,events

    def test_bank_at_399_then_fund_multiple_producers_without_relocking(self):
        g,e,events=self.make();second=unit('usep',991,owner=0);g.own.append(second)
        e.tick(g,700);self.assertFalse(g.commands);self.assertEqual(g.gold,399)
        g.gold=400;e.tick(g,703)
        self.assertEqual(g.commands,['ucry']);self.assertEqual(g.food,53);self.assertEqual(g.gold,185)
        g.gold+=30;e.tick(g,706)
        self.assertEqual(g.commands,['ucry','ucry']);self.assertEqual(g.food,56);self.assertEqual(g.gold,0)
        self.assertTrue(any(x['event']=='upkeep_burst_released' for x in events))

    def test_48_food_cannot_accidentally_cross_50_but_47_can_fill(self):
        g,e,_=self.make();g.food=48;e.tick(g,700);self.assertFalse(g.commands)
        g,e,_=self.make();g.food=47;g.gold=250
        e.mass_army=True;crypt=g.my_buildings({'usep'})[0]
        self.assertTrue(e.train(g,crypt,'ucry',700));self.assertEqual(g.food,50)
        g.busy.clear();self.assertFalse(e.train(g,crypt,'ucry',703));self.assertEqual(g.food,50)

    def test_tick_can_fill_47_to_50_without_waiting_for_400(self):
        g,e,_=self.make();g.food=47;g.gold=250;e.tick(g,700)
        self.assertEqual(g.commands,['ucry']);self.assertEqual(g.food,50)

    def test_third_hero_food_is_reserved_before_orb_and_during_courier_trip(self):
        # AZ 20261013-003657: spider at 560.425s took 45 -> 48;
        # hiring the third hero at 578.805s then crossed straight to 53.
        for mass in (False,True):
            for third in ('Nbrn','Nngs'):
                with self.subTest(mass=mass,third=third):
                    g,e,events=self.make();g.food=45;g.gold=600
                    g.own=[u for u in g.own if u.type!='Nbrn']
                    e.ever_heroes.discard('Nbrn');e.third_hero=third;e.mass_army=mass
                    crypt=g.my_buildings({'usep'})[0]
                    self.assertFalse(e.train(g,crypt,'ucry',700))
                    self.assertEqual(g.food,45);self.assertEqual(g.gold,600)

    def test_fill_42_to_45_then_wait_for_third_and_research_at_50(self):
        g,e,_=self.make();g.food=42;g.gold=900
        g.own=[u for u in g.own if u.type!='Nbrn'];e.ever_heroes.discard('Nbrn')
        crypt=g.my_buildings({'usep'})[0]
        self.assertTrue(e.train(g,crypt,'ucry',700));self.assertEqual(g.food,45)
        g.busy.clear()
        self.assertFalse(e.train(g,crypt,'ucry',703))
        g.own.append(unit('Nbrn',992,owner=0));g.food+=5;g.gold=300;g.levels['Rura']=0
        e.tick(g,706)
        self.assertEqual(g.food,50);self.assertEqual(g.commands,['ucry','Rura'])
        self.assertFalse(e.upkeep_released)

    def test_reserved_hero_food_cannot_be_used_by_other_unit_producers(self):
        for code,building in [('uobs','uslh'),('ugho','usep'),('uaco','unp2')]:
            with self.subTest(code=code):
                g,e,_=self.make();g.food=45;g.gold=900
                g.own=[u for u in g.own if u.type!='Nbrn'];e.ever_heroes.discard('Nbrn')
                self.assertFalse(e.train(g,g.my_buildings({building})[0],code,700))
                self.assertEqual(g.food,45)

    def test_upgrades_spend_before_growth_and_attack_stays_before_armor(self):
        g,e,_=self.make();g.levels={'Rura':2,'Rucr':0,'Ruwb':1};g.gold=900
        e.tick(g,700);self.assertEqual(g.commands,['Rura']);self.assertFalse(e.upkeep_released)
        g.busy.clear();g.levels['Rura']=3;g.gold=900;e.tick(g,704)
        self.assertEqual(g.commands,['Rura','Rucr']);self.assertFalse(e.upkeep_released)

    def test_frontline_spends_portal_budget_on_research_then_units(self):
        g,e,events=self.make();g.food=59;g.gold=250
        g.invs['Udea']=[None]*6;g.levels.update(Rura=2,Rucr=0)
        g.costs['Rura']=(250,200)
        e.mass_army=True;e.upkeep_released=True;e.upkeep_crossed=True
        e.save_for_tp=True;e.frontline_combat=True
        e.tick(g,700)
        self.assertEqual(g.commands,['Rura']);self.assertEqual(g.gold,0)
        g.gold=215;e.tick(g,704)
        self.assertEqual(g.commands,['Rura','ucry']);self.assertEqual(g.gold,0)
        g.busy.clear();g.levels['Rura']=3;g.gold=150;e.frontline_combat=False
        e.tick(g,710);self.assertEqual(g.commands,['Rura','ucry'])

    def test_frontline_bank_release_keeps_400_gate_without_portal_reserve(self):
        g,e,_=self.make();g.invs['Udea']=[None]*6;e.frontline_combat=True
        e.tick(g,700);self.assertFalse(g.commands)
        g.gold=400;e.tick(g,704);self.assertEqual(g.commands,['ucry'])

    def test_missing_portal_reserve_is_not_spent_on_population_break(self):
        g,e,_=self.make();g.invs['Udea']=[None]*6;g.gold=400
        e.tick(g,700);self.assertFalse(g.commands)
        g.invs['Udea'][0]='stwp';e.tick(g,704);self.assertEqual(g.commands,['ucry'])

    def test_unhired_third_and_unfunded_upgrade_cannot_be_spent_on_growth(self):
        # Live LR 614.98: 48 food, 757 gold, no portal or third, upgrades 0/0.
        g,e,_=self.make();g.food=48;g.gold=757;g.levels['Rura']=0
        g.invs['Udea']=[None]*6
        g.own=[u for u in g.own if u.type!='Nbrn'];e.ever_heroes.remove('Nbrn')
        e.tick(g,700)
        self.assertFalse(g.commands);self.assertEqual(g.food,48)
        g.gold=925;e.tick(g,704)
        self.assertEqual(g.commands,['Rura']);self.assertEqual(g.food,48)
        self.assertFalse(e.upkeep_released)
        # Hiring the hero spends its 425; the active research is already paid.
        g.own.append(unit('Nbrn',992,owner=0));g.gold=749
        e.tick(g,705);self.assertEqual(g.commands,['Rura'])
        g.gold=750;e.tick(g,706)
        self.assertEqual(g.commands,['Rura','ucry']);self.assertEqual(g.food,51)

    def test_research_throttle_does_not_release_its_unspent_budget(self):
        g,e,_=self.make();g.food=48;g.gold=400;g.levels['Rura']=0
        e.upgrade_checked=700
        e.tick(g,701)
        self.assertFalse(g.commands);self.assertEqual(g.food,48)
        e.tick(g,704)
        self.assertEqual(g.commands,['Rura']);self.assertEqual(g.food,48)
        # No double reservation of an already paid research queue.
        g.gold=400;e.tick(g,705)
        self.assertEqual(g.commands,['Rura','ucry']);self.assertEqual(g.food,51)

    def test_hero_food_crossing_is_not_permission_to_unlock_growth(self):
        # LR 0.1.79: third hero jumps 48->53 without any bank release.
        g,e,_=self.make();g.food=53;g.gold=408;g.levels['Rura']=0
        g.invs['Udea']=[None]*6;e.mass_army=True
        e.tick(g,700)
        self.assertFalse(g.commands);self.assertEqual(g.food,53)
        self.assertFalse(e.upkeep_released)
        g.gold=500;e.tick(g,704)
        self.assertEqual(g.commands,['Rura']);self.assertEqual(g.food,53)

    def test_idle_grave_saves_then_spiders_and_research_run_together(self):
        g,e,events=self.make();g.food=59;g.gold=200;g.levels['Rura']=2;g.levels['Rucr']=0
        e.mass_army=True;e.upkeep_released=True;e.upkeep_crossed=True
        g.costs.update(Rura=(250,200),Rucr=(150,75))
        e.tick(g,700)
        self.assertFalse(g.commands);self.assertEqual(g.gold,200)
        g.gold=250;e.tick(g,704)
        self.assertEqual(g.commands,['Rura']);self.assertEqual(g.gold,0)
        # The grave is busy: enough new income immediately funds another spider.
        g.gold=215;e.tick(g,705)
        self.assertEqual(g.commands,['Rura','ucry']);self.assertEqual(g.food,62)
        # After attack 3 finishes, armor begins before the next spider queue.
        g.busy.clear();g.levels['Rura']=3;g.gold=149;e.tick(g,710)
        self.assertEqual(g.commands,['Rura','ucry'])
        g.gold=150;e.tick(g,714)
        self.assertEqual(g.commands,['Rura','ucry','Rucr'])
        g.gold=215;e.tick(g,715)
        self.assertEqual(g.commands,['Rura','ucry','Rucr','ucry'])

    def test_visible_base_threat_can_spend_below_400(self):
        g,e,_=self.make();g.gold=250;e.tick(g,700,threat=True)
        self.assertEqual(g.commands,['ucry']);self.assertEqual(g.food,53)

    def test_actual_losses_back_to_50_rearm_saving(self):
        g,e,events=self.make();g.food=53;g.gold=500;e.tick(g,700)
        self.assertIn('ucry',g.commands)
        g.busy.clear();g.food=50;g.commands=[];g.gold=399;e.tick(g,704)
        self.assertFalse(g.commands);self.assertFalse(e.upkeep_released)
        self.assertTrue(any(x['event']=='upkeep_bank_reset' for x in events))

    def test_hero_revival_still_has_priority_over_banking(self):
        g,e,a,events=revival.RevivalTests().make();e.upkeep_released=False;g.food=50;g.gold=350
        e.tick(g,700)
        self.assertEqual(g.commands,['revive']);self.assertEqual(g.busy[a.handle].queue,['Ulic'])

if __name__=='__main__':unittest.main()
