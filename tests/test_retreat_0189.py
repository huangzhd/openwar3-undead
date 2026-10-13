import json
import unittest
from pathlib import Path
from undead.controller import Controller
from undead.policy import Action, Situation, choose_rule
import test_opening_safety_0131 as emergency


class RetreatContinuityTests(unittest.TestCase):
    def bot(self):
        return Controller(None, lambda *a, **kw: None)

    def decide(self, b, now, enemy=0, **kw):
        b.situation = Situation(now, army_hp=4000, local_enemy_hp=enemy,
            tier=3, lich=True, orb=True, third_hero=True, attack_committed=True, **kw)
        return b.retreat_rule(choose_rule(b.situation))

    def test_archived_loss_does_not_reengage_on_brief_threat_dips(self):
        b = self.bot()
        data = json.loads((Path(__file__).parent/'fixtures/lr-retreat-0188.json').read_text(encoding='utf-8'))
        for row in data['frames']:
            b.situation = Situation(row['clock'], army_hp=row['army_hp'],
                local_enemy_hp=row['enemy_hp'], army_health=row['army_health'],
                recent_losses=row['recent_losses'], attack_committed=True,
                tier=3, lich=True, orb=True, third_hero=True)
            actual = b.retreat_rule(choose_rule(b.situation))
            self.assertEqual(actual, Action.RETREAT if row['clock']>=826.755 else Action.ATTACK, row)

    def test_clear_disengagement_releases_after_continuous_safe_window(self):
        b = self.bot()
        self.assertEqual(self.decide(b, 100, 6000), Action.RETREAT)
        for t in (101, 104, 105.9):
            self.assertEqual(self.decide(b, t), Action.RETREAT)
        self.assertEqual(self.decide(b, 106), Action.ATTACK)
        self.assertEqual(self.decide(b, 107, 5000), Action.ATTACK)

    def test_threat_return_resets_safe_window_without_needing_raw_retreat(self):
        b = self.bot()
        self.decide(b, 100, 6000)
        self.decide(b, 101, 1000)
        self.assertEqual(self.decide(b, 105, 5000), Action.RETREAT)
        self.assertEqual(self.decide(b, 106, 1000), Action.RETREAT)
        self.assertEqual(self.decide(b, 110, 1000), Action.RETREAT)
        self.assertEqual(self.decide(b, 111, 1000), Action.ATTACK)

    def test_base_force_keeps_gate_but_safe_defense_can_resume(self):
        b = self.bot()
        self.decide(b, 100, 6000)
        self.assertEqual(self.decide(b, 101, threatened=True, base_enemy_hp=7000), Action.RETREAT)
        self.assertEqual(self.decide(b, 107, threatened=True, base_enemy_hp=7000), Action.RETREAT)
        self.assertEqual(self.decide(b, 108, threatened=True, base_enemy_hp=1000), Action.RETREAT)
        self.assertEqual(self.decide(b, 113, threatened=True, base_enemy_hp=1000), Action.DEFEND)

    def test_ordinary_damage_and_opening_do_not_create_new_retreat(self):
        b = self.bot()
        self.assertEqual(self.decide(b, 100, 2000, army_health=.4), Action.ATTACK)
        b.situation = Situation(101, army_hp=1000, local_enemy_hp=3000)
        self.assertEqual(b.retreat_rule(choose_rule(b.situation)), Action.RETREAT)
        self.assertEqual(self.decide(b, 102, 2000), Action.ATTACK)

    def test_full_tick_keeps_safety_above_forced_action_between_decisions(self):
        g,b,dk,allies,orders,clock = emergency.EmergencyTests().controller()
        b.attack_committed=True
        g.enemies()[0].hp=5000
        b.emergency_portal=lambda *a:True
        b.protect_portal_allies=lambda *a:None
        b.tick(forced=Action.ATTACK)
        self.assertEqual(b.action, Action.RETREAT)
        clock[0]+=1
        g.enemies()[0].hp=1100
        b.last_decide=clock[0]-6
        b.tick(forced=Action.ATTACK)
        self.assertEqual(b.action, Action.RETREAT)


if __name__=='__main__': unittest.main()
