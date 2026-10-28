import unittest
from types import SimpleNamespace as N
from unittest.mock import Mock, call

from undead.debug_console import ActionMeter
from tests import test_attach_0155 as attachment_fixture


class CommandTraceTests(unittest.TestCase):
    def game(self, sender):
        names = ('point', 'target', 'immediate', 'build', 'learn', 'use_item',
                 'revive', 'rally', 'buy', 'item_drop')
        return N(clock=Mock(return_value=100), _snap=N(clock=100.125),
                 lane=N(commands=sender),
                 _w3fast=N(OP={name: index + 1 for index, name in enumerate(names)}))

    def test_mixed_batch_logs_actions_without_changing_delivery_or_receipts(self):
        events = []
        chronology = []
        calls = [N(op=1, args=[10, 1, 2, 851986, 0, 0, 0, 100, 200, 0, 1]),
                 N(op=22, args=[0, 0, 0]),
                 N(op=9, args=[20, 3, 4, 1919837539]),
                 N(op=2, args=[10, 1, 2, 851971, 30, 5, 6])]
        original_args = [list(call.args) for call in calls]
        receipts = [N(ok=True, reason='accepted', faulted=0, ret=1, order_after=851986),
                    N(ok=True),
                    N(ok=True, reason='accepted', faulted=0, ret=1, order_after=0),
                    N(ok=False, reason='invalid_target', faulted=0, ret=0, order_after=851986)]

        def send(batch, *args, **kwargs):
            chronology.append('send')
            self.assertIs(batch, calls)
            self.assertEqual(args, ('marker',))
            self.assertEqual(kwargs, {'timeout': .8})
            self.assertEqual([call.args for call in batch], original_args)
            g.clock.return_value = 100.5
            return receipts

        sender = Mock(side_effect=send)
        g = self.game(sender)

        def trace(event, **data):
            chronology.append(event)
            events.append((event, data))

        meter = ActionMeter(g, trace=trace)
        returned = g.lane.commands(calls, 'marker', timeout=.8)
        self.assertIs(returned, receipts)
        self.assertEqual(chronology, ['attachment_commands_submitted', 'send',
                                      'attachment_commands_completed'])
        self.assertEqual(sender.call_count, 1)  # An audit must never replay an order.
        self.assertEqual(g.clock.call_count, 2)  # Constructor and the original post-send read only.
        submitted, completed = events[0][1], events[1][1]
        self.assertEqual(submitted['clock'], 100.125)
        self.assertEqual(submitted['clock_basis'], 'cached_snapshot')
        self.assertEqual(completed['clock'], 100.5)
        self.assertEqual(submitted['batch_id'], completed['batch_id'])
        self.assertEqual(submitted['commands'], [
            {'index': 0, 'op': 'point', 'args': original_args[0]},
            {'index': 2, 'op': 'buy', 'args': original_args[2]},
            {'index': 3, 'op': 'target', 'args': original_args[3]}])
        self.assertEqual([(r['index'], r['ok'], r['reason']) for r in completed['receipts']],
                         [(0, True, 'accepted'), (2, True, 'accepted'), (3, False, 'invalid_target')])
        self.assertEqual(completed['receipts'][2]['order_after'], 851986)
        self.assertEqual(meter.total, 2)
        self.assertEqual([call.args for call in calls], original_args)

    def test_query_only_batch_has_no_action_trace_and_no_action_count(self):
        receipts = [N(ok=True)]
        sender = Mock(return_value=receipts)
        trace = Mock()
        g = self.game(sender)
        meter = ActionMeter(g, trace=trace)
        calls = [N(op=22, args=[1, 2])]
        self.assertIs(g.lane.commands(calls, timeout=.3), receipts)
        sender.assert_called_once_with(calls, timeout=.3)
        trace.assert_not_called()
        self.assertEqual(meter.total, 0)

    def test_sender_failure_preserves_original_exception_without_completion_or_retry(self):
        failure = TimeoutError('command lane stopped')
        sender = Mock(side_effect=failure)
        events = []
        g = self.game(sender)
        del g._snap
        meter = ActionMeter(g, trace=lambda event, **data: events.append((event, data)))
        calls = [N(op=9, args=[20, 3, 4, 1919837539])]
        with self.assertRaises(TimeoutError) as caught:
            g.lane.commands(calls, timeout=.7)
        self.assertIs(caught.exception, failure)
        sender.assert_called_once_with(calls, timeout=.7)
        self.assertEqual([event for event, _ in events],
                         ['attachment_commands_submitted', 'attachment_commands_failed'])
        self.assertEqual(events[0][1]['clock'], 100)
        self.assertEqual(events[0][1]['batch_id'], events[1][1]['batch_id'])
        self.assertEqual(events[1][1]['error'], repr(failure))
        self.assertEqual(meter.total, 0)

    def test_trace_failure_disables_logging_but_delivers_orders_once(self):
        for failing_event in ('attachment_commands_submitted', 'attachment_commands_completed'):
            with self.subTest(failing_event=failing_event):
                failure = OSError('trace disk unavailable')
                seen = []

                def trace(event, **data):
                    seen.append(event)
                    if event == failing_event:
                        raise failure

                receipts = [N(ok=True)]
                sender = Mock(return_value=receipts)
                g = self.game(sender)
                meter = ActionMeter(g, trace=trace)
                calls = [N(op=1, args=[10, 1, 2, 851986])]
                self.assertIs(g.lane.commands(calls), receipts)
                events_at_failure = list(seen)
                self.assertIs(g.lane.commands(calls), receipts)
                self.assertEqual(seen, events_at_failure)
                self.assertEqual(sender.call_args_list, [call(calls), call(calls)])
                self.assertEqual(meter.total, 2)
                self.assertEqual(meter.trace_error, repr(failure))
                self.assertEqual(meter.summary(101)['command_trace_error'], repr(failure))

    def test_trace_failure_does_not_replace_sender_failure(self):
        failure = RuntimeError('original transport failure')
        sender = Mock(side_effect=failure)
        trace = Mock(side_effect=OSError('trace failure'))
        g = self.game(sender)
        meter = ActionMeter(g, trace=trace)
        calls = [N(op=1, args=[])]
        with self.assertRaises(RuntimeError) as caught:
            g.lane.commands(calls)
        self.assertIs(caught.exception, failure)
        self.assertEqual(meter.total, 0)
        sender.assert_called_once_with(calls)

    def test_default_meter_keeps_original_sender_and_summary_contract(self):
        receipts = [N(ok=True)]
        sender = Mock(return_value=receipts)
        g = self.game(sender)
        meter = ActionMeter(g)
        # Existing SDK test doubles need not provide audit-only attributes.
        calls = [N(op=1)]
        self.assertIs(g.lane.commands(calls), receipts)
        self.assertNotIn('command_trace_error', meter.summary(101))
        self.assertEqual(meter.total, 1)
        meter.close()
        self.assertIs(g.lane.commands, sender)


