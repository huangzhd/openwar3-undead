import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
from undead.game_view import Game,TrainingGame,SDKGame
from undead.controller import Controller


class KKManualSkillsTests(unittest.TestCase):
    def test_sdk_learning_is_blocked_only_for_attachment_mode(self):
        with patch.object(SDKGame,'learn',return_value='receipt') as learn:
            g=object.__new__(Game);g.manual_skill_learning=True
            self.assertFalse(g.learn('hero','AUdc'));learn.assert_not_called()
            for cls in (Game,TrainingGame):
                local=object.__new__(cls)
                self.assertEqual(local.learn('hero','AUdc'),'receipt')
            self.assertEqual(learn.call_count,2)

    def test_manual_points_are_observed_without_issuing_learning_commands(self):
        hero=N(type='Udea',handle=(1,2),level=1,skill_points=1)
        calls=[];events=[]
        g=N(manual_skill_learning=True,my_heroes=lambda:[hero],units=lambda *args:[],learn=lambda *args:calls.append(args))
        bot=Controller(g,lambda e,**kw:events.append(e))
        for now in (1,1.2,2):bot.skills(now)
        self.assertFalse(calls)
        self.assertEqual(bot.manual_skill_requests[0]['ability'],'AUdc')
        self.assertEqual(events.count('hero_skill_manual_required'),1)
        hero.skill_points=0;bot.skills(3)
        self.assertEqual(bot.manual_skill_requests,[])
        hero.level=2;hero.skill_points=1;bot.skills(4)
        self.assertEqual(bot.manual_skill_requests[0]['ability'],'AUau')
        self.assertFalse(calls)
