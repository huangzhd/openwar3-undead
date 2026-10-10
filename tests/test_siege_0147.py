import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from undead.controller import Controller
from undead.siege import building_priority,TOWERS,HALLS
from undead.policy import Action
from openwar3.orders import REPAIR,REVIVE,ORDER,ATTACK,HARVEST

class SiegeTests(unittest.TestCase):
    def game(self):
        own=[unit('Udea',1,0),unit('Ulic',2,0),unit('ucry',3,0),unit('ucry',4,0)]
        for u in own:u.owner=0;u.mana=0
        foes=[];orders=[];current={};order_ids={};production={};events=[]
        g=N(me=lambda:0,dist=dist,enemies=lambda:foes,path_distance=dist,
            current_target=lambda u:current.get(u.handle),order_of=lambda u:order_ids.get(u.handle),
            production=lambda u:production.get(u.handle),cooldown=lambda *a:0,
            unit=lambda h:next((u for u in own+foes if u.handle==h),None),
            units=lambda side,codes:[u for u in own if u.type in codes])
        def attack(u,t,**kw):orders.append(('attack',u.handle,t.handle));current[u.handle]=t;return True
        g.attack=attack;g.move=lambda u,x,y:orders.append(('move',u.handle,(x,y))) or True
        g.hold=lambda u:orders.append(('hold',u.handle)) or True
        b=Controller(g,lambda e,**kw:events.append(dict(event=e,**kw)));b.action=Action.ATTACK
        b.home=N(x=-5000,y=0);b.enemy_main=(5000,0)
        return b,own,foes,orders,current,order_ids,production,events

    def enemy(self,code,h,x,hp=500):
        u=unit(code,h,x,hp);u.owner=1;u.mana=0;u.alive=True;u.visible_to=lambda me:True
        return u

    def test_entire_force_focuses_priority_not_low_hp_or_individual_range(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();farm=self.enemy('hhou',10,70,10);tower=self.enemy('hgtw',11,500,600);f.extend([farm,tower])
        b.fight(a,f,10)
        self.assertEqual({t for op,h,t in cmd if op=='attack'},{tower.handle})
        self.assertEqual({h for op,h,t in cmd if op=='attack'},{u.handle for u in a})
        self.assertTrue(all(cur[u.handle] is tower for u in a))

    def test_sequential_building_priorities_after_each_target_disappears(self):
        b,a,f,cmd,cur,ids,p,ev=self.game()
        chain=[self.enemy(c,10+i,200+i*20) for i,c in enumerate(['hgtw','otrb','emow','uaod','unpl','hhou'])]
        f.extend(reversed(chain));ids[chain[3].handle]=REVIVE;p[chain[3].handle]=N(kind='queue',blocked=False,duration=60,queue=['Udea'])
        for i,target in enumerate(chain):
            cmd.clear();b.fight(a,f,10+i*2)
            self.assertEqual({t for op,h,t in cmd if op=='attack'},{target.handle})
            f.remove(target)

    def test_visible_active_revive_only_idle_training_blocked_unknown_altars_stay_low(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();altar=self.enemy('halt',10,80);base=self.enemy('htow',11,200);f.extend([altar,base])
        for mode in ['idle','training','blocked','unknown','revive']:
            with self.subTest(mode=mode):
                ids[altar.handle]=REVIVE if mode in ['blocked','revive'] else None
                p[altar.handle]=None if mode in ['idle','unknown'] else N(kind='queue',blocked=mode=='blocked',duration=60,queue=['Hamg'])
                self.assertEqual(building_priority(b.g,altar),3 if mode=='revive' else 5)
                cur.clear();cmd.clear();b.fight(a,f,10+2*['idle','training','blocked','unknown','revive'].index(mode))
                self.assertEqual({t for op,h,t in cmd if op=='attack'},{altar.handle if mode=='revive' else base.handle})

    def test_each_race_repair_order_preempts_tower_and_leaving_returns_to_building(self):
        for code,order in [('hpea',REPAIR),('opeo',REPAIR),('uaco',ORDER('restoration')),('ewsp',ORDER('renew'))]:
            with self.subTest(code=code):
                b,a,f,cmd,cur,ids,p,ev=self.game();tower=self.enemy('hgtw',10,300);worker=self.enemy(code,11,350);f.extend([tower,worker])
                b.fight(a,f,10);self.assertTrue(all(cur[u.handle] is tower for u in a))
                ids[worker.handle]=order;cur[worker.handle]=tower;cmd.clear();b.fight(a,f,12)
                self.assertEqual({t for op,h,t in cmd if op=='attack'},{worker.handle})
                worker.x=1300;cmd.clear();b.fight(a,f,14)
                self.assertEqual({t for op,h,t in cmd if op=='attack'},{tower.handle})

    def test_worker_standing_nearby_autocast_or_gathering_is_not_repair(self):
        for mode in ['idle','harvest','autocast','no_target','wrong_owner','too_far','full_health']:
            b,a,f,cmd,cur,ids,p,ev=self.game();tower=self.enemy('hgtw',10,100);worker=self.enemy('hpea',11,200);f.extend([tower,worker])
            ids[worker.handle]=REPAIR;cur[worker.handle]=tower
            if mode=='idle':ids[worker.handle]=None
            if mode=='harvest':ids[worker.handle]=HARVEST
            if mode=='autocast':ids[worker.handle]=ORDER('repairon')
            if mode=='no_target':cur.pop(worker.handle)
            if mode=='wrong_owner':worker.owner=2
            if mode=='too_far':worker.x=700
            if mode=='full_health':tower.hp=tower.hp_max
            b.fight(a,f,10)
            self.assertTrue(all(cur[u.handle] is tower for u in a),mode)

    def test_defenders_suspend_siege_then_driven_away_restores_focus(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();tower=self.enemy('hgtw',10,300);soldier=self.enemy('ogru',11,80);f.extend([tower,soldier])
        b.fight(a,f,10);self.assertTrue(all(cur[u.handle] is soldier for u in a))
        soldier.x=1100;cmd.clear();b.fight(a,f,12)
        self.assertEqual({t for op,h,t in cmd if op=='attack'},{tower.handle})
        soldier.x=80;cmd.clear();b.fight(a,f,14)
        self.assertEqual({t for op,h,t in cmd if op=='attack'},{soldier.handle})

    def test_same_priority_sticks_and_higher_priority_interrupts(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();base=self.enemy('unpl',10,200);other=self.enemy('htow',11,300);f.extend([base,other])
        b.fight(a,f,10);other.x=50;other.hp=1;cmd.clear();b.fight(a,f,12)
        self.assertFalse(cmd);self.assertTrue(all(cur[u.handle] is base for u in a))
        tower=self.enemy('uzg1',12,500);f.append(tower);b.fight(a,f,14)
        self.assertTrue(all(cur[u.handle] is tower for u in a))

    def test_higher_tower_outside_siege_area_hidden_dead_or_unreachable_is_not_chased(self):
        for reason in ['far','hidden','dead','unreachable']:
            b,a,f,cmd,cur,ids,p,ev=self.game();base=self.enemy('unpl',10,50);tower=self.enemy('hgtw',11,800);f.extend([base,tower])
            if reason=='far':tower.x=2000
            if reason=='hidden':tower.visible_to=lambda me:False
            if reason=='dead':tower.hp=0;tower.alive=False
            if reason=='unreachable':b.g.path_distance=lambda x,y:None if y==(tower.x,tower.y) else dist(x,y)
            b.fight(a,f,10);self.assertTrue(all(cur[u.handle] is base for u in a),reason)

    def test_all_standard_defense_towers_and_main_halls_keep_correct_tiers(self):
        b,a,f,cmd,cur,ids,p,ev=self.game()
        for code in TOWERS:
            f[:]=[self.enemy('otrb',10,50),self.enemy(code,11,300)];cur.clear();cmd.clear()
            b.siege.target=None;b.last.clear();b.fight(a,f,10)
            self.assertTrue(all(cur[u.handle] is f[1] for u in a),code)
        for code in HALLS:
            f[:]=[self.enemy('hhou',10,50),self.enemy(code,11,300)];cur.clear();cmd.clear()
            b.siege.target=None;b.last.clear();b.fight(a,f,10)
            self.assertTrue(all(cur[u.handle] is f[1] for u in a),code)

    def test_advance_attack_does_not_overwrite_focus_with_old_site_goal(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();base=self.enemy('unpl',10,200);tower=self.enemy('hgtw',11,500);f.extend([base,tower])
        b.g.visible=lambda *p:False;b.memory.update(f,1,0,lambda u:True);b.attack_target=base.handle
        b.go=lambda *args,**kw:self.fail('Shared siege must not march back to the remembered base')
        b.advance_attack(a,f,(0,0),10)
        self.assertTrue(all(cur[u.handle] is tower for u in a))

    def test_protected_units_and_statues_not_attacked_and_late_units_rejoin(self):
        b,a,f,cmd,cur,ids,p,ev=self.game();f.append(self.enemy('hgtw',10,500))
        b.cast_until[a[0].handle]=20;b.shield_moves[a[1].handle]=(0,0)
        statue=unit('uobs',5,-800);late=unit('ucry',6,-2500);a.extend([statue,late])
        b.focus_siege(a,f,10)
        self.assertFalse(any(op=='attack' and h in {a[0].handle,a[1].handle,statue.handle,late.handle} for op,h,t in cmd))
        self.assertTrue(any(op=='move' and h==late.handle for op,h,t in cmd))
        self.assertTrue(any(op=='move' and h==statue.handle for op,h,t in cmd))

    def test_defend_retreat_and_creeping_do_not_enable_siege(self):
        for action in [Action.DEFEND,Action.RETREAT,Action.CREEP]:
            b,a,f,cmd,cur,ids,p,ev=self.game();b.action=action;f.append(self.enemy('hgtw',10,300))
            self.assertFalse(b.focus_siege(a,f,10));self.assertFalse(cmd)
