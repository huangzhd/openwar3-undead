import json,tempfile,unittest,contextlib,io
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import run_match
import test_debug_console as display
from undead.policy import Situation


class MatchButtonTests(unittest.TestCase):
    def test_buttons_queue_only_one_action_disable_and_do_not_count_apm(self):
        c,g,h,events,observe=display.HistoryTests().make()
        observe(10,'练级');c.toggle()
        restart=g.ui.callbacks['bot.console.restart'];surrender=g.ui.callbacks['bot.console.surrender']
        restart(g,None);restart(g,None);surrender(g,None)
        self.assertEqual(c.match_action,'restart')
        self.assertNotIn('bot.console.restart',g.ui.callbacks)
        self.assertNotIn('bot.console.surrender',g.ui.callbacks)
        self.assertIn('正在重开',g.ui.canvas.items['bot.console.restart']['text'])
        self.assertFalse(g.ui.canvas.items['bot.console.surrender']['clickable'])
        self.assertEqual(c.meter.total,0)
        c.close();self.assertFalse(g.ui.callbacks)

    def test_controls_do_not_overlap_speed_message_or_history_and_hide_when_collapsed(self):
        c,g,h,events,observe=display.HistoryTests().make()
        observe(10,'练级');c.toggle();c.toggle_history();c.speed.request(800);c.render()
        items=g.ui.canvas.items;button=items['bot.console.restart'];status=items['bot.speed.status']
        self.assertGreaterEqual(button['screen'][1],status['screen'][1]+status['height'])
        self.assertLessEqual(button['screen'][1]+button['height'],items['bot.console.older']['screen'][1])
        self.assertGreaterEqual(button['screen'][0],items['bot.console.surrender']['screen'][0]+138+8)
        c.toggle();self.assertNotIn('bot.console.restart',g.ui.callbacks)
        self.assertNotIn('bot.console.surrender',items);c.close()


