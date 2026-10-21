import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller


class DarkRangerTests(unittest.TestCase):
    def test_autocast_waits_for_learning_and_reenables_after_revive(self):
        hero=unit('Nbrn',1,0);hero.skill_points=0
        own=[hero];abilities=[];casts=[]
        g=N(my_heroes=lambda:own,units=lambda *a:[],abilities=lambda h:abilities,
            cast=lambda h,spell:casts.append(spell) or True)
        bot=Controller(g,lambda *a,**k:None)
        bot.skills(1)
        self.assertFalse(casts)
        abilities.append(dict(code='ANba',level=1))
        bot.skills(2);bot.skills(10)
        self.assertEqual(casts,['blackarrowon'])
        own.clear();bot.skills(12);own.append(hero);bot.skills(20)
        self.assertEqual(casts,['blackarrowon','blackarrowon'])

    def test_rejected_autocast_stops_after_three_attempts(self):
        hero=unit('Nbrn',1,0);hero.skill_points=0
        casts=[]
        g=N(my_heroes=lambda:[hero],units=lambda *a:[],abilities=lambda h:[dict(code='ANba',level=1)],
            cast=lambda h,spell:casts.append(spell) and False)
        bot=Controller(g,lambda *a,**k:None)
        for now in range(0,50):bot.skills(now)
        self.assertEqual(len(casts),3)
        self.assertFalse(bot.black_arrow_enabled)


class SkeletonOpeningTests(unittest.TestCase):
    def setup_fight(self):
        dk=unit('Udea',1,0);skeleton=unit('uske',2,100);enemy=unit('nmrl',3,500);enemy.owner=12
        attacks=[];holds=[];targets={};events=[]
        g=N(dist=dist,current_target=lambda e:targets.get(e.handle),
            attack=lambda u,t:attacks.append((u.handle,t.handle)) or True,
            hold=lambda u:holds.append(u.handle) or True)
        return Controller(g,lambda e,**k:events.append(e)),dk,skeleton,enemy,attacks,holds,targets,events

    def test_skeleton_starts_then_main_army_fights_after_first_damage(self):
        b,dk,sk,e,attacks,holds,targets,events=self.setup_fight()
        self.assertTrue(b.skeleton_opening([dk,sk],[e],1))
        self.assertEqual(attacks,[(sk.handle,e.handle)])
        self.assertEqual(holds,[dk.handle])
        targets[e.handle]=sk
        self.assertTrue(b.skeleton_opening([dk,sk],[e],1.5))
        e.hp-=12
        self.assertFalse(b.skeleton_opening([dk,sk],[e],1.5))
        self.assertIn('skeleton_tank_observed',events)

    def test_opening_is_bounded_and_not_repeated_for_same_camp(self):
        b,dk,sk,e,attacks,holds,targets,events=self.setup_fight()
        self.assertTrue(b.skeleton_opening([dk,sk],[e],1))
        self.assertFalse(b.skeleton_opening([dk,sk],[e],4))
        self.assertFalse(b.skeleton_opening([dk,sk],[e],20))
        self.assertEqual(attacks,[(sk.handle,e.handle)])

    def test_player_combat_and_missing_skeleton_never_wait(self):
        b,dk,sk,e,*_=self.setup_fight()
        self.assertFalse(b.skeleton_opening([dk],[e],1))
        e.owner=1
        self.assertFalse(b.skeleton_opening([dk,sk],[e],2))
        e.owner=12;b.attack_committed=True
        self.assertFalse(b.skeleton_opening([dk,sk],[e],3))
