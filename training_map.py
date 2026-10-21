"""Pinned UD V61 map and reproducible single-round adapter; originals stay intact."""
import hashlib
import json
import re
import ctypes
import tempfile
import zipfile
import io
import urllib.request
from pathlib import Path

from bootstrap import ROOT
from w3mpq import Mpq

COMMIT = '71c0e1fdafc3cd523cbbd7feb7f3570d3de020c2'
SOURCE = 'converted-1.27/UD-decisive-V61-1.27.w3x'
SHA256 = 'bc10e7835f7a99e4c6e678bb9aae3193cb2149694ecec666af1df9d970897718'
VERSION = 'ud-training-0.1.0'
MATCHUPS = {'human': 1, 'orc': 2, 'undead': 3, 'nightelf': 4}
ORIGINAL = ROOT / 'vendor/ud-decisive' / SOURCE


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def source_map(download=False):
    if not ORIGINAL.exists() and download:
        url = f'https://raw.githubusercontent.com/ufo19890607/Warcraft-III-/{COMMIT}/{SOURCE}'
        with urllib.request.urlopen(url, timeout=30) as response:
            blob = response.read(2_000_001)
        if digest(blob) != SHA256:
            raise ValueError('Downloaded training map fingerprint mismatch')
        ORIGINAL.parent.mkdir(parents=True, exist_ok=True)
        ORIGINAL.write_bytes(blob)
    blob = ORIGINAL.read_bytes()
    if digest(blob) != SHA256:
        raise ValueError('Original training map fingerprint mismatch')
    return blob


STORM_ZIP_SHA = 'b2c9635e7b63edee1bd7c82e7dc180d739f3accb2b8994804c7774e464ce89ae'
STORM_DLL_SHA = '93321f6f030be5d7d79eb4cbf433d6ef7e83ce20d47d8963717f207d54afbe16'
STORM_DLL = ROOT / 'vendor/StormLib-9.40/x64/StormLib.dll'


def stormlib(download=False):
    if not STORM_DLL.exists() and download:
        url = 'https://github.com/ladislav-zezula/StormLib/releases/download/v9.40/stormlib_dll.zip'
        with urllib.request.urlopen(url, timeout=60) as response:
            blob = response.read(4_000_001)
        if digest(blob) != STORM_ZIP_SHA:
            raise ValueError('StormLib download fingerprint mismatch')
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            dll = archive.read('x64/StormLib.dll')
        if digest(dll) != STORM_DLL_SHA:
            raise ValueError('StormLib DLL fingerprint mismatch')
        STORM_DLL.parent.mkdir(parents=True, exist_ok=True)
        STORM_DLL.write_bytes(dll)
    if digest(STORM_DLL.read_bytes()) != STORM_DLL_SHA:
        raise ValueError('StormLib DLL fingerprint mismatch')
    lib = ctypes.WinDLL(str(STORM_DLL), use_last_error=True)
    ptr, uint, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool
    specs = {
        'SFileOpenArchive': [ctypes.c_wchar_p, uint, uint, ctypes.POINTER(ptr)],
        'SFileCreateFile': [ptr, ctypes.c_char_p, ctypes.c_uint64, uint, uint, uint, ctypes.POINTER(ptr)],
        'SFileWriteFile': [ptr, ptr, uint, uint],
        'SFileFinishFile': [ptr],
        'SFileCloseArchive': [ptr],
    }
    for name, types in specs.items():
        fn = getattr(lib, name); fn.argtypes = types; fn.restype = boolean
    return lib


def replace_script(blob, script):
    """Use StormLib sector compression and archive bookkeeping for WC3 1.27."""
    lib = stormlib()
    with tempfile.TemporaryDirectory(prefix='ud-training-') as temp:
        path = Path(temp) / 'adapted.w3x'
        path.write_bytes(blob)
        archive, file = ctypes.c_void_p(), ctypes.c_void_p()
        def require(ok):
            if not ok:
                raise OSError(ctypes.get_last_error(), 'StormLib map update failed')
        require(lib.SFileOpenArchive(str(path), 0, 0, ctypes.byref(archive)))
        try:
            # COMPRESS | REPLACEEXISTING, fixed timestamp for reproducible maps.
            require(lib.SFileCreateFile(archive, b'war3map.j', 0, len(script), 0,
                                       0x80000200, ctypes.byref(file)))
            try:
                require(lib.SFileWriteFile(file, ctypes.c_char_p(script), len(script), 2))
            finally:
                require(lib.SFileFinishFile(file))
        finally:
            require(lib.SFileCloseArchive(archive))
        result = path.read_bytes()
    if Mpq(result).read('war3map.j') != script:
        raise ValueError('Derived script roundtrip failed')
    return result


