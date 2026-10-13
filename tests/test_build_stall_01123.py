import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from undead.home_layout import HomeLayout,ENVELOPES,clear_of_buildings
import test_recovery_0153 as recovery


class BuildStallTests(unittest.TestCase):
    def test_rejections_continue_past_first_batch_and_preserve_walking_order(self):
        h=N(x=-3904,y=-3968,type='unp1');calls=[];layout=HomeLayout()
        g=N(my_buildings=lambda:[h],build_near=lambda w,c,x,y,**kw:calls.append((x,y)))
        layout.build(g,None,'uslh',h);first=set(calls);calls.clear()
        layout.build(g,None,'uslh',h);self.assertFalse(first & set(calls))
        earlier=(123,456);g.build_near=lambda *a,**kw:earlier
        cursor=dict(layout.cursors)
        self.assertEqual(layout.build(g,None,'uslh',h),earlier)
        self.assertEqual(layout.cursors,cursor)

    def test_unbuildable_ground_and_visible_tree_footprints_are_skipped(self):
        h=N(x=-3904,y=-3968,type='unp1');layout=HomeLayout()
        candidates=list(layout.candidates('uslh',h,[h]));bad,tree,good=candidates[:3];calls=[]
        g=N(my_buildings=lambda:[h],map=lambda:N(buildable=lambda x,y:(x,y)!=bad),
            visible=lambda *p:True,trees=lambda *a,**kw:[N(x=tree[0],y=tree[1])],
            build_near=lambda w,c,x,y,**kw:calls.append((x,y)) or (x,y))
        point=layout.build(g,None,'uslh',h)
        self.assertNotIn(bad,calls);self.assertNotIn(tree,calls)
        self.assertGreaterEqual(max(abs(point[0]-tree[0]),abs(point[1]-tree[1])),224)

    def test_lr_actual_buildings_have_dense_options_without_closing_lane(self):
        sample=json.loads((Path(__file__).parent/'fixtures/lr-building-stall-01123.json').read_text(encoding='utf-8'))['sample']
        buildings=[N(**r) for r in sample['own'] if r['type'] in ENVELOPES]
        home=next(u for u in buildings if u.type=='unp1')
        points=list(HomeLayout().candidates('uslh',home,buildings))
        self.assertTrue(any(max(abs(p[0]-home.x),abs(p[1]-home.y))<=768 for p in points))
        for point in points:self.assertTrue(clear_of_buildings(point,buildings,128,160))

    def test_stalled_foundation_spends_only_surplus_on_fiends_and_still_retries(self):
        g,e=recovery.SustainTests().economy();g.own=[u for u in g.own if u.type!='uslh']
        g.own=[u for u in g.own if u.type!='ucry']
        built=[];e.build=lambda game,code,home,now:built.append((code,now)) or True
        e.tick(g,400);self.assertFalse(g.commands)
        g.gold=739;g.lumber=1000;e.tick(g,411);self.assertFalse(g.commands)
        g.gold=1000;g.lumber=404;e.tick(g,414);self.assertFalse(g.commands)
        g.lumber=1000;e.tick(g,417);self.assertEqual(g.commands,['ucry'])
        e.tick(g,420);self.assertEqual(built[-1],('uslh',420))
        self.assertNotIn('unp2',g.commands)


if __name__=='__main__':unittest.main()
