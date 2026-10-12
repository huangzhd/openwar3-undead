import unittest
from types import SimpleNamespace as N
from test_baseline import FakeGame,unit
from test_upgrades_portal import UpgradeGame
import test_upgrades_portal as portals
import test_opening_safety_0131 as emergency
from undead.economy import Economy
from undead.policy import Action

class RevivalTests(unittest.TestCase):
    def make(self):
        g=UpgradeGame();events=[];e=Economy(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        e.ever_heroes={'Udea','Ulic','Nbrn'};e.mass_army=True;g.levels={'Rura':3,'Rucr':3,'Ruwb':1}
        g.own=[u for u in g.own if u.type!='Ulic'];g.gold=215
        altar=g.my_buildings({'uaod'})[0]
        def revive(a):
            g.commands.append('revive')
            if g.gold<340:return False # Fixture price; production must not consume the savings.
            g.gold-=340;g.busy[a.handle]=N(kind='queue',queue=['Ulic'])
            return True
        g.revive=revive
        return g,e,altar,events

    def test_income_accumulates_until_revive_and_paid_queue_releases_production(self):
        g,e,a,events=self.make()
        for t in (830,835,840):
            e.tick(g,t);g.gold+=45
        self.assertEqual(g.commands,['revive']*3)
        e.tick(g,845)
        self.assertEqual(g.busy[a.handle].queue,['Ulic'])
        self.assertFalse(e.revival_pending(g))
        g.gold=1000;e.tick(g,850)
        self.assertIn('ucry',g.commands)
        self.assertTrue(any(x['event']=='hero_revival_state' and x['queued']==['Ulic'] for x in events))

    def test_receipt_without_queue_and_failure_never_release_budget(self):
        for receipt in (True,False):
            g,e,a,events=self.make();g.revive=lambda a:receipt
            e.save_for_tp=True;e.expansion.pending_budget=lambda now:True
            for t in (10,11,15,20,25,30):e.tick(g,t)
            self.assertFalse(g.commands)
            self.assertEqual(len([x for x in events if x['event']=='revive_attempt']),3)
            self.assertEqual(e.revival_pending(g),{'Ulic'})

    def test_two_missing_heroes_keep_budget_until_both_paid(self):
        g,e,a,_=self.make();g.own=[u for u in g.own if u.type!='Udea']
        g.busy[a.handle]=N(kind='queue',queue=['Ulic'])
        self.assertEqual(e.revival_pending(g),{'Udea'})
        e.tick(g,900);self.assertFalse(g.commands)
        g.busy[a.handle]=N(kind='queue',queue=['Ulic','Udea'])
        self.assertFalse(e.revival_pending(g))

    def test_population_and_altar_prerequisites_can_be_restored(self):
        for obstacle in ('altar','food'):
            g,e,a,_=self.make();built=[]
            e.build=lambda g,code,home,now:built.append(code) or True
            if obstacle=='altar':g.own.remove(a)
            else:g.food=70
            e.tick(g,900)
            self.assertEqual(built,['uaod' if obstacle=='altar' else 'uzig'])
            self.assertFalse(g.commands)

    def test_observed_return_clears_missing_without_retraining_hero(self):
        g,e,a,_=self.make();g.own.append(unit('Ulic',999,owner=0))
        self.assertFalse(e.revival_pending(g))
        e.tick(g,900);self.assertNotIn('revive',g.commands)

    def test_other_shop_cannot_consume_unpaid_revival_budget(self):
        g,b,_=portals.PortalTests().make();b.economy.ever_heroes={'Udea','Ulic','Nbrn'}
        g.all_production=lambda owner:[]
        b.prepare_attack(g.heroes,100)
        self.assertFalse(g.purchases)
        b.shop_item(g.heroes,g.dk,g.shop,'rnec',105)
        self.assertFalse(g.purchases)

class OpeningParallelTests(unittest.TestCase):
    def test_altar_and_workers_share_initial_tick_with_sufficient_combined_resources(self):
        g=FakeGame(gold=500);g.own=[u for u in g.own if u.type not in {'uaod','Udea'}]
        workers=g.units('me',{'uaco'});g.own=[u for u in g.own if u not in workers[3:]]
        e=Economy(lambda *a,**kw:None);e.build=lambda g,c,h,t:g.commands.append(c) or True
        e.tick(g,0);self.assertEqual(g.commands,['uaco','uaod'])
        # With only enough money for one command, do not spend the stale snapshot twice.
        g.commands=[];e=Economy(lambda *a,**kw:None);g.gold=200
        e.build=lambda g,c,h,t:g.commands.append(c) or True
        e.tick(g,0);self.assertEqual(g.commands,['uaco'])

class PortalProtectionTests(unittest.TestCase):
    def test_channel_keeps_wounded_ally_moving_and_caster_untouched(self):
        g,b,dk,allies,orders,clock=emergency.EmergencyTests().controller()
        hurt,healthy=allies[:2];moves=[];fighters=[]
        b.teleport={'hero':dk.handle,'started':100}
        b.go_raw=lambda units,p,t:moves.extend(u.handle for u in units)
        b.fight=lambda units,foes,t:fighters.extend(u.handle for u in units)
        b.protect_portal_allies([dk,hurt,healthy],{dk.handle:(-300,0),hurt.handle:(-200,0)},101)
        self.assertEqual(moves,[hurt.handle]);self.assertEqual(fighters,[healthy.handle])

    def test_missing_hero_holds_creeping_but_not_required_base_defense(self):
        g,b,dk,allies,orders,clock=emergency.EmergencyTests().controller()
        b.economy.ever_heroes={'Udea','Ulic'};retreat=[]
        b.collective_retreat=lambda army,now:retreat.append(now)
        b.action=Action.CREEP
        self.assertTrue(b.recover_missing_heroes(allies,100));self.assertEqual(retreat,[100])
        b.action=Action.DEFEND
        self.assertFalse(b.recover_missing_heroes(allies,101))
        b.economy.ever_heroes={'Udea'};b.action=Action.CREEP
        self.assertFalse(b.recover_missing_heroes(allies,102))

if __name__=='__main__':unittest.main()
