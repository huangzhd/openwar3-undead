import json
import unittest
from pathlib import Path
import test_tp_escort_01104 as prior
from test_micro_loot import unit
from undead.policy import Action


class LifetimeTavernReturnsTests(unittest.TestCase):
    def replay_returns(self):
        b,a,shops,m,buys,ev,res=prior.TavernEscortTests().make()
        rows=json.loads((Path(__file__).parent/'fixtures/al-tavern-lifetime-01128.json').read_text(encoding='utf-8'))['returns']
        self.assertEqual([r['reason'] for r in rows],['lifetime_insufficient','travel_timeout','travel_timeout'])
        skeleton=unit('uske',88,-2000);a.append(skeleton)
        b.skeleton_expiry[skeleton.handle]=100
        b.recruit_tavern(a,[],10,3,set())
        self.assertEqual(b.tavern_mission['courier'],skeleton.handle)
        b.skeleton_expiry[skeleton.handle]=12
        b.recruit_tavern(a,[],11,3,set())
        a.remove(skeleton)
        for start in (50,110):
            b.recruit_tavern(a,[],start,3,set())
            b.recruit_tavern(a,[],start+26,3,set())
        self.assertEqual([e['reason'] for e in ev if e['event']=='tavern_dispatch_end'],[r['reason'] for r in rows])
        self.assertIsNone(b.tavern_mission)
        self.assertFalse(b.tavern_joiners)
        m.clear()
        return b,a,m,buys

    def test_exhausted_lifetime_and_stall_sequence_unlocks_visible_bounded_hire(self):
        b,a,m,buys=self.replay_returns()
        self.assertTrue(b.escort_tavern(a,[],140,3))
        self.assertEqual({h for h,p in m},{u.handle for u in a})
        for u in a:u.x=0
        self.assertTrue(b.escort_tavern(a,[],145,3))
        self.assertEqual(buys,['Nbrn'])
        self.assertFalse(b.situation.third_hero)

    def test_lifetime_sequence_preserves_defense_returning_and_path_guards(self):
        for guard in ('defense','returning','path'):
            b,a,m,buys=self.replay_returns()
            if guard=='defense':b.action=Action.DEFEND
            elif guard=='returning':b.tavern_joiners.add(a[-1].handle)
            else:b.g.path_distance=lambda *args:None
            self.assertFalse(b.escort_tavern(a,[],140,3))
            self.assertFalse(m);self.assertFalse(buys)

    def test_lifetime_fallback_stops_after_one_stalled_escort(self):
        b,a,m,buys=self.replay_returns()
        self.assertTrue(b.escort_tavern(a,[],140,3))
        self.assertFalse(b.escort_tavern(a,[],171,3))
        self.assertFalse(b.escort_tavern(a,[],200,3))
        self.assertTrue(b.tavern_escort_done)
