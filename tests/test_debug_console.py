import unittest
from types import SimpleNamespace as N
from undead.debug_console import ActionMeter,DebugConsole
from undead.controller import Controller
from undead.policy import Action
from test_speed_control import FakeUI
from test_micro_loot import dist
from test_baseline import unit
import test_opening_safety_0131 as safety


class MeterTests(unittest.TestCase):
    def game(self):
        self.now=0;self.wall=0;self.sent=[]
        def commands(calls,*args,**kw):
            self.sent.extend(calls)
            return [N(ok=getattr(c,'accepted',True)) for c in calls]
        names=('point','target','immediate','build','learn','use_item','revive','rally','buy','item_drop')
        return N(clock=lambda:self.now,lane=N(commands=commands),_w3fast=N(OP={n:i+1 for i,n in enumerate(names)}))

    def test_accepted_batch_members_count_once_queries_and_failures_never_count(self):
        g=self.game();meter=ActionMeter(g);self.now=10
        calls=[N(op=1),N(op=2),N(op=3,accepted=False),N(op=22),N(op=73),N(op=40),N(op=9)]
        receipts=g.lane.commands(calls,timeout=.8)
        self.assertEqual(self.sent,calls);self.assertEqual([r.ok for r in receipts],[True,True,False,True,True,True,True])
        self.assertEqual(meter.value(10),18)
        self.assertEqual(meter.total,3)
        self.now=30;g.lane.commands([N(op=4)])
        self.assertEqual(meter.value(60),4)
        self.assertEqual(meter.value(70),1)
        self.assertEqual(meter.value(90),0)

    def test_pause_and_speed_changes_do_not_decay_or_multiply_apm(self):
        g=self.game();meter=ActionMeter(g);self.now=20
        g.lane.commands([N(op=1)]*10)
        before=meter.value(20)
        for speed in (25,100,400,800):
            g.speed=speed;self.wall+=120
            self.assertEqual(meter.value(self.now),before)
        self.now=40;self.assertEqual(meter.value(self.now),15)

    def test_new_clock_resets_window_and_close_restores_original_sender(self):
        g=self.game();original=g.lane.commands;meter=ActionMeter(g)
        self.now=80;g.lane.commands([N(op=1)]*20)
        self.now=2;g.lane.commands([N(op=1)])
        self.assertEqual(meter.total,1);self.assertEqual(meter.value(12),6)
        meter.close();self.assertIs(g.lane.commands,original)
        g.lane.commands([N(op=1)]);self.assertEqual(meter.total,1)

    def test_sender_exception_propagates_without_counting_an_unconfirmed_action(self):
        g=self.game()
        def fail(*a,**kw):raise RuntimeError('transport failed')
        g.lane.commands=fail;meter=ActionMeter(g)
        with self.assertRaisesRegex(RuntimeError,'transport'):g.lane.commands([N(op=1)])
        self.assertEqual(meter.value(20),0)


