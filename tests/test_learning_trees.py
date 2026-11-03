import copy
import json
import unittest
from types import MethodType, SimpleNamespace as N
from unittest.mock import Mock, patch

import bootstrap
import w3world
from openwar3 import Game
from learning.actions import preflight
from learning.trajectory import BoundaryError
import test_learning_actions as helpers
from test_learning_actions import action


class TreePrimitiveTests(unittest.TestCase):
    run_action=helpers.PrimitiveTests.run_action
    rows=helpers.PrimitiveTests.rows

    def setUp(self):
        helpers.PrimitiveTests.setUp(self)
        self.own.type='ugho'
        self.own.abilities.append(N(code='Ahrl',level=1,cooldown=0))
        self.tree=w3world.Tree(100077,77,7,'LTlt',64.,64.,100.)
        self.hidden_tree=w3world.Tree(100088,88,7,'LTlt',128.,64.,100.)
        self.game.world.trees=Mock(return_value=[self.tree,self.hidden_tree])
        self.game.visible.side_effect=lambda x,y:x!=128
        self.game.gather=MethodType(Game.gather,self.game)
        p=patch('w3world.tree_types',return_value={'LTlt'});p.start();self.addCleanup(p.stop)
        self.refresh()

    def refresh(self):
        self.raw.clock+=.1;self.raw.publish_count+=1;self.rec.observe()
        self.decision=copy.deepcopy(self.rec.last_observation)

    def scan(self):
        result=self.run_action(action('inspect_trees',x=0,y=0));self.refresh();return result

    def test_explicit_scan_reads_only_visible_geometry_and_never_submits(self):
        receipt=self.scan()
        self.assertEqual(receipt['status'],'observation_only');self.assertIsNone(receipt['accepted'])
        self.native.assert_not_called()
        self.game.world.trees.assert_called_with(alive=False)
        self.assertEqual(self.decision['tree_sightings'],[dict(handle=[77,7],type='LTlt',x=64.,y=64.,seen_clock=10.1)])
        data=json.dumps(self.decision['tree_sightings'])
        self.assertNotIn('life',data);self.assertNotIn('addr',data);self.assertNotIn('100088',data)

    def test_hidden_life_death_and_removal_do_not_change_sightings(self):
        self.scan();first=self.rec.trees.rows()
        # Keep the clock fixed to isolate hidden state changes.
        for life in (0,-100,100000):
            self.hidden_tree.life=life
            self.rec.trees.scan(0,0)
            expected=copy.deepcopy(first);expected[0]['seen_clock']=self.raw.clock
            self.assertEqual(self.rec.trees.rows(),expected)
        self.game.world.trees.return_value=[self.tree]
        self.rec.trees.scan(0,0);self.assertEqual(self.rec.trees.rows(),expected)

    def test_hidden_tree_life_is_not_read_even_if_accessor_would_fail(self):
        class Hidden:
            handle_lo=88;handle_hi=7;type='LTlt';x=128.;y=64.
            @property
            def life(self):raise AssertionError('Read hidden life')
        self.game.world.trees.return_value=[self.tree,Hidden()]
        self.scan()
        self.assertEqual(len(self.decision['tree_sightings']),1)

    def test_lumber_dispatch_links_tree_target_without_address_or_life_leak(self):
        self.scan()
        result=self.run_action(action('gather_lumber',unit=[11,7],target=[77,7]))
        self.assertTrue(result['accepted']);self.assertEqual(result['native_request_ids'],[1])
        self.assertEqual(self.native.call_args.args[0][0].args[4:7],[100077,77,7])
        rows=[json.loads(s) for s in (self.path/'trajectory.jsonl').read_text().splitlines()]
        request=next(r for r in rows if r['event']=='action_request')
        self.assertTrue(request['eligible']);self.assertEqual(request['action']['target_kind'],'tree')
        self.assertEqual(request['action']['target'],[77,7]);self.assertNotIn('100077',json.dumps(rows))
        self.assertEqual(rows[0]['schema'],'dayuan-trajectory-v2')

    def test_hidden_unseen_dead_stale_and_wrong_worker_targets_rejected(self):
        value=action('gather_lumber',unit=[11,7],target=[77,7])
        self.assertEqual(self.run_action(value)['reason'],'tree_not_observed')
        self.scan();self.game.visible.side_effect=lambda x,y:False
        self.assertEqual(self.run_action(value)['reason'],'tree_no_longer_visible')
        self.game.visible.side_effect=lambda x,y:True;self.tree.life=0
        self.assertEqual(self.run_action(value)['reason'],'tree_not_alive')
        self.tree.life=100;self.raw.clock+=9;self.refresh()
        self.assertEqual(self.run_action(value)['reason'],'tree_sighting_stale')
        self.scan();self.own.type='uaco';self.refresh()
        self.assertEqual(self.run_action(value)['reason'],'source_cannot_gather_lumber')
        self.native.assert_not_called()

    def test_query_invisible_or_outside_point_is_rejected_without_reading_trees(self):
        self.game.visible.side_effect=lambda *a:None
        self.assertEqual(self.run_action(action('inspect_trees',x=0,y=0))['reason'],'tree_query_point_not_visible')
        self.assertEqual(self.run_action(action('inspect_trees',x=1001,y=0))['reason'],'point_outside_map')
        self.game.world.trees.assert_not_called();self.native.assert_not_called()

    def test_hidden_death_does_not_erase_previous_visible_sighting(self):
        self.scan();first=self.rec.trees.rows()
        self.game.visible.side_effect=lambda x,y:(x,y)==(0,0)
        self.tree.life=0;self.game.world.trees.return_value=[]
        self.rec.trees.scan(0,0)
        self.assertEqual(self.rec.trees.rows(),first)

    def test_epoch_change_during_visibility_query_fails_before_any_command(self):
        def changed(x,y):self.raw.epoch+=1;return True
        self.game.visible.side_effect=changed
        with self.assertRaises(BoundaryError):self.scan()
        self.native.assert_not_called()

    def test_unknown_catalog_does_not_treat_all_destructibles_as_trees(self):
        with patch('w3world.tree_types',return_value=set()),self.assertRaisesRegex(RuntimeError,'catalog'):
            self.scan()
        self.native.assert_not_called()


if __name__=='__main__':unittest.main()
