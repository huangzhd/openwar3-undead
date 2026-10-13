import unittest
import json
from pathlib import Path
from types import SimpleNamespace as N
import bootstrap
from undead.economy import Economy
from test_baseline import FakeGame,unit
from test_micro_loot import dist


class HallRebuildTests(unittest.TestCase):
    def make(self):
        g=FakeGame(tier=3,gold=1101);events=[];calls=[]
        e=Economy(lambda event,**kw:events.append(dict(event=event,**kw)))
        home=g.my_buildings({'unp2'})[0]
        g.dist=dist;g.enemies=lambda:[];g.is_constructing=lambda u:False
        g.can_afford=lambda code:True
        g.build_near=lambda w,code,x,y,**kw:calls.append((w.handle,code,x,y)) or (x,y)
        e.hall_rebuild.observe(g,home,600)
        g.own.remove(home)
        return g,e,home,calls,events

    def test_real_ch_frame_with_five_workers_and_1111_gold_resumes_construction(self):
        data=json.loads((Path(__file__).parent/'fixtures/ch-lost-hall-0192.json').read_text(encoding='utf-8'))
        g,e,home,calls,events=self.make();frame=data['frame']
        g.own=[N(**dict(u,handle=tuple(u['handle']))) for u in frame['own']]
        g.resources=lambda:frame['resources']
        g.enemies=lambda:[N(**dict(u,handle=tuple(u['handle']))) for u in frame['enemies']]
        e.hall_rebuild.home=tuple(data['home'])
        e.tick(g,frame['clock'])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1:],('unpl',2176,4224))

    def test_missing_hall_economy_dispatches_replacement_at_observed_home(self):
        g,e,home,calls,events=self.make()
        e.tick(g,727)
        self.assertEqual(calls[0][1:],('unpl',home.x,home.y))
        self.assertNotIn('hall_rebuild_complete',[x['event'] for x in events])

    def test_threat_unknown_home_or_unaffordable_never_dispatches(self):
        for mode in ('raid','visible','unknown','funds','workers'):
            g,e,home,calls,events=self.make()
            if mode=='visible':g.enemies=lambda:[unit('earc',99,x=100)]
            elif mode=='unknown':e.hall_rebuild.home=None
            elif mode=='funds':g.can_afford=lambda code:False
            elif mode=='workers':g.own=[u for u in g.own if u.type!='uaco']
            e.tick(g,727,mode=='raid');self.assertFalse(calls,mode)

    def test_accepted_receipt_and_busy_builder_do_not_create_duplicate_halls(self):
        g,e,home,calls,events=self.make();e.tick(g,727)
        e.tick(g,728);self.assertEqual(len(calls),1)
        g.is_constructing=lambda u:True
        e.tick(g,800);self.assertEqual(len(calls),1)

    def test_rejected_orders_are_bounded_and_reserved_workers_excluded(self):
        g,e,home,calls,events=self.make()
        workers=g.units('me',{'uaco'});e.scout=workers[0].handle
        e.expansion.miners={workers[1].handle};e.repairs.tasks[workers[2].handle]={}
        g.build_near=lambda w,code,x,y,**kw:calls.append(w.handle) or None
        for now in range(727,820):e.tick(g,now)
        self.assertEqual(len(calls),3)
        self.assertTrue(all(h not in {u.handle for u in workers[:3]} for h in calls))

    def test_only_observed_full_completed_hall_confirms_rebuild(self):
        g,e,home,calls,events=self.make();e.tick(g,727)
        home.hp=home.hp_max/2;g.busy[home.handle]=N(kind='construction')
        e.hall_rebuild.observe(g,home,740)
        self.assertTrue(e.hall_rebuild.pending)
        home.hp=home.hp_max
        e.hall_rebuild.observe(g,home,760)
        self.assertTrue(e.hall_rebuild.pending)
        g.busy.pop(home.handle);e.hall_rebuild.observe(g,home,780)
        self.assertFalse(e.hall_rebuild.pending)
        self.assertEqual(sum(x['event']=='hall_rebuild_complete' for x in events),1)


if __name__=='__main__':unittest.main()
