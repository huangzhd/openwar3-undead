import json
import unittest
from pathlib import Path
import test_tp_escort_01104 as prior
from undead.policy import Action


class MixedTavernReturnsTests(unittest.TestCase):
    def mixed_returns(self):
        b,a,shops,m,buys,ev,res=prior.TavernEscortTests().make()
        fixture=json.loads((Path(__file__).parent/'fixtures/al-tavern-mixed-returns-01126.json').read_text(encoding='utf-8'))
        self.assertEqual([r['reason'] for r in fixture['returns']],['unsafe','unsafe','travel_timeout'])
        for start,row in zip((10,),fixture['returns']):
            b.recruit_tavern(a,[],start,3,set())
            handle=b.tavern_mission['courier']
            if row['reason']=='unsafe':b.recruit_tavern(a,[],start+1,3,{handle})
            else:b.recruit_tavern(a,[],start+26,3,set())
        self.assertIsNone(b.tavern_mission)
        self.assertFalse(b.tavern_joiners)
        return b,a,shops,m,buys,ev,res

    def test_al_mixed_returns_unlock_bounded_escort_and_visible_purchase(self):
        b,a,shops,m,buys,ev,res=self.mixed_returns()
        m.clear()
        self.assertTrue(b.escort_tavern(a,[],120,3))
        self.assertEqual({h for h,p in m},{u.handle for u in a})
        self.assertFalse(buys)
        for u in a:u.x=0
        self.assertTrue(b.escort_tavern(a,[],130,3))
        self.assertEqual(buys,['Nbrn'])
        self.assertFalse(b.situation.third_hero)

    def test_mixed_returns_still_obey_defense_and_path_guards(self):
        for reason in ('defend','path'):
            b,a,shops,m,buys,ev,res=self.mixed_returns();m.clear()
            if reason=='defend':b.action=Action.DEFEND
            elif reason=='path':b.g.path_distance=lambda *args:None
            else:b.tavern_joiners.add(a[-1].handle)
            self.assertFalse(b.escort_tavern(a,[],120,3))
            self.assertFalse(m);self.assertFalse(buys)

    def test_mixed_fallback_cannot_repeat_after_stalling(self):
        b,a,shops,m,buys,ev,res=self.mixed_returns()
        self.assertTrue(b.escort_tavern(a,[],120,3))
        self.assertFalse(b.escort_tavern(a,[],151,3))
        self.assertTrue(b.escort_tavern(a,[],200,3))
        self.assertFalse(b.tavern_escort_done)


if __name__=='__main__':unittest.main()