class MatchLifecycleTests(unittest.TestCase):
    def play(self,actions,*,freeze=False,cleanup_failure=False,ui_failure=False,stop_after=False,
             deadline_after=False,live_after=False,terminal_on_click=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in ('session.py','run_match.py','game_preferences.py'):(root/n).write_text('fixture')
            order=[];games=[];wall=[100.0];cutoff=110 if deadline_after else None
            def create(speed,race,difficulty):
                idx=len(games)
                if idx>=len(actions):raise AssertionError('Unrequested additional match')
                if idx:
                    self.assertIn(('closed',idx-1),order)
                    self.assertTrue(list((root/'artifacts').glob('*/result.json')))
                helper=display.MeterTests();g=helper.game();g.ui=display.FakeUI();g.set_speed=lambda p:True
                count=[0];ticks=[];game=dict(g=g,helper=helper,count=count,ticks=ticks,settings=(speed,race,difficulty))
                games.append(game)
                def snapshot(**kw):
                    count[0]+=1
                    if actions[idx]=='error' and count[0]==2:raise RuntimeError('publication failed')
                    helper.now=1 if freeze else count[0]
                    return N(clock=helper.now,speed_pct=800,publish_count=count[0],me=0,in_game=True)
                def events():
                    if count[0]==2 and actions[idx] in ('restart','surrender'):
                        g.ui.callbacks['bot.console.toggle'](g,None)
                        cb=g.ui.callbacks['bot.console.'+actions[idx]]
                        cb(g,None);cb(g,None)
                    return []
                g.snapshot=snapshot;g.events=events;g.world=N(read=lambda:None)
                g.my_units=lambda:[];g.my_heroes=lambda:[];g.resources=lambda:{}
                g.all_production=lambda *a:[];g.tech_many=lambda codes:{}
                def start(**kw):order.append(('started',idx));return g
                def stop():
                    order.append(('closed',idx))
                    if cleanup_failure:raise RuntimeError('cleanup failed')
                    (root/'artifacts/session.json').write_text(json.dumps({'processes':[{'pid':1}] if live_after else [],'closed':not live_after}))
                    if stop_after:(root/'artifacts/STOP').write_text('stop')
                    if deadline_after:wall[0]=120
                return N(game=g,start=start,stop=stop)
            def policy(g,log,race):
                item=next(x for x in games if x['g'] is g)
                return N(tick=lambda:item['ticks'].append(g.clock()),observe_events=lambda e:None,
                         situation=Situation(0),intent='练级')
            def terminal(*args):
                game=games[-1];idx=len(games)-1;count=game['count'][0]
                if terminal_on_click and count>=2:return ('win','all_enemy_buildings_destroyed')
                if actions[idx] is None and count>=3:return ('loss','all_own_buildings_destroyed')
            def console(g,*args):
                c=display.DebugConsole(g,*args)
                if ui_failure:
                    def close():raise RuntimeError('ui cleanup failed')
                    c.close=close
                return c
            def sleep(seconds):wall[0]+=1
            with patch.multiple(run_match,ROOT=root,Controller=policy,DebugConsole=console,
                                Referee=lambda:N(observe=terminal)), \
                 patch.object(run_match,'Session',side_effect=create) as sessions, \
                 patch.object(run_match.time,'sleep',sleep),patch.object(run_match.time,'monotonic',lambda:wall[0]), \
                 patch.object(run_match.time,'time',lambda:wall[0]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                sessions.matches=lambda row:live_after
                result=run_match.play_matches(400,None,cutoff,3,4)
            saved=[json.loads(p.read_text(encoding='utf-8')) for p in (root/'artifacts').glob('*/result.json')]
            events=[json.loads(s) for p in (root/'artifacts').glob('*/events.jsonl') for s in p.read_text(encoding='utf-8').splitlines()]
            return result,saved,games,order,events

    def test_surrender_during_pause_stops_without_new_orders_or_restart(self):
        result,saved,games,order,events=self.play(['surrender'],freeze=True)
        self.assertEqual((result['result'],result['reason']),('loss','manual_surrender'))
        self.assertEqual(games[0]['ticks'],[1]);self.assertEqual(order,[('started',0),('closed',0)])
        self.assertEqual(saved,[result]);self.assertFalse(games[0]['g'].ui.callbacks)
        self.assertTrue(any(e['event']=='match_control_committed' and e['action']=='surrender' for e in events))

    def test_restart_closes_and_persists_old_game_then_inherits_actual_speed_and_opponent(self):
        result,saved,games,order,events=self.play(['restart','surrender'],freeze=True)
        self.assertEqual(order,[('started',0),('closed',0),('started',1),('closed',1)])
        old=next(r for r in saved if r['reason']=='manual_restart')
        self.assertEqual(old['result'],'aborted');self.assertEqual(result['restarted_from'],old['id'])
        self.assertEqual(games[1]['settings'],(800,3,4));self.assertIsNone(result['max_game_seconds'])
        self.assertEqual(result['reason'],'manual_surrender');self.assertNotEqual(old['id'],result['id'])
        self.assertEqual([g['ticks'] for g in games],[[1],[1]])

    def test_new_game_does_not_reuse_old_click_and_natural_end_does_not_restart(self):
        result,saved,games,order,events=self.play(['restart',None])
        self.assertEqual(result['reason'],'all_own_buildings_destroyed')
        self.assertEqual(games[1]['ticks'],[1,2]);self.assertEqual(order[-1],('closed',1))
        self.assertFalse(any(r.get('reason')=='manual_surrender' for r in saved))

    def test_cleanup_failure_stops_restart(self):
        result,saved,games,order,events=self.play(['restart'],cleanup_failure=True)
        self.assertEqual(result['restart_blocked'],'cleanup_failed')
        self.assertIn('cleanup_error',saved[0]);self.assertEqual(order,[('started',0),('closed',0)])

    def test_ui_cleanup_error_still_closes_game_and_prevents_restart(self):
        result,saved,games,order,events=self.play(['restart'],ui_failure=True)
        self.assertEqual(result['restart_blocked'],'cleanup_failed')
        self.assertIn('ui_cleanup_error',saved[0]);self.assertIn(('closed',0),order)

    def test_stop_or_expired_explicit_deadline_during_cleanup_cancels_restart(self):
        for kw,reason in [({'stop_after':True},'user_stop'),({'deadline_after':True},'automation_deadline')]:
            with self.subTest(reason=reason):
                result,saved,games,order,events=self.play(['restart'],**kw)
                self.assertEqual(result['restart_blocked'],reason);self.assertEqual(saved,[result])
                self.assertEqual(order,[('started',0),('closed',0)])

    def test_still_live_session_blocks_next_launch(self):
        result,saved,games,order,events=self.play(['restart'],live_after=True)
        self.assertEqual(result['restart_blocked'],'previous_session_still_running')
        self.assertEqual(order,[('started',0),('closed',0)])

    def test_game_error_stops_instead_of_restarting(self):
        result,saved,games,order,events=self.play(['error'])
        self.assertEqual(result['result'],'error');self.assertIn('publication failed',result['reason'])
        self.assertEqual(order,[('started',0),('closed',0)]);self.assertEqual(saved,[result])

    def test_confirmed_terminal_wins_over_click_in_same_poll(self):
        result,saved,games,order,events=self.play(['restart'],terminal_on_click=True)
        self.assertEqual(result['reason'],'all_enemy_buildings_destroyed')
        self.assertNotIn('restart_speed',result);self.assertEqual(order,[('started',0),('closed',0)])