class DisplayTests(unittest.TestCase):
    def test_console_updates_macro_target_without_counting_ui_and_keeps_speed_readback(self):
        helper=MeterTests();g=helper.game();g.ui=FakeUI();requested=[]
        g.set_speed=lambda p:requested.append(p) or True
        wall=[0];events=[];console=DebugConsole(g,lambda ev,**kw:events.append((ev,kw)),lambda:wall[0])
        bot=N(intent='练级：北西侧食人魔营地')
        helper.now=20;g.lane.commands([N(op=1)]*5)
        snap=N(clock=20,speed_pct=400);console.observe(snap,bot)
        items=g.ui.canvas.items
        self.assertEqual(set(items),{'bot.console.toggle'})
        g.ui.callbacks['bot.console.toggle'](g,None)
        self.assertIn('00:20',items['bot.console.metrics']['text']);self.assertIn('APM 15',items['bot.console.metrics']['text'])
        self.assertIn('食人魔',items['bot.console.intent']['text'])
        g.ui.callbacks['bot.speed.slower'](g,None)
        self.assertEqual(requested,[200]);self.assertEqual(items['bot.speed.current']['text'],'4×')
        wall[0]=1;snap.speed_pct=200;bot.intent='前往商店 · 购买腐蚀之球';console.observe(snap,bot)
        self.assertEqual(items['bot.speed.current']['text'],'2×');self.assertIn('腐蚀之球',items['bot.console.intent']['text'])
        self.assertEqual(console.meter.total,5)
        wall[0]=2;console.observe(snap,bot,paused=True)
        self.assertIn('暂停',items['bot.console.intent']['text']);self.assertIn('APM 15',items['bot.console.metrics']['text'])
        wall[0]=3;console.observe(snap,bot)
        self.assertIn('腐蚀之球',items['bot.console.intent']['text'])
        frame=items['bot.console.frame'];fx,fy=frame['screen']
        for key in ('bot.console.metrics','bot.console.intent','bot.speed.slower','bot.speed.faster'):
            item=items[key];x,y=item['screen']
            self.assertGreaterEqual(x,fx);self.assertLessEqual(x+item['width'],fx+frame['width'])
            self.assertGreaterEqual(y,fy);self.assertLessEqual(y+item['height'],fy+frame['height'])
        console.close()

    def test_old_snapshot_after_orders_does_not_reset_action_window(self):
        helper=MeterTests();g=helper.game();g.ui=FakeUI();g.set_speed=lambda p:True
        c=DebugConsole(g,lambda *a,**kw:None,lambda:0)
        helper.now=21;g.lane.commands([N(op=1)]*5)
        c.observe(N(clock=20,speed_pct=400),N(intent='进攻敌方主基地'))
        c.toggle()
        self.assertEqual(c.meter.total,5);self.assertIn('00:21',g.ui.canvas.items['bot.console.metrics']['text']);c.close()

    def test_emergency_portal_overrides_previous_creep_and_shopping_intent(self):
        g,b,dk,allies,orders,clock=safety.EmergencyTests().controller()
        b.intent='前往商店 · 购买腐蚀之球'
        b.tick(forced=Action.CREEP)
        self.assertIn('紧急回城',b.intent);self.assertEqual(orders[0][0],'portal')
        clock[0]+=1;b.tick(forced=Action.CREEP)
        self.assertIn('引导中',b.intent);self.assertEqual(len(orders),1)

    def test_attack_display_follows_actual_known_building_then_search_goal(self):
        moves=[];g=N(me=lambda:0,dist=dist,path_distance=dist,is_building=lambda u:True,visible=lambda *p:True,map=lambda:None)
        b=Controller(g,lambda *a,**kw:None);b.home=N(x=0,y=0);b.enemy_main=(5000,0)
        b.creeping.catalog=[dict(kind='expansion',x=7000,y=-3000)]
        b.go=lambda army,point,now,attack=False:moves.append(point);b.fight=lambda *a:None
        structure=unit('htow',10,x=5000);b.memory.update([structure],1,0,lambda u:True)
        army=[unit('Udea',1,owner=0)]
        b.advance_attack(army,[structure],(5000,0),2)
        self.assertEqual(b.intent,'进攻敌方主基地');self.assertEqual(moves[-1],(5000,0))
        b.advance_attack(army,[],(5000,0),3)
        self.assertIn('搜索残余建筑',b.intent);self.assertEqual(moves[-1],(7000,-3000))


