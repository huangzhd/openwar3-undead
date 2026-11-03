import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import build_training_bundle as bundle


class BundleSourceTests(unittest.TestCase):
    def test_archive_contains_learning_dependencies_but_not_private_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'repo';root.mkdir()
            tracked=['run_match.py','learning/__init__.py','learning/outcome.py','learning/model_codec.py',
                     'undead/__init__.py','data/version.json','data/machine_profiles.json']
            assets=['training_launcher.py','portable_game_data.py','start-training.cmd','requirements-p0.lock',
                    'docs/FRIEND_TRAINING.md','vendor/StormLib-9.40/x64/StormLib.dll',
                    'vendor/StormLib-9.40/LICENSE','vendor/ud-decisive/converted-1.27/UD-decisive-V61-1.27.w3x']
            for name in tracked+assets+['learning/private_model.py','private.env']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
            (root/'run_match.py').write_text('from learning.outcome import classify_outcome\n')
            def git(args,**kwargs):return ('\0'.join(tracked)+'\0').encode() if 'ls-files' in args else 'abcdef\n'
            with patch.object(bundle,'ROOT',root),patch.object(bundle,'RUNTIME',{}),\
                 patch.object(bundle,'portable_python',return_value={}),patch.object(bundle,'upstream_files'),\
                 patch.object(bundle.subprocess,'check_output',side_effect=git):
                archive=bundle.build(Path(directory)/'out')
            with zipfile.ZipFile(archive) as zipped:
                names=zipped.namelist()
                self.assertIn('dayuan-training/learning/outcome.py',names)
                self.assertIn('dayuan-training/learning/model_codec.py',names)
                self.assertIn('dayuan-training/portable_game_data.py',names)
                self.assertNotIn('dayuan-training/learning/private_model.py',names)
                self.assertNotIn('dayuan-training/private.env',names)
                manifest=json.loads(zipped.read('dayuan-training/bundle-manifest.json'))
                self.assertIn('learning/outcome.py',manifest['files'])
                self.assertEqual(json.loads(zipped.read('dayuan-training/data/machine_profiles.json')), {})

if __name__=='__main__':unittest.main()