class AttachmentObservationTests(unittest.TestCase):
    def test_system_hint_is_retained_before_departure_without_starting_bot(self):
        for terminal in ('player.left', 'game.ended'):
            with self.subTest(terminal=terminal):
                g, loop, bots, logs = attachment_fixture.AttachmentTests().setup()
                sender = Mock(side_effect=AssertionError('observation must not issue commands'))
                g.lane.commands = sender
                g.evs = [N(kind='message', clock=120.5, text='Game desynchronized', chat=None),
                         N(kind='message', clock=120.6, text='player chat', chat={'text': 'player chat'}),
                         N(kind=terminal, clock=121, player=4)]
                self.assertEqual(loop.step('resume', 0), 'game_or_local_player_left')
                evidence = [data for (event,), data in logs if event == 'attachment_game_event']
                self.assertEqual([(row['kind'], row['text']) for row in evidence],
                                 [('message', 'Game desynchronized'), (terminal, None)])
                self.assertEqual(evidence[0]['clock'], 120.5)
                self.assertFalse(bots)
                sender.assert_not_called()

    def test_first_owned_hero_is_observed_once_while_paused_without_orders(self):
        g, loop, bots, logs = attachment_fixture.AttachmentTests().setup()
        sender = Mock(side_effect=AssertionError('paused observation must not issue commands'))
        g.lane.commands = sender
        g.manual_skill_learning = True
        dk = N(is_hero=True, type='Udea', owner=4, alive=True, handle=(10, 20),
               level=1, skill_points=1, hp=675, mana=255, items=['stwp'] + [None] * 5)
        enemy = N(**{**vars(dk), 'owner': 1, 'handle': (11, 21)})
        dead = N(**{**vars(dk), 'alive': False, 'handle': (12, 22)})
        g.s.units = [g.u, dk, enemy, dead]
        for clock in (100, 100.5, 101):
            g.s.clock = clock
            g.s.publish_count += 1
            self.assertIsNone(loop.step('pause', clock))
        evidence = [data for (event,), data in logs if event == 'attachment_hero_observed']
        self.assertEqual([row['handle'] for row in evidence], [dk.handle])
        self.assertEqual(evidence[0]['items'], dk.items)
        self.assertEqual(evidence[0]['skill_points'], 1)
        self.assertTrue(evidence[0]['manual_skill_learning'])
        self.assertFalse(bots)
        self.assertTrue(loop.paused)
        sender.assert_not_called()
