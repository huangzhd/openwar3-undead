"""Build a relocatable Windows training zip from the verified local dependencies."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import zipfile

from training_launcher import UPSTREAM_NAME, RUNTIME, digest

ROOT=Path(__file__).resolve().parent


def copy_tree(source, destination):
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'),dirs_exist_ok=True)


def upstream_files(archive, destination):
    with tarfile.open(archive,'r:gz') as tar:
        for entry in tar:
            parts=PurePosixPath(entry.name).parts
            if not parts or parts[0]!=UPSTREAM_NAME:raise ValueError('Unexpected upstream archive root')
            relative=PurePosixPath(*parts[1:])
            if '..' in relative.parts or relative.is_absolute():raise ValueError('Unsafe archive path')
            if not entry.isfile():continue
            if (relative.parts[0] in {'bin','.git'} or relative.as_posix().startswith('data/game/')
                    or relative.name=='openwar3.json' or relative.suffix in {'.log','.pyc'}):continue
            target=destination.joinpath(*relative.parts);target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(entry) as stream, target.open('wb') as output:shutil.copyfileobj(stream,output)


def portable_python(destination):
    base=Path(sys.base_prefix)
    if sys.platform!='win32' or sys.maxsize<=2**32:raise RuntimeError('Build with 64-bit Windows Python')
    destination.mkdir(parents=True)
    for name in ('python.exe','pythonw.exe','python3.dll',f'python{sys.version_info.major}{sys.version_info.minor}.dll',
                 'vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        shutil.copy2(base/name,destination/name)
    for name in ('DLLs','tcl'):copy_tree(base/name,destination/name)
    shutil.copytree(base/'Lib',destination/'Lib',ignore=shutil.ignore_patterns(
        '__pycache__','*.pyc','site-packages','test','tests','idlelib','ensurepip'))
    site=destination/'Lib/site-packages';site.mkdir()
    packages={}
    for name in ('mpyq','numpy','pillow','psutil'):
        dist=importlib.metadata.distribution(name);packages[name]=dist.version
        origin=Path(dist.locate_file('')).resolve()
        for entry in dist.files or ():
            source=Path(dist.locate_file(entry)).resolve()
            if not source.is_relative_to(origin) or not source.is_file():continue
            relative=source.relative_to(origin)
            if '__pycache__' in relative.parts or source.suffix in {'.pyc','.pyo'}:continue
            target=site/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    return packages


def build(output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    destination=output/'dayuan-training';destination.mkdir()
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
    included=set()
    for name in tracked:
        path=Path(name)
        if ((len(path.parts)==1 and path.suffix=='.py') or
                (path.parts and path.parts[0]=='undead' and path.suffix=='.py') or
                (path.parts and path.parts[0]=='data' and path.suffix=='.json' and path.name!='machine_profiles.json')):
            included.add(path)
    included.update(map(Path,('training_launcher.py','start-training.cmd','requirements-p0.lock')))
    # New source modules are explicit; untracked personal files are never swept into a release.
    for relative in sorted(included):
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    shutil.copy2(ROOT/'start-training.cmd',destination/'启动训练.cmd')
    # A valid empty machine profile table is enough for training-only imports.
    (destination/'data/machine_profiles.json').write_text('{}\n',encoding='utf-8')
    shutil.copy2(ROOT/'docs/FRIEND_TRAINING.md',destination/'使用说明.txt')
    (destination/'THIRD_PARTY.txt').write_text(
        'OpenWar3AI ffd7dd25a3c2478f457b74bde89d23e605b24243: see vendor/'+UPSTREAM_NAME+'/LICENSE and NOTICE.\n'
        'Runtime binaries are redistributed unchanged; their hashes are checked at startup.\n'
        'Python: see python/LICENSE.txt. Package licenses are in python/Lib/site-packages/*.dist-info.\n'
        'StormLib 9.40: see vendor/StormLib-9.40/LICENSE.\n'
        'UD V61 training map: https://github.com/ufo19890607/Warcraft-III-/blob/'
        '71c0e1fdafc3cd523cbbd7feb7f3570d3de020c2/converted-1.27/UD-decisive-V61-1.27.w3x\n'
        'The unmodified training map retains its original credits.\n'
        'Game executable, Game.dll, MPQs and extracted Blizzard tables are NOT included.\n',encoding='utf-8')
    packages=portable_python(destination/'python')
    upstream=destination/'vendor'/UPSTREAM_NAME
    upstream_files(ROOT/'vendor/openwar3-pinned.tar.gz',upstream)
    for name, expected in RUNTIME.items():
        if digest(upstream/'prebuilt'/name)!=expected:raise ValueError('Unverified runtime: '+name)
    for relative in ('StormLib-9.40/x64/StormLib.dll','StormLib-9.40/LICENSE',
                     'ud-decisive/converted-1.27/UD-decisive-V61-1.27.w3x'):
        target=destination/'vendor'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'vendor'/relative,target)
    manifest=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  python=sys.version,packages=packages,upstream=UPSTREAM_NAME,
                  files={p.relative_to(destination).as_posix():digest(p) for p in sorted(destination.rglob('*')) if p.is_file()})
    (destination/'bundle-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=output/'dayuan-training.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zip:
        for path in sorted(destination.rglob('*')):
            if path.is_file():zip.write(path,path.relative_to(output).as_posix())
    print(json.dumps(dict(zip=str(archive),bytes=archive.stat().st_size,sha256=digest(archive),
                          unpacked=str(destination),files=len(manifest['files'])),ensure_ascii=False,indent=2))
    return archive


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
