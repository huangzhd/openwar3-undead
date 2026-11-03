import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace as N

import bootstrap
import w3fast
from openwar3 import Game
from learning.actions import SCHEMA, PrimitiveExecutor, validate, preflight, receipt_diagnostics
from learning.trajectory import BoundaryError, TrajectoryRecorder
from test_learning_trajectory import fixture


def action(op, **kwargs):
    return dict(schema=SCHEMA, op=op, **kwargs)


class PrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.game, self.raw = fixture()
        self.own, self.seen, self.hidden = self.raw.units
        self.own.has_detail = True
        self.own.abilities = [N(code=c, level=1, cooldown=0) for c in ('Amov','Aatk')]
        self.own.items = [None]*6
        self.game.map = lambda:N(bounds=(-1000,1000,-1000,1000))
        self.game._batch = None
        self.game._take = lambda *args:True
        self.game._recent_orders = {}
        self.game._QUEUE = Game._QUEUE
        for method in ('_q','_issue','move','attack_move','attack','stop','hold'):
            setattr(self.game,method,MethodType(getattr(Game,method),self.game))
        self.native = self.game.lane.commands
        self.rec = TrajectoryRecorder(self.game,self.path/'trajectory.jsonl',policy='external_primitives')
        self.executor = PrimitiveExecutor(self.game,self.rec,self.path/'actions.jsonl')
        self.addCleanup(lambda:self.rec.finish('aborted','user_stop'))
        self.addCleanup(self.executor.close)
        self.decision = copy.deepcopy(self.rec.last_observation)

    def run_action(self, value):
        self.executor.execute(value,self.decision,1)
        return self.executor.drain_receipts()[-1]

    def rows(self):
        return [json.loads(s) for s in (self.path/'actions.jsonl').read_text().splitlines()]

    def test_all_six_operations_dispatch_exact_sdk_commands_without_queue_or_addresses_in_log(self):
        cases = [(action('move',unit=[11,7],x=12.1,y=-20), 'point',851986),
                 (action('attack_move',unit=[11,7],x=40,y=50),'point',851983),
                 (action('attack',unit=[11,7],target=[22,7]),'target',851971),
                 (action('stop',unit=[11,7]),'immediate',851972),
                 (action('hold',unit=[11,7]),'immediate',851993)]
        for value,op,code in cases:
            with self.subTest(op=value['op']):
                receipt=self.run_action(value)
                self.assertTrue(receipt['accepted'])
                call=self.native.call_args.args[0][0]
                self.assertEqual(call.op,w3fast.OP[op]);self.assertEqual(call.args[3],code)
                self.assertEqual(call.args[:3],[self.own.addr,11,7])
                self.assertEqual(call.args[9:],[0,0])
                expected=w3fast.command(op,self.own,code,target=self.seen if op=='target' else None,
                                         x=value.get('x'),y=value.get('y'))
                self.assertEqual(call.args,expected.args)
        calls=len(self.native.call_args_list)
        self.assertEqual(self.run_action(action('wait'))['status'],'no_command')
        self.assertEqual(len(self.native.call_args_list),calls)
        data=json.dumps(self.rows())
        self.assertNotIn(str(self.own.addr),data);self.assertNotIn('args',data)
        self.assertEqual(self.rows()[0]['policy'],'external_primitives')

    def test_invalid_or_unsupported_schema_never_submits(self):
        for value in (action('build',unit=[11,7],x=0,y=0),action('stop',unit=[True,7]),
                      action('move',unit=[11,7],x=float('nan'),y=1),
                      action('move',unit=[11,7],x=1e50,y=1),
                      action('attack',unit=[11,7],target=[22,7],force=True),
                      action('stop',unit=[11,7],queue='after'),
                      dict(schema='v0',op='wait')):
            with self.subTest(value=value),self.assertRaises(ValueError):self.run_action(value)
        self.native.assert_not_called()

    def test_outside_map_unknown_capabilities_and_invisible_target_are_rejected(self):
        for value in (action('move',unit=[11,7],x=1001,y=0),
                      action('stop',unit=[22,7]),
                      action('attack',unit=[11,7],target=[33,7])):
            receipt=self.run_action(value)
            self.assertFalse(receipt['accepted']);self.assertEqual(receipt['status'],'preflight_rejected')
        self.own.has_detail=False
        self.assertFalse(self.run_action(action('stop',unit=[11,7]))['accepted'])
        self.native.assert_not_called()

    def test_same_clock_visibility_or_ownership_change_rechecked_before_command(self):
        attack=action('attack',unit=[11,7],target=[22,7])
        self.assertEqual(preflight(attack,self.decision,self.executor.bounds),'allowed')
        self.seen.visible_mask=1
        self.assertFalse(self.run_action(attack)['accepted'])
        self.seen.visible_mask=3;self.own.owner=2
        self.assertFalse(self.run_action(action('move',unit=[11,7],x=1,y=2))['accepted'])
        self.native.assert_not_called()

    def test_newly_visible_entity_cannot_be_selected_from_old_observation(self):
        self.hidden.visible_mask=3;self.raw.clock+=1;self.raw.publish_count+=1
        self.assertFalse(self.run_action(action('attack',unit=[11,7],target=[33,7]))['accepted'])
        self.native.assert_not_called()

    def test_hidden_world_changes_cannot_change_preflight_result(self):
        value=action('attack',unit=[11,7],target=[33,7])
        first=self.run_action(value)
        self.hidden.flags=0;self.hidden.hp=0;self.hidden.owner=3
        self.raw.players[2].gold=999999;self.hidden.x=999999
        second=self.run_action(value)
        self.assertEqual(first['reason'],second['reason'])
        self.assertFalse(second['accepted']);self.native.assert_not_called()

    def test_stale_decision_and_changed_epoch_never_execute(self):
        self.raw.clock+=9;self.raw.publish_count+=1
        receipt=self.run_action(action('stop',unit=[11,7]))
        self.assertEqual(receipt['reason'],'stale_decision')
        self.raw.epoch+=1
        with self.assertRaises(BoundaryError):self.run_action(action('stop',unit=[11,7]))
        self.native.assert_not_called()
        self.assertEqual(self.rows()[-1]['accepted'],None)

    def test_rejection_missing_timeout_and_transport_failure_preserve_uncertainty(self):
        for status in (7,99):
            self.native.side_effect=lambda calls,s=status:[w3fast.Receipt(calls[0].op,s,0,None,0,0,(0,)*8)]
            receipt=self.run_action(action('stop',unit=[11,7]))
            self.assertIs(receipt['accepted'],False if status==7 else None)
        self.native.side_effect=lambda calls:[]
        self.assertIsNone(self.run_action(action('stop',unit=[11,7]))['accepted'])
        self.native.side_effect=RuntimeError('private opponent gold=999999')
        with self.assertRaises(RuntimeError):self.run_action(action('stop',unit=[11,7]))
        self.assertNotIn('999999',json.dumps(self.rows()))
        self.assertIsNone(self.rows()[-1]['accepted'])
        self.assertEqual(len(self.native.call_args_list),4)  # Each distinct request, no retry.

    def test_receipt_links_to_later_observation_without_claiming_effect(self):
        receipt=self.run_action(action('attack',unit=[11,7],target=[22,7]))
        self.assertEqual(receipt['native_request_ids'],[1])
        self.executor.observe()
        self.assertFalse(any(r['event']=='next_observation' for r in self.rows()))
        self.raw.clock+=1;self.raw.publish_count+=1;self.seen.hp-=10
        self.rec.observe();self.executor.observe()
        self.assertEqual(self.rows()[-1],dict(event='next_observation',id=1,observation_id=2,
                                            clock=11.,effect='unverified'))
        self.run_action(action('wait'));self.executor.close()
        self.assertIsNone(self.rows()[-1]['observation_id'])

    def test_float_coordinates_are_recorded_as_native_float32(self):
        value=action('move',unit=[11,7],x=0.1,y=-0.2)
        normalized=validate(value)
        self.run_action(value)
        request=next(r for r in self.rows() if r['event']=='request')
        self.assertEqual(request['action'],normalized)
        self.assertNotEqual(normalized['x'],value['x'])

    def test_rejection_details_are_preserved_only_in_diagnostic_sidecar(self):
        self.native.side_effect=lambda calls:[w3fast.Receipt(calls[0].op,1,0,1001,851986,851986,(999999,)*8,
                                                            note='private=123456',data=b'private')]
        receipt=self.run_action(action('attack',unit=[11,7],target=[22,7]))
        self.assertFalse(receipt['accepted'])
        rows=[json.loads(s) for s in (self.path/'primitive-diagnostics.jsonl').read_text().splitlines()]
        self.assertTrue(rows[0]['excluded_from_actor'])
        self.assertEqual(rows[1],dict(event='receipt',id=1,native_status=1,verdict=1001,engine_return=0,
                                     order_before=851986,order_after=851986))
        for key in ('verdict','engine_return','order_before','order_after','values','data','note'):
            self.assertNotIn(key,receipt)
            self.assertNotIn(key,json.dumps(self.rows()))
        self.assertNotIn('private',json.dumps(rows));self.assertNotIn('999999',json.dumps(rows))

    def test_missing_synthetic_and_malformed_diagnostic_fields_stay_unknown(self):
        for result in (None,w3fast.Receipt.timeout(1),N(status=98,verdict=0,order_after=0)):
            row=receipt_diagnostics(result)
            self.assertTrue(all(row[key] is None for key in ('verdict','engine_return','order_before','order_after')))
        row=receipt_diagnostics(N(status=1,verdict='secret',engine_return=True,order_before=-1,order_after=2**32))
        self.assertEqual(row,dict(native_status=1,verdict=None,engine_return=None,order_before=None,order_after=None))

    def test_diagnostic_write_failure_does_not_resend_and_close_releases_both_streams(self):
        original=self.executor.write_diagnostic
        def broken(*args,**kwargs):raise OSError('diagnostic disk failure')
        self.executor.write_diagnostic=broken
        with self.assertRaisesRegex(OSError,'diagnostic disk failure'):
            self.run_action(action('stop',unit=[11,7]))
        self.assertEqual(self.native.call_count,1)
        self.executor.write_diagnostic=original
        self.executor.close()
        self.assertTrue(self.executor.stream.closed)
        self.assertTrue(self.executor.diagnostics.closed)


if __name__=='__main__':unittest.main()
