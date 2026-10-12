import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.controller import Controller,ground_attack_range
from undead.economy import Economy
from undead.policy import Action
from undead.retreat import escape_point,clearance
from test_micro_loot import unit,dist
from test_upgrades_portal import UpgradeGame
import test_combat_focus as focus


class RetreatTests(unittest.TestCase):
    def archived(self):
        data=json.loads((Path(__file__).parent/'fixtures/base-retreat-232932.json').read_text())
        def convert(r,owner):
            v=dict(r);v['handle']=tuple(v['handle']);v['owner']=owner;v['is_hero']=v['type'][0].isupper()
            return N(**v)
        army=[convert(r,0) for r in data['frame']['army']]
        enemies=[convert(r,1) for r in data['frame']['enemies']];moves=[];holds=[]
        g=N(dist=dist,enemies=lambda:enemies,map=lambda:N(walkable=lambda *p:True),
            path_distance=dist,walk_path=lambda a,b:[b],hold=lambda u:holds.append(u.handle) or True,
            move=lambda u,x,y:moves.append((u.handle,(x,y))) or True)
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=data['home'][0],y=data['home'][1])
        b.action=Action.RETREAT;b.emergency_portal=lambda *a:False
        b.go=lambda units,p,now,**kw:moves.extend((u.handle,p) for u in units)
        return b,army,enemies,moves,holds

    def test_archived_dk_escapes_instead_of_returning_to_occupied_home(self):
        b,army,enemies,moves,holds=self.archived()
        dk=next(u for u in army if u.type=='Udea')
        b.collective_retreat(army,438.55)
        point=next(p for h,p in moves if h==dk.handle)
        self.assertNotEqual(point,(b.home.x,b.home.y))
        self.assertGreater(clearance(point,enemies,ground_attack_range),
                           clearance((dk.x,dk.y),enemies,ground_attack_range)+80)

    def test_safe_reinforcement_stays_out_of_the_besieged_base(self):
        b,army,enemies,moves,holds=self.archived()
        u=unit('ucry',999,-5184);u.y=800
        b.collective_retreat([u],438.55)
        self.assertFalse(moves);self.assertEqual(holds,[u.handle])

    def test_unreachable_or_dangerous_routes_do_not_issue_a_suicidal_move(self):
        for mode in ('unreachable','cross_enemy','no_grid'):
            with self.subTest(mode=mode):
                b,army,enemies,moves,holds=self.archived();g=b.g
                dk=next(u for u in army if u.type=='Udea')
                if mode=='unreachable':g.path_distance=lambda *a:None
                elif mode=='no_grid':g.map=lambda:None
                else:g.walk_path=lambda a,p:[(enemies[1].x,enemies[1].y),p]
                self.assertIsNone(escape_point(g,dk,enemies,ground_attack_range))
                b.collective_retreat([dk],440)
                self.assertFalse(moves);self.assertIn(dk.handle,holds)

    def test_protected_cast_and_lightning_shield_keep_priority(self):
        b,army,enemies,moves,holds=self.archived();dk=next(u for u in army if u.type=='Udea')
        b.cast_until[dk.handle]=500;b.collective_retreat([dk],440)
        self.assertFalse(moves);self.assertFalse(holds)
        b.cast_until.clear();b.shield_moves[dk.handle]=(-6000,2000)
        b.collective_retreat([dk],442);self.assertEqual(moves,[(dk.handle,(-6000,2000))])

    def test_safe_home_and_emergency_portal_keep_existing_behavior(self):
        b,army,enemies,moves,holds=self.archived();b.home=N(x=0,y=0)
        b.collective_retreat(army,440)
        self.assertTrue(moves);self.assertTrue(all(p==(0,0) for _,p in moves))
        moves.clear();b.emergency_portal=lambda *a:True;b.collective_retreat(army,442)
        self.assertFalse(moves)

    def test_escape_planning_is_throttled(self):
        b,army,enemies,moves,holds=self.archived()
        b.collective_retreat(army,440);count=len(moves)+len(holds)
        b.collective_retreat(army,440.5)
        self.assertEqual(len(moves)+len(holds),count)


class SustainTests(unittest.TestCase):
    def economy(self):
        g=UpgradeGame();g.own[0].type='unp1'
        g.own=[u for u in g.own if u.type not in {'uobs','Nbrn'}];g.food=30
        e=Economy(lambda *a,**kw:None);e.ever_heroes={'Udea','Ulic'}
        return g,e

    def test_tier_three_can_start_before_first_statue_then_sustain_continues(self):
        g,e=self.economy();e.tick(g,327)
        self.assertEqual(g.commands,['unp2'])
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'])
        e.tick(g,329);self.assertEqual(g.commands,['unp2','uobs'])

    def test_slaughterhouse_construction_releases_tier_three(self):
        g,e=self.economy();slaughter=g.my_buildings({'uslh'})[0]
        g.busy[slaughter.handle]=N(kind='construction',queue=['uslh'])
        e.tick(g,327);self.assertEqual(g.commands,['unp2'])

    def test_insufficient_resources_cannot_start_either_purchase(self):
        g,e=self.economy();g.gold=100;g.can_do=lambda b,code:8
        e.tick(g,327);self.assertFalse(g.commands)

    def test_missing_slaughterhouse_is_built_even_without_visible_raid(self):
        g,e=self.economy();g.own=[u for u in g.own if u.type!='uslh'];built=[]
        e.build=lambda g,code,home,now:built.append(code) or True
        e.tick(g,327);self.assertEqual(built,['uslh']);self.assertFalse(g.commands)

    def fight(self,mana,hurt=False):
        b,f,d,s,h,target,own,foes,commands,targets,events=focus.CombatFocusTests().make()
        d.mana=mana;target.owner=15;target.type='ngna';target.hp=500
        if hurt:f.hp=100
        casts=[];b.g.cast=lambda u,order,**kw:casts.append(order) or True
        b.skeleton_opening=lambda *a:False;b.fight(own,[target],10)
        return b,f,d,own,casts

    def test_neutral_creep_damage_keeps_one_coil_in_reserve(self):
        for mana,expected in ((75,False),(116.54,False),(149,False),(150,True),(255,True)):
            with self.subTest(mana=mana):
                *_,casts=self.fight(mana)
                self.assertEqual('deathcoil' in casts,expected)

    def test_reserved_mana_remains_available_for_healing(self):
        b,f,d,own,casts=self.fight(75,hurt=True)
        self.assertFalse(casts)
        b.heal_allies(own,12)
        self.assertEqual(casts,['deathcoil'])
