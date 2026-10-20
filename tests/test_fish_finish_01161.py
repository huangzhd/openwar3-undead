import json
import unittest
from pathlib import Path
import test_combat_focus as focus
import test_th_route_01152 as th
from test_micro_loot import unit, dist
from undead.policy import Action


class FishFinishTests(unittest.TestCase):
    def scene(self,clock=207.15):
        data=json.loads((Path(__file__).parent/'fixtures/th_002654_fish_false_clear.json').read_text(encoding='utf-8'))
        frame=next(e for e in data['events'] if e['event']=='combat_state' and abs(e['clock']-clock)<.01)
        b,*rest=focus.CombatFocusTests().make()
        own,foes,orders,targets=rest[5:9]
        own.clear();foes.clear()
        for rows,out,owner in ((frame['army'],own,0),(frame['enemies'],foes,12)):
            for r in rows:
                u=unit(r['type'],r['handle'][0],r['x'],r['hp'])
                u.handle=tuple(r['handle']);u.y=r['y'];u.owner=owner
                u.hp_max=r.get('hp_max',400);u.mana=0
                out.append(u)
        _,_,_,c=th.THRouteTests().scene()
        b.creeping=c;c.active=next(p for p in c.catalog if p['id']=='th-1')
        c.cleared={'th-8'};c.progress_at=clock
        # Bind from the visible spawn observations before the fish were dragged.
        for e in foes:
            spawn=next(s for s in c.active['spawns'] if s['code']==e.type)
            xy=e.x,e.y;e.x,e.y=spawn['x'],spawn['y']
            c.observe_drop_carriers(b.g,[e]);e.x,e.y=xy
            targets[e.handle]=own[0]
        targets[own[0].handle]=foes[0]
        b.g.creeps=lambda:foes;b.g.visible=lambda *a:True
        b.g.path_distance=dist;b.g.walk_path=lambda a,z:[z]
        b.action=Action.CREEP
        b.home=unit('unpl',50,-3904);b.home.y=2880
        b.ni_rod_stop.tick=lambda *a:False;b.ch_resummon.tick=lambda *a:False
        return b,own,foes,orders,targets

    def test_real_front_finishes_while_new_fiend_is_still_at_home(self):
        b,army,foes,orders,targets=self.scene()
        self.assertTrue(b.fight(army,foes,207.15))
        dk=next(u for u in army if u.type=='Udea')
        self.assertIs(targets[dk.handle],foes[0])
        fiend=next(u for u in army if u.type=='ucry')
        self.assertNotIn(fiend.handle,targets)

    def test_real_pulled_fish_block_clear_and_stay_in_current_goal(self):
        b,army,foes,_,_=self.scene(212.63)
        c=b.creeping;point=c.active['x'],c.active['y']
        self.assertTrue(all(dist(u,point)>700 for u in foes))
        self.assertFalse(c.observe_clear(b.g,point,213.405,foes))
        goal,remaining=c.choose(b.g,army,point,b.home,213.405)
        self.assertEqual(goal,point);self.assertEqual(remaining,foes)
        self.assertNotIn('th-1',c.cleared)

    def test_dead_fish_no_longer_block_clear(self):
        b,_,foes,_,_=self.scene(212.63)
        c=b.creeping
        for u in foes:u.hp=0
        self.assertTrue(c.observe_clear(b.g,(c.active['x'],c.active['y']),214,foes))

    def test_other_camp_distant_fish_do_not_block_or_extend_combat(self):
        b,army,foes,orders,_=self.scene(212.63)
        c=b.creeping
        for u in foes:c.drop_camps[u.handle]=-1
        self.assertTrue(c.observe_clear(b.g,(c.active['x'],c.active['y']),214,foes))
        for u in foes:u.x+=3000
        self.assertFalse(b.fight(army,foes,214))
        self.assertFalse(orders)

    def test_engaged_creep_fallback_cannot_reuse_entry_waypoint(self):
        b,army,foes,_,_=self.scene()
        c=b.creeping;b.camp_goal=(c.active['x'],c.active['y'])
        b.formation.route=[(-832,2240),(-4032,832),b.camp_goal]
        b.formation.objective=b.camp_goal
        b.skeleton_opening=lambda *a:False;b.fight=lambda *a:False
        moves=[]
        def go(a,p,now,attack=False):
            self.assertFalse(b.formation.route)
            moves.append(p)
        b.go=go;b.go_raw=lambda *a:None
        b.creep(army,(-4361,999),207.15)
        self.assertEqual(moves,[b.camp_goal])

    def test_reinforcement_moves_to_front_without_recalling_dk(self):
        b,army,foes,orders,targets=self.scene()
        moves=[];b.go_raw=lambda a,p,now:moves.extend((u.type,p) for u in a)
        b.creep(army,(-4361,999),207.15)
        self.assertEqual([typ for typ,p in moves],['ucry'])
        self.assertIs(targets[next(u.handle for u in army if u.type=='Udea')],foes[0])


if __name__=='__main__':unittest.main()
