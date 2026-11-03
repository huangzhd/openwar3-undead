import copy,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from learning import teacher_corpus as corpus
from learning.dataset import DatasetError


class TeacherCorpusTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.out=self.root/'out'
        self.train=self.root/'short';self.val=self.root/'long'
        def group(tick,state,op):
            return dict(tick=tick,observation_id=tick,input=dict(clock=state/3600),
                        omitted_requests=0,labels=[dict(request=tick,decision=dict(op=op))])
        self.groups={'short':[group(1,20,0),group(2,40,0)],'long':[group(1,20,1),group(2,800,1)]}
        def read(folder):
            groups=self.groups[folder.name]
            return dict(episode=folder.name,termination={},input_hashes={'trajectory.jsonl':folder.name},
                        ticks=len(groups),monitored_requests=len(groups),labels=len(groups),excluded={},
                        model_contract={'operations':['move','attack']}),groups
        for name,fn in [('audit_episode',read),('provenance',lambda *a:dict(map_sha256='same'))]:
            p=patch.object(corpus,name,side_effect=fn);p.start();self.addCleanup(p.stop)

    def test_holdout_kept_whole_duplicate_inputs_removed_from_train_only(self):
        idx=corpus.build([self.train],[self.val],self.out)
        load=lambda name:[json.loads(l) for l in (self.out/(name+'.jsonl')).read_text().splitlines()]
        self.assertEqual([(r['episode'],r['tick']) for r in load('train')],[('short',2)])
        self.assertEqual([r['tick'] for r in load('validation')],[1,2])
        self.assertEqual(idx['heldout_operations_absent_from_train'],['attack'])
        self.assertEqual(idx['splits']['train']['excluded_cross_split_groups'],1)
        self.assertEqual(corpus.verify([self.train],[self.val],self.out),idx)
        with self.assertRaisesRegex(DatasetError,'already_exists'):corpus.build([self.train],[self.val],self.out)
        (self.out/'validation.jsonl').write_bytes(b'{}\n')
        with self.assertRaisesRegex(DatasetError,'corpus_data_mismatch'):corpus.verify([self.train],[self.val],self.out)

    def test_renamed_copy_and_same_episode_are_refused_before_publication(self):
        with self.assertRaisesRegex(DatasetError,'duplicate_episode_identity'):corpus.build([self.val],[self.val],self.out)
        self.groups['short']=copy.deepcopy(self.groups['long'])
        with self.assertRaisesRegex(DatasetError,'duplicate_encoded_episode'):corpus.build([self.train],[self.val],self.out)
        self.assertFalse(self.out.exists())

    def test_incompatible_rules_cannot_be_silently_pooled(self):
        with patch.object(corpus,'provenance',side_effect=lambda p,r:dict(rules=p.name)):
            with self.assertRaisesRegex(DatasetError,'incompatible_episode_provenance'):
                corpus.build([self.train],[self.val],self.out)
        self.assertFalse(self.out.exists())

    def test_changing_split_claim_is_detected_against_preregistered_sources(self):
        corpus.build([self.train],[self.val],self.out)
        with self.assertRaisesRegex(DatasetError,'corpus_index_mismatch'):corpus.verify([self.val],[self.train],self.out)
