"""Public map catalogs with separate, fingerprinted machine bindings."""
import hashlib
import json
from pathlib import Path
from bootstrap import ROOT, UPSTREAM


def pool():
    path = ROOT / 'data/kk_map_pool.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def profiles():
    return json.loads((ROOT / 'data/machine_profiles.json').read_text(encoding='utf-8'))


def profile_name(config):
    available = profiles()
    selected = config.get('undead_machine_profile')
    if selected:
        if selected not in available:
            raise ValueError('Unknown machine profile: ' + selected)
        return selected
    normalize = lambda value: str(value).replace('\\', '/').rstrip('/').casefold()
    matches = [name for name, row in available.items()
               if normalize(row['game_dir']) == normalize(config['game_dir'])]
    if len(matches) != 1:
        raise ValueError('Select this machine with start-local.ps1 or start-upstream.ps1')
    return matches[0]


def bound_catalog(alias, machine):
    catalogs = pool()
    key = alias.upper()
    if key not in catalogs:
        raise ValueError('Unknown map alias: ' + alias)
    binding = profiles()[machine].get('maps', {}).get(key, {})
    return dict(catalogs[key], **binding, machine_profile=machine)


def resolve_map(alias, config=None):
    if config is None:
        config = json.loads((UPSTREAM / 'openwar3.json').read_text(encoding='utf-8'))
    data = bound_catalog(alias, profile_name(config))
    path = Path(config['game_dir']) / 'Maps/dz/versus' / data['file']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != data['map_sha256']:
        raise ValueError('Map missing or fingerprint changed: ' + str(path))
    return path, data


def catalog_for_path(path):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    catalogs = pool()
    for machine, profile in profiles().items():
        for alias, row in catalogs.items():
            data = dict(row, **profile.get('maps', {}).get(alias, {}), machine_profile=machine)
            if data['map_sha256'] == digest:
                return dict(data, file=path.name)
    return None