def patch_script(script, matchup, level, mode):
    if matchup not in MATCHUPS or not 1 <= level <= 10 or mode not in ('easy', 'hard'):
        raise ValueError('Invalid training selection')
    # Latin-1 preserves the upstream mixed-encoding source byte for byte.
    text = script.decode('latin-1')
    def edit(name, transform):
        nonlocal text
        pattern = r'function ' + re.escape(name) + r' takes nothing returns nothing\r?\n(.*?)endfunction'
        matches = list(re.finditer(pattern, text, re.S))
        if len(matches) != 1:
            raise ValueError('Missing or duplicate pinned function: ' + name)
        m = matches[0]
        text = text[:m.start(1)] + transform(m.group(1)) + text[m.end(1):]

    def initialize(body):
        start = body.index('    call DialogClearBJ( udg_DefeatDialog )')
        end = body.index('    loop\n', start) if '    loop\n' in body[start:] else body.index('    loop\r\n', start)
        choice = (f'    set udg_P1Race = 3\n    set udg_P2Race = {MATCHUPS[matchup]}\n'
                  f'    set udg_Hardcore = {str(mode == "hard").lower()}\n'
                  '    call ConditionalTriggerExecute( gg_trg_CourseName )\n'
                  '    call TriggerSleepAction( 0.01 )\n'
                  f'    set udg_RoundNo = {level}\n    call TriggerExecute( gg_trg_Main )\n')
        return body[:start] + choice + body[end:]
    edit('Trig_Initialiaztion_Actions', initialize)
    # Public scoreboard is the adapter protocol; no hidden opponent data.
    edit('Trig_Main_Actions', lambda body: body +
         '    call LeaderboardSetLabel(PlayerGetLeaderboard(Player(0)), "OWT:waiting")\n')
    def countdown(body):
        needle = 'set udg_Counting = false'
        if body.count(needle) != 2:
            raise ValueError('Unexpected countdown implementation')
        return body.replace(needle, needle + '\n            call LeaderboardSetLabel(PlayerGetLeaderboard(Player(0)), "OWT:battle")')
    edit('Trig_ComputerForceCountdown_Actions', countdown)
    # Keep original Player1Win/Player2Win conditions and scoring. Stop only
    # auto-advance, unit removal and menus after the map has adjudicated.
    edit('Trig_CheckPass_Actions', lambda body:
         '    set udg_RoundOver = true\n'
         '    call LeaderboardSetLabel(PlayerGetLeaderboard(Player(0)), "OWT:result:" + I2S(udg_win))\n'
         '    call DisplayTimedTextToForce(GetPlayersAll(), 60.0, "OWT single round complete; winner slot " + I2S(udg_win - 1))\n')
    return text.encode('latin-1')


def build(matchup='orc', level=2, mode='easy', download=False):
    blob = source_map(download)
    stormlib(download)
    original = Mpq(blob)
    script = patch_script(original.read('war3map.j'), matchup, level, mode)
    adapted = replace_script(blob, script)
    # Verify all original named resources, including terrain and object data.
    names = (original.read('(listfile)') or b'').decode('utf-8', errors='replace').splitlines()
    if not names:
        raise ValueError('Pinned map has no resource list')
    derived = Mpq(adapted)
    for name in names:
        if name.lower() not in ('war3map.j', '(attributes)') and original.read(name) != derived.read(name):
            raise ValueError('Unexpected resource change: ' + name)
    out = ROOT / 'artifacts/training-maps' / f'ud-v61-{matchup}-{level}-{mode}.w3x'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(adapted)
    manifest = dict(adapter_version=VERSION, source_commit=COMMIT, source_path=SOURCE,
                    source_sha256=SHA256, map_sha256=digest(adapted),
                    script_sha256=digest(script), matchup=matchup, level=level, mode=mode,
                    preserved_resources=len(names), map_path=str(out))
    out.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return out, manifest