class HistoryTests(unittest.TestCase):
    def make(self):
        helper=MeterTests();g=helper.game();g.ui=FakeUI();g.set_speed=lambda p:True
        events=[];c=DebugConsole(g,lambda ev,**kw:events.append((ev,kw)),lambda:helper.wall)
        def observe(at,text,wall_step=.6):
            helper.now=at;helper.wall+=wall_step
            c.observe(N(clock=at,speed_pct=400),N(intent=text,intent_clock=at))
        return c,g,helper,events,observe

    def test_collapsed_keeps_history_and_removes_all_hidden_button_hit_targets(self):
        c,g,h,events,observe=self.make();observe(1,'基地发展')
        self.assertEqual(set(g.ui.canvas.items),{'bot.console.toggle'})
        self.assertEqual(set(g.ui.callbacks),{'bot.console.toggle'})
        observe(10,'练级：西侧豺狼人营地');observe(20,'进攻敌方主基地')
        g.ui.callbacks['bot.console.toggle'](g,None)
        c.toggle_history()
        self.assertIn('[00:10]',g.ui.canvas.items['bot.console.entry.1']['text'])
        self.assertIn('进攻',g.ui.canvas.items['bot.console.entry.2']['text'])
        self.assertIn('bot.speed.slower',g.ui.callbacks)
        g.ui.callbacks['bot.console.toggle'](g,None)
        self.assertEqual(set(g.ui.canvas.items),{'bot.console.toggle'})
        self.assertEqual(set(g.ui.callbacks),{'bot.console.toggle'})
        observe(30,'回防基地')
        self.assertEqual(len(c.history),4);c.close()

    def test_scroll_anchor_stays_put_while_new_messages_arrive_and_latest_resumes_following(self):
        c,g,h,events,observe=self.make()
        for i in range(8):observe(i*10,f'目标{i}')
        c.toggle();c.toggle_history();g.ui.callbacks['bot.console.older'](g,None)
        before=[g.ui.canvas.items[f'bot.console.entry.{i}']['text'] for i in range(3)]
        observe(90,'回防基地');observe(100,'撤退回家')
        self.assertEqual([g.ui.canvas.items[f'bot.console.entry.{i}']['text'] for i in range(3)],before)
        self.assertEqual(c.unread,2);self.assertIn('2条新消息',g.ui.canvas.items['bot.console.label']['text'])
        g.ui.callbacks['bot.console.latest'](g,None)
        self.assertIsNone(c.view_end);self.assertEqual(c.unread,0)
        self.assertIn('[01:40] 撤退回家',g.ui.canvas.items['bot.console.entry.2']['text'])
        observe(110,'进攻敌方主基地')
        self.assertIn('[01:50] 进攻',g.ui.canvas.items['bot.console.entry.2']['text']);c.close()

    def test_timestamps_and_changes_are_retained_even_between_render_frames_without_duplicates(self):
        c,g,h,events,observe=self.make()
        observe(2,'练级',.1);observe(3,'练级',.1);observe(4,'买腐球',.1);observe(5,'进攻',.1)
        self.assertEqual(c.history,[{'clock':2,'text':'练级'},{'clock':4,'text':'买腐球'},{'clock':5,'text':'进攻'}])
        c.toggle();c.toggle_history();self.assertIn('[00:04] 买腐球',g.ui.canvas.items['bot.console.entry.1']['text'])
        self.assertEqual(len([e for e,_ in events if e=='strategic_intent']),3);c.close()

    def test_history_pages_stop_at_ends_and_resize_stays_above_native_bottom_hud(self):
        c,g,h,events,observe=self.make()
        for i in range(8):observe(i*10,f'目标{i}')
        c.toggle();c.toggle_history()
        for _ in range(10):c.scroll(-1)
        self.assertIn('[00:00]',g.ui.canvas.items['bot.console.entry.0']['text'])
        self.assertNotIn('bot.console.older',g.ui.callbacks)
        for _ in range(10):c.scroll(1)
        self.assertIsNone(c.view_end);self.assertNotIn('bot.console.newer',g.ui.callbacks)
        g.ui.block=N(state=lambda:{'back':(800,600)})
        observe(90,'回防基地')
        frame=g.ui.canvas.items['bot.console.frame']
        self.assertLessEqual(frame['screen'][1]+frame['height'],600*.75)
        self.assertLessEqual(frame['screen'][0]+frame['width'],800)
        self.assertEqual(len([k for k in g.ui.canvas.items if k.startswith('bot.console.entry.')]),3)
        c.close()


