import unittest
from dataclasses import fields, MISSING
from unittest.mock import Mock, patch
import bootstrap
from w3world import Unit, WorldState, ALIVE, HERO, Ability
from undead.game_view import Game, TrainingGame, SDKGame
from training import TrainingController, unit_row
import test_banshee_link_dust_01208 as support_tests
import test_tc_pressure_01186 as pressure_tests


def record(cls, **values):
    return cls(**{f.name: values.get(f.name, 0) for f in fields(cls)
                  if f.default is MISSING and f.default_factory is MISSING},
               **{k: v for k, v in values.items() if next(f for f in fields(cls) if f.name == k).default is not MISSING
                  or next(f for f in fields(cls) if f.name == k).default_factory is not MISSING})


class TrainingIdentityTests(unittest.TestCase):
    def test_pinned_map_custom_dark_ranger_only_changes_cost_and_requirements(self):
        import struct
        from training_map import source_map, ORIGINAL
        from w3mpq import Mpq
        if not ORIGINAL.exists():self.skipTest('Pinned map is not installed')
        blob=Mpq(source_map()).read('war3map.w3u');offset=4;found=None
        def integer():
            nonlocal offset
            value=struct.unpack_from('<i',blob,offset)[0];offset+=4;return value
        def code():
            nonlocal offset
            value=blob[offset:offset+4].decode('latin1');offset+=4;return value
        for table in range(2):
            for _ in range(integer()):
                old,new=code(),code();mods={}
                for _ in range(integer()):
                    field=code();kind=integer()
                    if kind==3:
                        end=blob.index(b'\0',offset);value=blob[offset:end].decode('utf-8');offset=end+1
                    else:
                        value=struct.unpack_from('<i' if kind==0 else '<f',blob,offset)[0];offset+=4
                    code();mods[field]=value
                if new=='N001':found=(old,mods)
        self.assertEqual(offset,len(blob))
        self.assertIsNotNone(found)
        self.assertEqual(found[0],'Nbrn')
        self.assertEqual(found[1],dict(ufoo=0,ureq='',urq1='',urq2='',ugol=0,ugor=0,ulur=0,ulum=0))

    def scene(self, cls=TrainingGame):
        raw=record(Unit,type='N001',handle_lo=10,owner=0,flags=ALIVE|HERO,
                   hp=625,hp_max=625,mana=300,mana_max=300,level=4,skill_points=4,
                   has_detail=True,items=[None]*6)
        visible=record(Unit,type='N001',handle_lo=20,owner=1,flags=ALIVE|HERO,visible_mask=1)
        hidden=record(Unit,type='Obla',handle_lo=30,owner=1,flags=ALIVE|HERO)
        units=[raw,visible,hidden]
        snap=record(WorldState,me=0,clock=10,units=units,items=[],players=[],by_handle={u.handle:u for u in units})
        g=cls.__new__(cls);g.player=None;g.fair=True;g._items_in_sight=lambda *_:[]
        view=g._view(snap);g.snapshot=lambda *a,**kw:view
        return g,raw,view

    def test_alias_is_own_training_only_preserves_fairness_raw_and_fresh_lookup(self):
        g,raw,view=self.scene()
        self.assertEqual(raw.type,'N001')
        self.assertEqual([u.type for u in view.units],['Nbrn','N001'])
        hero=g.my_heroes()[0]
        self.assertEqual(hero.raw_type,'N001')
        self.assertIs(g.unit(raw.handle),hero)
        self.assertIs(g._fresh(raw),hero)
        self.assertEqual(g.units('me',{'Nbrn'}),[hero])
        self.assertIsNone(g.unit((30,0)))
        normal,_,_=self.scene(Game)
        self.assertEqual(normal.my_heroes()[0].type,'N001')

    def test_custom_hero_spends_initial_and_future_points_and_enables_black_arrow(self):
        g,raw,view=self.scene();h=g.my_heroes()[0]
        orders=[]
        def learn(hero,code):
            orders.append(code);hero.skill_points-=1
            old=next((a for a in hero.abilities if a.code==code),None)
            if old:old.level+=1
            else:hero.abilities.append(record(Ability,code=code,level=1,cooldown=0))
            return True
        g.learn=learn
        b=TrainingController(g,lambda *a,**k:None,2)
        b.army_recovery.statues=Mock()
        with patch.object(SDKGame,'cast',return_value=True) as cast:
            for now in (10,12,14,16):b.skills(now)
            self.assertEqual(orders,['ANba','ANsi','ANba','ANsi'])
            self.assertEqual(h.skill_points,0)
            h.level=5;h.skill_points=1;b.skills(20)
            self.assertEqual(orders[-1],'ANba')
            self.assertTrue(any(c.args[1]=='blackarrowon' for c in cast.call_args_list))
            self.assertEqual(g.hero_spell_level(raw,'ANsi'),2)
            self.assertTrue(g.cast(raw,'silence',x=300,y=0))
            self.assertEqual(cast.call_args.args[0].type,'Nbrn')
        row=unit_row(g,h)
        self.assertEqual((row['raw_type'],row['type'],row['skill_points']),('N001','Nbrn',0))
        self.assertEqual({a['code'] for a in row['abilities']},{'ANba','ANsi'})

    def test_normalized_custom_hero_uses_shared_silence_priority(self):
        g,raw,view=self.scene();hero=g.my_heroes()[0]
        b,fake,own,foes,orders,events,effects,dk,tc=pressure_tests.TcFirstTests().scene(TrainingController)
        index=next(i for i,u in enumerate(own) if u.type=='Nbrn')
        hero.x,hero.y=own[index].x,own[index].y;own[index]=hero
        b.combat_spells(own,foes,10)
        casts=[o for o in orders if o[0]=='cast']
        self.assertEqual(casts[0][1:3],(hero.handle,'silence'))
        self.assertIs(casts[0][3]['target'],tc)

    def test_actual_aam2_shield_uses_75_mana_and_its_own_cooldown(self):
        for mana,cd,expected in ((74,0,False),(75,0,True),(100,4,False),(100,None,False)):
            b,g,own,foes,orders,events,effects,dk,tc,ban=support_tests.BansheeLinkDustTests().scene()
            u=ban[0];u.mana=mana;own[:]=[dk,u]
            g.abilities=lambda u:[dict(code=c,level=1) for c in ('Acrs','Aam2')]
            g.cooldown=lambda u,code:cd if code=='Aam2' else 0
            b.banshee_support.tick(b,own,[],10,True)
            attempts=[d for e,d in events if e=='banshee_shell_attempt']
            self.assertEqual(bool(attempts),expected)
            if expected:
                self.assertEqual(attempts[0]['ability'],'Aam2')
                effects[dk.handle]=['Bam2'];b.banshee_support.tick(b,own,[],12,True)
                self.assertTrue(any(e=='banshee_shell_observed' for e,_ in events))

    def test_repeated_encounters_do_not_exhaust_successful_autocurse_toggles(self):
        b,g,own,foes,orders,events,effects,dk,tc,ban=support_tests.BansheeLinkDustTests().scene()
        own[:]=[ban[0]]
        for i in range(12):b.banshee_support.tick(b,own,[],10+i*3,i%2==0)
        self.assertEqual(len([o for o in orders if o[0]=='cast' and o[2] in {'curseon','curseoff'}]),12)

    def test_curse_target_beyond_weapon_range_does_not_get_interrupted_by_hold(self):
        b,g,own,foes,orders,events,effects,dk,tc,ban=support_tests.BansheeLinkDustTests().scene()
        u=ban[0];u.x=0;tc.x=650;own[:]=[u];g.current_target=lambda _:tc
        b.banshee_support.tick(b,own,foes,10,False)
        self.assertFalse(any(o[0] in {'move','hold'} for o in orders))


if __name__=='__main__':unittest.main()
