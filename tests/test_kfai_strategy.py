import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

from kfai_strategy import MISSION, StrategyTrace, read_publication
from learning.review_kfai import analyze


class Cache:
    def __init__(self):
        self.data=dict(sequence=2,version=1,player=2,strategy=0,chosen_strategy=0,counter=4)
        self.hook=None
    def InitGameCache(self,name):return 10
    def GetStoredInteger(self,cache,mission,key):
        assert cache==10 and mission==MISSION
        if self.hook:self.hook(key)
        return self.data[key]


class StrategyTests(unittest.TestCase):
    def test_reads_actual_ids_and_reports_skipped_changes_not_guessed_army_labels(self):
        j=Cache()
        first=read_publication(j,10,0)
        self.assertEqual(first['strategy_name'],'Rifle')
        self.assertEqual(first['missed_publications'],0)
        j.data.update(sequence=8,strategy=11,chosen_strategy=11)
        changed=read_publication(j,10,2)
        self.assertEqual(changed['strategy_name'],'Gryph')
        self.assertEqual(changed['missed_publications'],2)
        self.assertIsNone(read_publication(j,10,8))

    def test_partial_writes_wrong_player_and_reset_cannot_become_strategy_evidence(self):
        j=Cache();j.data['sequence']=3
        self.assertIsNone(read_publication(j,10,0))
        j.data.update(sequence=2,player=1)
        with self.assertRaises(RuntimeError):read_publication(j,10,0)
        j.data['player']=2
        with self.assertRaises(RuntimeError):read_publication(j,10,8)
        j.data['sequence']=0
        with self.assertRaises(RuntimeError):read_publication(j,10,2)
        j.data['sequence']=2
        def change_during_read(key):
            if key=='counter':j.data['sequence']+=2
        j.hook=change_during_read
        self.assertIsNone(read_publication(j,10,0))

    def trace(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'trace.jsonl'
        game=N(jass=Cache(),world=N(read=lambda:N(in_game=True,me=0,epoch=7)),close=Mock())
        trace=StrategyTrace(game,path)
        self.addCleanup(lambda:trace.close() if not trace.stream.closed else None)
        return trace,game,path

    def test_trace_is_sidecar_only_and_rejects_game_change(self):
        trace,game,path=self.trace()
        trace.poll(7,10,1)
        game.world.read=lambda:N(in_game=True,me=0,epoch=8)
        for i in range(3):trace.poll(8,20+i,2+i)
        trace.close()
        rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        samples=[r for r in rows if r['event']=='kfai_strategy_snapshot']
        self.assertEqual([r['epoch'] for r in samples],[7])
        self.assertTrue(rows[-1]['disabled'])
        self.assertTrue(game.close.called)

    def test_missing_bridge_is_bounded_and_never_claims_capture(self):
        trace,game,path=self.trace();game.jass.data['sequence']=0
        trace.poll(7,10,1);trace.poll(7,40,2)
        self.assertTrue(trace.disabled)
        game.jass.data['sequence']=2
        trace.poll(7,50,3);trace.close()
        rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        self.assertFalse(any(r['event']=='kfai_strategy_snapshot' for r in rows))
        self.assertFalse(rows[-1]['captured_publication'])

    def test_invalid_cache_handle_is_never_used_and_retries_stop(self):
        trace,game,path=self.trace()
        game.jass.InitGameCache=lambda name:0
        game.jass.GetStoredInteger=Mock(side_effect=AssertionError('Invalid native handle reached reader'))
        for i in range(5):trace.poll(7,i,i)
        trace.close()
        rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        errors=[r for r in rows if r['event']=='strategy_trace_error']
        self.assertTrue(errors and all('cache handle unavailable' in r['error'] for r in errors))
        self.assertTrue(rows[-1]['disabled'])
        self.assertFalse(rows[-1]['captured_publication'])

    def test_review_requires_queue_and_return_before_confirming_revival(self):
        rows=[dict(event='hero_revival_state',clock=10,missing=['Ulic'],queued=[]),
              dict(event='revive_attempt',clock=11,heroes=['Ulic'],accepted=True),
              dict(event='hero_revival_state',clock=12,missing=['Ulic'],queued=['Ulic']),
              dict(event='hero_revival_state',clock=20,missing=[],queued=[])]
        review=analyze(rows,dict(id='test',result='win'))
        self.assertTrue(review['hero_revival'][0]['confirmed_revival_cycle'])
        self.assertEqual(review['hero_revival'][0]['absence_seconds'],10)
        self.assertFalse(analyze(rows[:-1],{})['hero_revival'][0]['confirmed_revival_cycle'])
        self.assertFalse(analyze([rows[0],rows[-1]],{})['hero_revival'][0]['confirmed_revival_cycle'])
