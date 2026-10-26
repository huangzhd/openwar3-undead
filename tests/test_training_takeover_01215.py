import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
import unittest
from uuid import uuid4
from unittest.mock import Mock, patch

import training
import training_control as c


class TrainingTakeoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for key in ('STATUS','COMMAND','SPEED_COMMAND','MODE_COMMAND'):
            p=patch.object(c,key,self.root/(key+'.json'));p.start();self.addCleanup(p.stop)
        self.sid=c.begin(dict(matchup='orc',level=7,mode='easy'),speed=400)
        c.status(self.sid,phase='running')

    def test_mode_requests_are_round_scoped_and_independent(self):
        self.assertTrue(c.post_mode(self.sid,'manual'))
        self.assertTrue(c.post_speed(self.sid,800))
        self.assertTrue(c.post(self.sid,'restart',speed=200))
        self.assertIsNone(c.take_mode('other',1))
        self.assertTrue(c.MODE_COMMAND.exists())
        self.assertIsNone(c.take_mode(self.sid,2))
        self.assertFalse(c.MODE_COMMAND.exists())
        self.assertEqual(c.take_speed(self.sid,1),800)
        self.assertEqual(c.take(self.sid)['action'],'restart')
        for mode in ('bad','',None):self.assertFalse(c.post_mode(self.sid,mode))
        self.assertFalse(c.post_mode('other','manual'))
        c.status(self.sid,phase='loading');self.assertFalse(c.post_mode(self.sid,'manual'))
        c.status(self.sid,phase='running',mode_control_available=False)
        self.assertFalse(c.post_mode(self.sid,'manual'))

    def test_acknowledgement_and_duplicate_requests(self):
        log=Mock();mode=c.RoundControl(self.sid,1,log)
        self.assertIn('自动',c.control_text(c.read_json(c.STATUS)))
        c.post_mode(self.sid,'manual')
        self.assertEqual(c.read_json(c.STATUS)['control_mode'],'auto')
        self.assertEqual(mode.observe(1),'manual')
        self.assertIn('已停止发令',c.control_text(c.read_json(c.STATUS)))
        c.post_mode(self.sid,'manual');self.assertIsNone(mode.observe(2))
        c.post_mode(self.sid,'auto');self.assertEqual(mode.observe(3),'auto')
        self.assertEqual(mode.history,[dict(clock=1,mode='manual'),dict(clock=3,mode='auto')])
        self.assertEqual(log.call_count,2)
        self.assertIn('旧训练进程',c.control_text(dict(phase='running')))
        self.assertIn('未运行',c.control_text(dict(phase='finished')))

    def test_takeover_speed_overrides_queue_and_requires_readback(self):
        g=N(set_speed=Mock(return_value=True));log=Mock()
        speed=c.RoundSpeed(g,log,self.sid,1,400,0,clock=lambda:0)
        c.post_speed(self.sid,800)
        speed.observe(N(clock=1,speed_pct=400),override=100)
        self.assertEqual([x.args[0] for x in g.set_speed.call_args_list],[100])
        self.assertEqual(c.read_json(c.STATUS)['speed_actual'],400)
        self.assertEqual(c.read_json(c.STATUS)['speed_pending'],100)
        speed.observe(N(clock=2,speed_pct=100))
        self.assertEqual(speed.preferred,100)
        self.assertIsNone(speed.pending)

    def run_loop(self, requests, states=None, speed_result=True, clocks=None, terminal=None,wall_step=None):
        root=self.root/uuid4().hex;(root/'undead').mkdir(parents=True)
        for name in ('training.py','training_map.py','training_control.py','session.py','game_preferences.py'):
            (root/name).write_text('fixture',encoding='utf-8')
        now=[0];step=[0];actual=[400];calls=[];created=[];speed_calls=[];closed=[]
        unit=N(type='ucry',addr=123)
        wall=[0]
        def snapshot(**kw):
            step[0]+=1;now[0]=clocks[step[0]-1] if clocks else step[0]
            if wall_step is not None:wall[0]+=wall_step
            if step[0] in requests:c.post_mode(self.sid,requests[step[0]])
            if terminal and step[0]==terminal[0]:c.post(self.sid,terminal[1])
            return N(clock=now[0],speed_pct=actual[0],in_game=True)
        def set_speed(pct):
            speed_calls.append(pct)
            if isinstance(speed_result,Exception):raise speed_result
            if speed_result:actual[0]=pct
            return speed_result
        g=N(snapshot=snapshot,clock=lambda:now[0],my_units=lambda:[unit],enemies=lambda:[],
            events=lambda:[('event',step[0])],set_speed=set_speed,me=lambda:0,
            claims=N(give_back=Mock()))
        def factory(*args):
            bot=N()
            for method in ('observe_events','update_training_phase','tick','skills','prepare'):
                setattr(bot,method,lambda *a,m=method:calls.append((step[0],m,a)))
            created.append(bot);return bot
        session=N(start=lambda:g,stop=lambda:closed.append(True),settings={})
        meter=N(last=0,summary=lambda now:{},close=lambda:None)
        def board(g):
            if step[0]>=8:return (3,0)
            return (states.get(step[0],2) if states else 2,12 if step[0]<4 else 3)
        args=N(matchup='orc',level=7,mode='easy',speed=400,probe=False,seconds=99,wall_seconds=240)
        original_speed=c.RoundSpeed
        with (patch.multiple(training,ROOT=root,STOP=root/'STOP',active_processes=lambda:[],
                build=lambda *a,**k:(root/'map',{}),install_map=lambda *a:root/'map',
                TrainingSession=lambda *a:session,TrainingController=factory,ActionMeter=lambda g:meter,
                board_signal=board,contact_reason=lambda *a:None,unit_row=lambda *a:dict(type='ucry')),
                patch.object(training.time,'sleep',lambda _:None),
                patch.object(training.time,'monotonic',lambda:wall[0]),
                patch.object(c,'RoundSpeed',side_effect=lambda *a,**kw:original_speed(*a,**kw,clock=lambda:wall[0])),
                contextlib.redirect_stdout(io.StringIO())):
            result=training.run(args,self.sid,1)
        events=[json.loads(line) for line in (Path(result['artifact_dir'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        return N(result=result,calls=calls,bots=created,speeds=speed_calls,g=g,closed=closed,events=events)

    def test_manual_blocks_all_bot_entrypoints_and_auto_rebuilds_from_live_phase(self):
        r=self.run_loop({2:'manual',5:'auto'},states={1:1,2:1,3:1})
        self.assertEqual(r.result['result'],'win')
        self.assertEqual({step for step,_,_ in r.calls},{1,5,6,7})
        self.assertEqual([m for step,m,_ in r.calls if step==1],['observe_events','update_training_phase','skills','prepare'])
        self.assertEqual([step for step,m,_ in r.calls if m=='tick'],[5,6,7])
        self.assertEqual(len(r.bots),2)
        self.assertTrue(r.bots[-1].battle_started);self.assertTrue(r.bots[-1].blight_opened)
        self.assertFalse(r.bots[-1].blight_waiting)
        self.assertEqual(r.bots[-1].training_peak_enemies,3)
        self.assertEqual([a for _,m,a in r.calls if m=='observe_events'],[([('event',n)],) for n in (1,5,6,7)])
        self.assertEqual(r.speeds,[100]);r.g.claims.give_back.assert_called_once_with(123)
        self.assertTrue(r.result['human_takeover_used']);self.assertEqual(r.result['final_control_mode'],'auto')
        self.assertEqual(r.result['final_speed'],100);self.assertEqual(r.closed,[True])
        self.assertTrue(r.result['source_unchanged'])
        self.assertEqual([e['clock'] for e in r.events if e['event']=='training_sample' and e['control_mode']=='manual'],[2,3,4])

    def test_manual_stays_manual_even_if_speed_rejected_or_raises(self):
        for response in (False,RuntimeError('denied')):
            with self.subTest(response=response):
                r=self.run_loop({1:'manual',3:'manual'},speed_result=response)
                self.assertEqual(r.calls,[]);self.assertEqual(r.speeds,[100])
                self.assertEqual(r.result['result'],'win')
                self.assertEqual(r.result['final_control_mode'],'manual')
                self.assertEqual(r.result['final_speed'],400)
                self.assertTrue(c.read_json(c.STATUS)['speed_message'])

    def test_switches_are_processed_even_on_unchanged_game_clock(self):
        r=self.run_loop({2:'manual',3:'auto'},clocks=[1,1,1,2,3,4,5,6])
        self.assertEqual([s for s,m,_ in r.calls if m=='tick'],[1,4,5,6,7])
        self.assertEqual(r.speeds,[100]);self.assertEqual(len(r.bots),2)
        self.assertEqual(r.result['control_history'],[dict(clock=1,mode='manual'),dict(clock=1,mode='auto')])

    def test_return_to_auto_before_combat_resumes_preparation(self):
        r=self.run_loop({1:'manual',4:'auto'},states={n:1 for n in range(1,8)})
        self.assertEqual([s for s,m,_ in r.calls if m=='prepare'],[4,5,6,7])
        self.assertFalse(r.bots[-1].battle_started)
        self.assertFalse(r.bots[-1].blight_opened)

    def test_manual_preserves_explicit_forfeit_and_new_round_defaults_to_auto(self):
        r=self.run_loop({1:'manual'},terminal=(4,'forfeit'))
        self.assertEqual(r.result['result'],'forfeit');self.assertEqual(r.calls,[])
        self.assertEqual(r.closed,[True])
        c.post_mode(self.sid,'manual')
        sid=c.begin(dict(matchup='orc',level=7,mode='easy'))
        self.assertEqual(c.read_json(c.STATUS)['control_mode'],'auto')
        self.assertIsNone(c.RoundControl(sid,1,Mock()).observe(1))

    def test_normal_round_ignores_old_game_and_wall_limits_in_both_modes(self):
        for requests in ({},{1:'manual'}):
            r=self.run_loop(requests,clocks=[n*10000 for n in range(1,9)],wall_step=10000)
            self.assertEqual(r.result['result'],'win')
            self.assertEqual(r.result['reason'],'original_map_round_result')
            self.assertIsNone(r.result['max_game_seconds']);self.assertIsNone(r.result['max_wall_seconds'])
            self.assertGreater(r.result['wall_budget_used'],240)
            self.assertEqual(r.closed,[True])


if __name__=='__main__':unittest.main()
