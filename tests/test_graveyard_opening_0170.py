import json,unittest
from pathlib import Path
from types import SimpleNamespace as N
import test_scout_opening as opening
from test_micro_loot import unit
from undead.creeping import Creeping

class GraveyardOpeningTests(unittest.TestCase):
    def make(self):
        parts=opening.ScoutCorpseTests().make()
        b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        yard=unit('ugrv',90,-1850,900);yard.hp_max=900;yard.owner=0;yard.alive=True
        g.my_buildings=lambda codes:[yard] if 'ugrv' in codes else []
        g.production=lambda u:None
        b.graveyard_ready_at=130
        return parts,yard

    def add_skeletons(self,parts):
        b,g,dk,corpse,own,all_units,*_=parts
        for i in (80,81):
            u=unit('uske',i,dk.x,180);u.hp_max=180;u.alive=True;u.owner=0;u.y=dk.y
            all_units.append(u)
        return g.units('me',{'Udea','uske'})

    def test_scout_corpse_precedes_graveyard_and_requires_real_skeletons(self):
        parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        b.scout_corpse=dict(handle=corpse.handle,point=(-1000,0),clock=140)
        b.creep([dk],(dk.x,dk.y),150)
        self.assertEqual(orders,[('move',[dk.handle],(-1000,0))])
        self.assertFalse(b.opening_rod_finished)
        dk.x=-1200;b.creep([dk],(dk.x,dk.y),152)
        self.assertEqual(orders[-1],('rod',dk.handle))
        self.add_skeletons(parts)
        self.assertFalse(b.use_scout_corpse([dk],dk,155))
        self.assertTrue(b.opening_rod_finished)
        self.assertEqual(events[-1]['fiends'],0)
        self.assertFalse(b.use_graveyard_corpse([dk],dk,156))

    def test_expired_scout_corpse_falls_back_to_graveyard(self):
        parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        b.scout_corpse=dict(handle=corpse.handle,point=(-1000,0),clock=50)
        b.creep([dk],(dk.x,dk.y),150)
        self.assertTrue(b.scout_corpse_abandoned)
        self.assertFalse(b.opening_rod_finished)
        self.assertEqual(orders,[('rod',dk.handle)])
        self.assertEqual(events[-1]['event'],'opening_graveyard_rod_attempt')

    def test_new_opening_waits_for_rod_instead_of_selecting_camp(self):
        parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        b.economy.opening_started=True;inv.clear()
        b.creeping.choose=lambda *a:(_ for _ in ()).throw(AssertionError('premature camp'))
        b.creep([dk],(dk.x,dk.y),120)
        self.assertEqual(orders,[('move',[dk.handle],(b.home.x,b.home.y))])

    def test_construction_and_cooldown_wait_without_spending_rod(self):
        parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        b.graveyard_ready_at=None
        g.production=lambda u:N(kind='construction')
        self.assertTrue(b.use_graveyard_corpse([dk],dk,150));self.assertFalse(orders)
        g.production=lambda u:None;cool[0]=10
        self.assertTrue(b.use_graveyard_corpse([dk],dk,154));self.assertFalse(orders)
        cool[0]=0;b.use_graveyard_corpse([dk],dk,158)
        self.assertFalse(orders)
        b.use_graveyard_corpse([dk],dk,170)
        self.assertIn(('rod',dk.handle),orders)

    def test_approach_and_cast_protection_and_bounded_failed_summons(self):
        parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
        dk.x=-2600;b.use_graveyard_corpse([dk],dk,140)
        self.assertEqual(orders[-1][2],(yard.x,yard.y));dk.x=-2000
        for t in (145,160,175):b.use_graveyard_corpse([dk],dk,t)
        self.assertEqual(sum(o[0]=='rod' for o in orders),3)
        self.assertFalse(b.use_graveyard_corpse([dk],dk,178));self.assertTrue(b.graveyard_rod_abandoned)
        self.assertFalse(b.opening_rod_finished)
        parts,yard=self.make();b,g,dk,*rest=parts;b.cast_until[dk.handle]=155
        self.assertTrue(b.use_graveyard_corpse([dk],dk,150));self.assertFalse(parts[6])

    def test_threat_pulling_or_unsafe_path_cannot_force_opening(self):
        for cause in ('threat','pull','route','timeout'):
            with self.subTest(cause=cause):
                parts,yard=self.make();b,g,dk,corpse,own,all_units,orders,events,inv,cool=parts
                if cause=='threat':b.battle_enemies=[corpse]
                elif cause=='pull':b.micro.pulling.add(dk.handle)
                elif cause=='route':g.path_distance=lambda *a:None
                else:b.graveyard_rod_started=50
                self.assertFalse(b.use_graveyard_corpse([dk],dk,150));self.assertFalse(orders)

    def test_real_lr_first_camp_before_fiend_for_both_starts(self):
        catalog=json.loads((Path(__file__).parents[1]/'data/kk_map_pool.json').read_text(encoding='utf-8'))['LR']
        for x,y,expected in ((-3904,-3968,'lr-6'),(3840,3328,'lr-15')):
            with self.subTest(start=(x,y)):
                parts,yard=self.make();b,g,dk,*_=parts;dk.x=x;dk.y=y;b.home=N(x=x,y=y)
                army=self.add_skeletons(parts)
                g.map=lambda:N(starts=[(-3904,-3968),(3840,3328)])
                c=Creeping(lambda *a,**k:None,catalog['camps']);c.opening_gnoll=True
                goal,_=c.choose(g,army,(x,y),b.home,180)
                self.assertIsNotNone(goal);self.assertEqual(c.active['id'],expected)
                self.assertFalse(any(u.type=='ucry' for u in army))
                c=Creeping(lambda *a,**k:None,catalog['camps']);c.opening_gnoll=True;dk.hp=300
                self.assertFalse(c.candidates(g,army,b.home,180))

if __name__=='__main__':unittest.main()
