"""Public catalogs bound to exact local map bytes, independent of default_map."""
import hashlib,json
from pathlib import Path
from bootstrap import ROOT,UPSTREAM

def pool():
    path=ROOT/'data/kk_map_pool.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

def resolve_map(alias):
    data=pool()
    key=alias.upper()
    if key not in data:raise ValueError('Unknown map alias: '+alias)
    config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
    path=Path(config['game_dir'])/'Maps/dz/versus'/data[key]['file']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=data[key]['map_sha256']:
        raise ValueError('Map missing or fingerprint changed: '+str(path))
    return path,data[key]

def catalog_for_path(path):
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return next((d for d in pool().values() if d['map_sha256']==digest),None)
