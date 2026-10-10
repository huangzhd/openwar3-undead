import unittest
from types import SimpleNamespace as N
from test_baseline import unit
from test_upgrades_portal import UpgradeGame
from undead.controller import Controller
from undead.economy import Economy

class WebTests(unittest.TestCase):
    def make(self):
        g=UpgradeGame();g.levels['Ruwb']=0
        e=Economy(lambda *a,**k:None);e.ever_heroes={h.type for h in g.my_heroes()}
        return g,e

    def test_only_visible_enemy_air_triggers_and_new_match_resets(self):
        g=N(me=lambda:0);b=Controller(g,lambda *a,**k:None)
        b.observe_air([unit('hgry',visible=False),unit('hgry',owner=0),unit('hgry',owner=12),unit('hfoo')],1)
        self.assertFalse(b.economy.enemy_air_seen)
        b.observe_air([unit('hgry')],2)
        self.assertTrue(b.economy.enemy_air_seen)
        b.observe_air([],3)
        self.assertTrue(b.economy.enemy_air_seen)
        self.assertFalse(Controller(g,lambda *a,**k:None).economy.enemy_air_seen)

    def test_air_research_precedes_attack_upgrades_and_waits_for_real_level(self):
        g,e=self.make();e.enemy_air_seen=True
        e.tick(g,1000)
        self.assertEqual(g.commands,['Ruwb'])
        self.assertNotEqual(e.web_level,1)
        e.research_web(g,1004)
        self.assertEqual(g.commands,['Ruwb'])
        g.busy.clear();g.levels['Ruwb']=1
        e.tick(g,1008)
        self.assertEqual(e.web_level,1)
        self.assertEqual(g.commands,['Ruwb','Rura'])

    def test_no_air_unknown_level_tier_one_and_busy_crypt_do_not_start_web(self):
        g,e=self.make();self.assertFalse(e.research_web(g,1))
        e.enemy_air_seen=True;g.levels['Ruwb']=None
        self.assertFalse(e.research_web(g,5))
        g.levels['Ruwb']=0;hall=g.my_buildings({'unp2'})[0];hall.type='unpl'
        self.assertFalse(e.research_web(g,9))
        hall.type='unp2';crypt=g.my_buildings({'usep'})[0]
        g.busy[crypt.handle]=N(kind='queue',queue=['ucry'])
        self.assertTrue(e.research_web(g,13))
        self.assertFalse(g.commands)
        g.busy.clear();self.assertTrue(e.research_web(g,17))
        self.assertEqual(g.commands,['Ruwb'])

    def test_reserves_150_gold_and_lumber_but_portal_gate_keeps_priority(self):
        g,e=self.make();e.enemy_air_seen=True;g.gold=149;g.lumber=149
        e.tick(g,1000);self.assertFalse(g.commands)
        g.gold=150;g.lumber=150;e.tick(g,1004)
        self.assertEqual(g.commands,['Ruwb'])
        g,e=self.make();e.enemy_air_seen=True;e.save_for_tp=True
        e.tick(g,1000);self.assertFalse(g.commands)

    def test_rejected_research_is_bounded(self):
        g,e=self.make();e.enemy_air_seen=True;rejected=[]
        class Rejected:
            reason='rejected'
            def __bool__(self):return False
        g.train=lambda b,c:rejected.append(c) or Rejected()
        for now in range(0,30,4):e.research_web(g,now)
        self.assertEqual(len(rejected),3)
        self.assertFalse(e.web_reserving)

    def test_web_effect_requires_actual_buff_not_research_receipt(self):
        events=[];buffs=[]
        g=N(me=lambda:0,buffs=lambda u:buffs)
        b=Controller(g,lambda event,**kw:events.append(event));b.economy.web_level=1
        enemy=unit('hgry',7)
        b.observe_air([enemy],1)
        self.assertNotIn('web_effect_observed',events)
        buffs.append('Bweb');b.observe_air([enemy],4)
        self.assertIn('web_effect_observed',events)

if __name__=='__main__':unittest.main()