class PlacementTests(unittest.TestCase):
    def make(self):
        c,g,h,events,observe=HistoryTests().make()
        cursor=[(750,90)];hotkeys={}
        g.ui.cursor=lambda:dict(screen=cursor[0])
        g.ui.hotkey=lambda key,cb:hotkeys.setdefault(key,cb) or key
        def register(key,cb):hotkeys[key]=cb;return key
        g.ui.hotkey=register;g.ui.remove_hotkey=lambda key:hotkeys.pop(key,None)
        observe(1,'前往商店 · 购买腐蚀之球');c.toggle()
        return c,g,h,events,observe,cursor,hotkeys

    def test_compact_history_toggle_preserves_feed_and_speed_controls_fit(self):
        c,g,h,e,observe,cursor,hotkeys=self.make()
        compact=g.ui.canvas.items['bot.console.frame']
        self.assertLess(compact['width']*compact['height'],380*426*.30)
        self.assertFalse(any(k.startswith('bot.console.entry.') for k in g.ui.canvas.items))
        observe(20,'进攻敌方主基地');c.toggle_history()
        self.assertIn('[00:20]',g.ui.canvas.items['bot.console.entry.1']['text'])
        c.toggle_history();observe(30,'回防基地');c.toggle_history()
        self.assertIn('[00:30]',g.ui.canvas.items['bot.console.entry.2']['text'])
        c.speed.request(200);c.render()
        frame=g.ui.canvas.items['bot.console.frame'];status=g.ui.canvas.items['bot.speed.status']
        self.assertLessEqual(status['screen'][1]+status['height'],frame['screen'][1]+frame['height'])
        self.assertLess(status['screen'][1],g.ui.canvas.items['bot.console.older']['screen'][1])
        c.close()

    def test_click_placement_follows_cursor_clamps_and_commit_removes_capture(self):
        c,g,h,e,observe,cursor,hotkeys=self.make()
        old=c.layout()[:2];g.ui.callbacks['bot.console.move'](g,None)
        self.assertIn('bot.console.placement',g.ui.callbacks);self.assertIn('esc',hotkeys)
        cursor[0]=(300,200);observe(2,'前往商店 · 购买腐蚀之球')
        self.assertNotEqual(c.layout()[:2],old)
        frame=g.ui.canvas.items['bot.console.frame'];speed=g.ui.canvas.items['bot.speed.slower']
        self.assertEqual(speed['screen'],(frame['screen'][0]+158,frame['screen'][1]+34))
        cursor[0]=(1023,767);g.ui.callbacks['bot.console.placement'](g,None)
        self.assertLessEqual(c.layout()[0]+300,1016);self.assertLessEqual(c.layout()[1]+c.panel_height(),760)
        self.assertFalse(c.moving);self.assertNotIn('bot.console.placement',g.ui.callbacks);self.assertFalse(hotkeys)
        position=c.position;c.toggle();c.toggle();self.assertEqual(c.position,position);c.close()

    def test_escape_and_timeout_restore_position_and_outside_cursor_never_moves(self):
        c,g,h,e,observe,cursor,hotkeys=self.make()
        c.start_move();cursor[0]=(-1,-1);observe(2,'目标')
        self.assertIsNone(c.position)
        cursor[0]=(200,300);observe(3,'目标');self.assertIsNotNone(c.position)
        hotkeys['esc'](g,None);self.assertIsNone(c.position);self.assertFalse(c.moving)
        c.start_move();cursor[0]=(400,200);observe(4,'目标');h.wall+=16;observe(5,'目标')
        self.assertIsNone(c.position);self.assertFalse(c.moving);self.assertFalse(hotkeys)
        c.start_move();c.close();self.assertFalse(g.ui.callbacks);self.assertFalse(hotkeys)

    def test_resize_clamps_entire_expanded_history_and_repositions_speed(self):
        c,g,h,e,observe,cursor,hotkeys=self.make()
        c.position=(900,650);c.toggle_history()
        g.ui.block=N(state=lambda:{'back':(800,600)})
        observe(4,'进攻敌方主基地')
        frame=g.ui.canvas.items['bot.console.frame'];x,y=frame['screen']
        for key,item in g.ui.canvas.items.items():
            self.assertGreaterEqual(item['screen'][0],x,key)
            self.assertLessEqual(item['screen'][0]+item['width'],x+frame['width'],key)
            self.assertGreaterEqual(item['screen'][1],y,key)
            self.assertLessEqual(item['screen'][1]+item['height'],y+frame['height'],key)
        self.assertLessEqual(x+frame['width'],800);self.assertLessEqual(y+frame['height'],600)
        c.close()
