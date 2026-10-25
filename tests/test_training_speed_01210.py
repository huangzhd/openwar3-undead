import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
from unittest.mock import patch, Mock
import training_control as c
import training


class TrainingSpeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for key,name in (('STATUS','s.json'),('COMMAND','c.json'),('SPEED_COMMAND','speed.json')):
            p=patch.object(c,key,root/name);p.start();self.addCleanup(p.stop)
        self.sid=c.begin(dict(matchup='orc',level=6,mode='easy'))
        c.status(self.sid,phase='running')
        self.now=0;self.events=[];self.g=N(set_speed=Mock(return_value=True))
        self.speed=c.RoundSpeed(self.g,lambda e,**kw:self.events.append((e,kw)),self.sid,1,100,0,lambda:self.now)

    def snap(self,pct=100):return N(speed_pct=pct,clock=self.now)

    def test_round_scoped_speed_channel_does_not_replace_terminal_command(self):
        self.assertTrue(c.post(self.sid,'forfeit'))
        self.assertTrue(c.post_speed(self.sid,200))
        self.assertEqual(c.take(self.sid)['action'],'forfeit')
        self.assertIsNone(c.take_speed('wrong',1))
        self.assertIsNone(c.take_speed(self.sid,2))
        self.assertFalse(c.SPEED_COMMAND.exists())
        for bad in (24,801,True,'200',200.0,37):self.assertFalse(c.post_speed(self.sid,bad))
        self.assertFalse(c.post_speed('wrong',200))
        c.status(self.sid,phase='finished');self.assertFalse(c.post_speed(self.sid,200))
        c.status(self.sid,phase='running',speed_control_available=False)
        self.assertFalse(c.post_speed(self.sid,200))

    def test_six_speeds_require_actual_readback_and_persist_only_after_confirmation(self):
        self.speed.observe(self.snap())
        for pct in c.SPEEDS:
            before=self.speed.actual
            self.assertTrue(c.post_speed(self.sid,pct));self.speed.observe(self.snap(before))
            self.assertEqual(self.speed.actual,before)
            self.assertEqual(self.speed.pending,pct)
            self.now+=.5;self.speed.observe(self.snap(pct))
            state=c.read_json(c.STATUS)
            self.assertEqual(state['speed'],pct);self.assertEqual(state['speed_actual'],pct)
            self.assertIsNone(state['speed_pending'])
        self.assertEqual([call.args[0] for call in self.g.set_speed.call_args_list],list(c.SPEEDS))

    def test_failure_exception_and_timeout_do_not_claim_success(self):
        self.speed.observe(self.snap())
        for response in (False,RuntimeError('denied'),True):
            self.g.set_speed.side_effect=response if isinstance(response,Exception) else None
            self.g.set_speed.return_value=response
            c.post_speed(self.sid,400);self.speed.observe(self.snap())
            self.now+=4;self.speed.observe(self.snap())
            self.assertIsNone(self.speed.pending)
            self.assertEqual(self.speed.preferred,100)
            self.assertEqual(c.read_json(c.STATUS)['speed_actual'],100)
            self.assertTrue(self.speed.message)
        self.assertEqual(len(self.g.set_speed.call_args_list),3)

    def test_slow_motion_scales_wall_budget_and_fast_motion_keeps_original_bound(self):
        self.speed.observe(self.snap(25));self.now=100;self.speed.observe(self.snap(200))
        self.assertEqual(self.speed.budget_used,25)
        self.now=200;self.speed.observe(self.snap(100))
        self.assertEqual(self.speed.budget_used,125)
        self.now=210;self.speed.observe(self.snap(100))
        self.assertEqual(self.speed.budget_used,135)

    def test_restart_and_switch_carry_selected_speed_only_after_cleanup(self):
        self.assertTrue(c.post(self.sid,'restart',speed=800));self.assertEqual(c.take(self.sid)['speed'],800)
        self.assertFalse(c.post(self.sid,'switch',dict(matchup='orc',level=6,mode='easy'),speed=900))
        for cleanup in (False,True):
            speeds=[]
            def run(args,sid,attempt):
                speeds.append(args.speed)
                return dict(result='restart_requested' if attempt==1 else 'win',cleanup_confirmed=cleanup,
                            next_speed=400,artifact_dir=self.tmp.name)
            args=N(probe=False,matchup='orc',level=6,mode='easy',speed=100,seconds=180,wall_seconds=240)
            with patch.object(c,'launch',return_value=None),patch.object(training,'run',side_effect=run):training.play(args)
            self.assertEqual(speeds,[100,400] if cleanup else [100])

    def test_status_text_separates_requested_actual_and_idle(self):
        self.assertIn('未运行',c.speed_text(dict(phase='finished',speed_actual=400)))
        self.assertIn('读取中',c.speed_text(dict(phase='running')))
        text=c.speed_text(dict(phase='running',speed_actual=100,speed_pending=400))
        self.assertIn('实际速度：1×',text);self.assertIn('正在设置 4×',text)

    def test_live_loop_processes_speed_without_finishing_or_restarting_round(self):
        root=Path(self.tmp.name);(root/'undead').mkdir()
        for name in ('training.py','training_map.py','training_control.py','session.py','game_preferences.py'):
            (root/name).write_text('fixture')
        game_clock=[0];actual=[100];ticks=[];closed=[]
        def snap(**kw):
            game_clock[0]+=1
            if game_clock[0]==1:c.post_speed(self.sid,200)
            return N(clock=game_clock[0],speed_pct=actual[0],in_game=True)
        def change(pct):actual[0]=pct;return True
        g=N(snapshot=snap,clock=lambda:game_clock[0],my_units=lambda:[],enemies=lambda:[],events=lambda:[],set_speed=change)
        session=N(start=lambda:g,stop=lambda:closed.append(True),settings={})
        bot=N(observe_events=lambda _:None,update_training_phase=lambda *a:None,tick=lambda:ticks.append(game_clock[0]))
        meter=N(last=0,sample=lambda now:{},summary=lambda now:{},close=lambda:None)
        args=N(matchup='orc',level=6,mode='easy',speed=100,probe=False,seconds=3,wall_seconds=240)
        with patch.multiple(training,ROOT=root,STOP=root/'STOP',active_processes=lambda:[],
                build=lambda *a,**k:(root/'map',{}),install_map=lambda *a:root/'map',
                TrainingSession=lambda *a:session,TrainingController=lambda *a:bot,ActionMeter=lambda g:meter,
                board_signal=lambda g:(2,None)),patch.object(training.time,'sleep',lambda _:None):
            result=training.run(args,self.sid,1)
        self.assertEqual(result['reason'],'game_time_limit')
        self.assertEqual(ticks,[1,2]);self.assertEqual(closed,[True])
        self.assertEqual(result['final_speed'],200);self.assertEqual(args.speed,200)
        self.assertEqual([h['percent'] for h in result['speed_history']],[100,200])


if __name__=='__main__':unittest.main()
