import bootstrap
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from test_micro_loot import dist
from undead.controller import Controller


class PortalAssemblyTests(unittest.TestCase):
    def make(self):
        data=json.loads((Path(__file__).parent/'fixtures/az-portal-drift-0191.json').read_text(encoding='utf-8'))
        army=[N(**dict(r,handle=tuple(r['handle']))) for r in data['frame']['army']]
        foes=[N(**dict(r,handle=tuple(r['handle']))) for r in data['frame']['enemies']]
        held=[];moving=[];fighting=[];events=[]
        g=N(dist=dist,unit=lambda h:next((u for u in army if u.handle==h),None),
            hold=lambda u:held.append(u.handle) or True)
        b=Controller(g,lambda ev,**kw:events.append(dict(event=ev,**kw)))
        caster=next(u for u in army if u.type=='Ulic')
        b.teleport=dict(hero=caster.handle,started=937.105);b.battle_enemies=foes
        b.go_raw=lambda units,p,t:moving.extend(u.handle for u in units)
        b.fight=lambda units,enemies,t:fighting.extend(u.handle for u in units)
        return b,army,caster,held,moving,fighting,events

    def test_real_nearby_heroes_cancel_escape_movement_during_channel(self):
        b,army,caster,held,moving,fighting,events=self.make()
        b.protect_portal_allies(army,{},937.105)
        for code in ('Udea','Nngs'):
            h=next(u for u in army if u.type==code)
            self.assertIn(h.handle,held)
            self.assertNotIn(h.handle,fighting)
        self.assertNotIn(caster.handle,held)
        self.assertTrue(events)

    def test_wounded_pulling_or_active_cast_allies_are_never_held(self):
        b,army,caster,held,moving,fighting,events=self.make()
        dk=next(u for u in army if u.type=='Udea');naga=next(u for u in army if u.type=='Nngs')
        b.cast_until[naga.handle]=940
        b.protect_portal_allies(army,{dk.handle:(0,0)},938)
        self.assertIn(dk.handle,moving);self.assertNotIn(dk.handle,held)
        self.assertNotIn(naga.handle,held);self.assertNotIn(naga.handle,fighting)

    def test_outside_portal_and_directly_threatened_allies_keep_original_micro(self):
        b,army,caster,held,moving,fighting,events=self.make()
        dk=next(u for u in army if u.type=='Udea');naga=next(u for u in army if u.type=='Nngs')
        dk.x=caster.x+1200
        b.battle_enemies=[N(type='hfoo',hp=500,x=naga.x,y=naga.y)]
        b.protect_portal_allies(army,{},938)
        self.assertNotIn(dk.handle,held);self.assertNotIn(naga.handle,held)
        self.assertIn(dk.handle,fighting);self.assertIn(naga.handle,fighting)

    def test_handoff_and_missing_caster_do_not_freeze_allies(self):
        for missing in (False,True):
            b,army,caster,held,moving,fighting,events=self.make()
            if missing:b.g.unit=lambda h:None
            else:b.teleport=None;b.portal_handoff=dict(donor=caster.handle)
            b.protect_portal_allies(army,{},938)
            self.assertFalse(held)
            self.assertNotIn(caster.handle,fighting)

    def test_repeated_tick_does_not_spam_hold(self):
        b,army,caster,held,moving,fighting,events=self.make()
        b.protect_portal_allies(army,{},938);first=list(held)
        b.protect_portal_allies(army,{},938.1)
        self.assertTrue(first);self.assertEqual(held,first)


if __name__=='__main__':unittest.main()
