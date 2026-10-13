import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import bootstrap
from undead.formation import Formation, distance
from openwar3.pathing import Grid


class RetreatJoinerTests(unittest.TestCase):
    def replay(self, path):
        data=json.loads((Path(__file__).parent/'fixtures/lr-retreat-joiner-0189.json').read_text(encoding='utf-8'))
        f=Formation(lambda *a,**kw:None)
        previous=set()
        for frame in data['frames']:
            army=[N(**{k:v for k,v in row.items() if k in ('type','x','y')},
                    handle=tuple(row['handle']),is_hero=row['type'][0].isupper()) for row in frame['army']]
            orders=f.plan(army,tuple(data['home']),frame['clock'],distance,path,retreat=True)
            added=[order for order in orders if previous and order[0].handle not in previous]
            previous={u.handle for u in army}
        return f,added,tuple(data['home'])

    def test_archived_home_side_reinforcement_moves_home_not_to_enemy_side_anchor(self):
        f,added,home=self.replay(lambda a,b:[b])
        self.assertEqual(len(added),1)
        obj,point,hold=added[0]
        self.assertGreater(distance((obj.x,obj.y),f.anchor),2000)
        self.assertEqual(point,home)
        self.assertFalse(hold)

    def test_joiner_without_own_escape_path_holds_instead_of_following_frontline(self):
        def path(a,b):return None if a==(-3160,-3204) else [b]
        f,added,home=self.replay(path)
        obj,point,hold=added[0]
        self.assertEqual(point,(obj.x,obj.y));self.assertTrue(hold)

    def test_retreat_joiner_follows_real_terrain_turn_instead_of_direct_wall_crossing(self):
        grid=Grid(30,30,100,0,0,bytearray(900))
        for row in range(23):grid.blocked[row*30+10]=1
        main=[N(type='ucry',x=250,y=250+i*80,handle=(i,0),is_hero=False) for i in range(3)]
        f=Formation(lambda *a,**kw:None);home=(450,250)
        f.plan(main,home,0,grid.distance,grid.path,retreat=True)
        joiner=N(type='ucry',x=1450,y=250,handle=(9,0),is_hero=False)
        turns=grid.path((joiner.x,joiner.y),home)
        orders=f.plan(main+[joiner],home,2,grid.distance,grid.path,retreat=True)
        point=next(p for u,p,hold in orders if u is joiner)
        self.assertIn(point,turns)
        self.assertNotEqual(point,home)
        self.assertGreater(point[0],1000)
        self.assertTrue(any(y>2000 for x,y in turns))

    def test_normal_advance_still_joins_main_body(self):
        f=Formation(lambda *a,**kw:None)
        main=[N(type='ucry',x=0,y=i*30,handle=(i,0),is_hero=False) for i in range(3)]
        path=lambda a,b:[b]
        f.plan(main,(3000,0),0,distance,path)
        joiner=N(type='ucry',x=-3000,y=0,handle=(9,0),is_hero=False)
        orders=f.plan(main+[joiner],(3000,0),2,distance,path)
        self.assertEqual(next(p for u,p,hold in orders if u is joiner),f.anchor)


if __name__=='__main__':unittest.main()
