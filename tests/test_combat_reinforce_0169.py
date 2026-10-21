import unittest
import test_combat_focus as focus
import test_consumables as consumables
from test_micro_loot import unit,dist
from undead.consumables import Consumables
from undead.policy import Action

class ReinforceTests(unittest.TestCase):
    def make(self):
        b,f,dk,s,h,e,own,foes,orders,targets,events=focus.CombatFocusTests().make()
        foes[:]=[e];e.x=1400;e.hp=1000
        lich=unit('Ulic',30,1000);lich.owner=0;lich.mana=0
        front=unit('ucry',31,950);front.owner=0
        statue=unit('uobs',32,0);statue.owner=0
        own.extend([lich,front,statue]);b.action=Action.ATTACK;b.player_contact=[e]
        b.g.path_distance=dist;b.g.walk_path=lambda start,end:[end]
        b.g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        return b,own,foes,orders,targets,events

    def test_rear_advances_and_front_keeps_firing_outside_old_anchor_limit(self):
        b,own,foes,orders,targets,events=self.make()
        b.respond_player_contact(own,10)
        moved={o[1]:o[2] for o in orders if o[0]=='move'}
        for u in (own[0],own[1]):
            self.assertIn(u.handle,moved)
            self.assertLess(dist(moved[u.handle],own[2]),dist(u,own[2]))
        self.assertNotIn(own[4].handle,moved) # Dedicated statue support owns its movement.
        for u in own[2:4]:
            self.assertNotIn(u.handle,moved);self.assertIs(targets[u.handle],foes[0])
        orders.clear();b.respond_player_contact(own,13)
        self.assertFalse(any(o[0]=='hold' and o[1] in {u.handle for u in own[2:4]} for o in orders))

    def test_protected_casters_and_pulling_units_are_not_recalled(self):
        b,own,foes,orders,targets,events=self.make()
        b.micro.pulling.add(own[0].handle);b.cast_until[own[1].handle]=20
        b.shield_moves[own[4].handle]=(-500,0)
        b.respond_player_contact(own,10)
        protected={own[i].handle for i in (0,1,4)}
        self.assertFalse(any(o[1] in protected for o in orders))
        self.assertIs(targets[own[2].handle],foes[0])

    def test_support_in_position_stays_and_no_enemy_hero_chase(self):
        b,own,foes,orders,targets,events=self.make()
        own[1].x=750;own[4].x=750
        b.respond_player_contact(own,10)
        self.assertFalse(any(o[0]=='move' and o[1] in {own[1].handle,own[4].handle} for o in orders))
        b,own,foes,orders,targets,events=self.make()
        foe=unit('Udea',90,2000);foe.owner=1;b.player_contact=[foe]
        b.respond_player_contact(own,10)
        self.assertFalse(any(o[0]=='attack' for o in orders))
        self.assertTrue(all(o[2][0]<=1000 for o in orders if o[0]=='move'))

    def test_no_one_in_range_closes_on_ordinary_enemy(self):
        b,own,foes,orders,targets,events=self.make();foes[0].x=1650
        b.respond_player_contact(own,10)
        moved={o[1]:o[2] for o in orders if o[0]=='move'}
        self.assertIn(own[2].handle,moved)
        self.assertLess(moved[own[2].handle][0],own[2].x) # forward hero rejoins DK before advancing
        self.assertLess(moved[own[2].handle][0],foes[0].x)

class DeathBookTests(unittest.TestCase):
    def test_neutrals_friendly_unknown_dead_and_distant_enemies_keep_book(self):
        for owner,code,x,hp in [(12,'nogr',200,500),(0,'ucry',200,500),(15,'hfoo',200,500),(1,'hfoo',200,0),(1,'hfoo',900,500)]:
            with self.subTest(owner=owner,code=code,x=x,hp=hp):
                g=consumables.Game();h=g.heroes[0];h.hp=500;g.bags[h.handle][0]='fgsk'
                g.units=lambda side,codes:[]
                foe=unit(code,90,x,hp);foe.owner=owner
                Consumables(lambda *a,**k:None).tick(g,g.army,[foe],1,{},attacking=True)
                self.assertFalse(g.orders);self.assertEqual(g.bags[h.handle][0],'fgsk')

    def test_actual_player_contact_uses_book_even_while_defending(self):
        g=consumables.Game();h=g.heroes[0];h.hp=500;g.bags[h.handle][0]='fgsk'
        g.units=lambda side,codes:[]
        foe=unit('ucry',90,200);foe.owner=1
        creep=unit('nogr',91,50);creep.owner=12
        Consumables(lambda *a,**k:None).tick(g,g.army,[creep,foe],1,{})
        self.assertEqual(g.orders,[('use','Udea','fgsk')])

if __name__=='__main__':unittest.main()
