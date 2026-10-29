"""Pinned KFAI LR observer derivative. Keep all original assets and AI scripts."""
import hashlib
import json
import re

from bootstrap import ROOT
from extract_map_pool import extract
from sparring_map import lobby_metadata, replace_members, scenario_header, scenario_script
from w3mpq import Mpq

SOURCE = ROOT / 'vendor/kfai-v1.30b/LR-no-multirace.w3x'
SOURCE_SHA = '8d573b1b098209652dd61890df665408e0bce1a848956854ff9d24b3594f69bd'


def patch_script(script, starts):
    original_init = 'Trig________________uActions'
    standard_init = 'Trig_Melee_Initialization_Actions'
    if script.count('function ' + original_init + ' takes') != 1:
        raise ValueError('Unexpected KFAI melee initialization')
    patched = scenario_script(script.replace(original_init, standard_init), starts).decode('utf-8')
    patched = patched.replace(standard_init, original_init)
    # Keep both participants in active computer slots. Gate the separate hero AI,
    # which upstream otherwise enables for every computer independent of Melee_AI_On.
    old = 'GetPlayerController(GetOwningPlayer(hero)) == MAP_CONTROL_COMPUTER and IsUnitInGroup(hero, AIsystem___group_AI_hero) == false'
    if patched.count(old) != 1:
        raise ValueError('Unexpected KFAI hero AI registration')
    patched = patched.replace(old, 'AIsystem___Melee_AI_On[GetPlayerId(GetOwningPlayer(hero))] == true and ' + old)
    def function(name, body):
        nonlocal patched
        patched, count = re.subn(r'function ' + name + r' takes nothing returns nothing\b.*?endfunction',
                                 'function ' + name + ' takes nothing returns nothing\n' + body + '\nendfunction',
                                 patched, flags=re.S)
        if count != 1:
            raise ValueError('Unexpected KFAI function: ' + name)
    function('MeleeAIsystem_Start', '    call AIsystem_SetAIplayer(Player(1), false)\n    call AIsystem_SetAIplayer(Player(2), true)\n    call AIsystem_melee_ai_Init()')
    # The existing owned runner judges buildings. Original melee defeat would defeat empty OB.
    function('Trig_SuccessFailureActions', '    // Building-elimination referee belongs to the owned runner.')
    marker = '    // No native AI scripts. The owned runner arbitrates building-elimination victory.'
    if patched.count(marker) != 1:
        raise ValueError('Missing native AI insertion point')
    patched = patched.replace(marker, '''    set udg_R_Global_Player_Group=GetPlayersAll()
    call ForForce(udg_R_Global_Player_Group, function Trig________________uFunc013A)
    call StartMeleeAI(Player(2), "human.ai")
    // Only P2 runs native KFAI; P1 remains controlled by dayuan.''')
    return patched.encode('utf-8')


def prepare_map(alias='LR', strategy_trace=False):
    if alias != 'LR':
        raise ValueError('KFAI observer probe supports LR only')
    blob = SOURCE.read_bytes()
    if hashlib.sha256(blob).hexdigest() != SOURCE_SHA:
        raise ValueError('KFAI source fingerprint mismatch')
    catalog = extract(SOURCE, alias)
    archive = Mpq(blob)
    starts = sorted(catalog['starts'], key=lambda s: s['slot'])
    members = {'war3map.j': patch_script(archive.read('war3map.j').decode('utf-8'), starts),
               'war3map.w3i': lobby_metadata(archive.read('war3map.w3i'), starts)}
    if strategy_trace:
        from kfai_strategy import patch_human_ai, HUMAN_AI_MEMBER
        members[HUMAN_AI_MEMBER] = patch_human_ai(archive.read(HUMAN_AI_MEMBER))
    result = scenario_header(replace_members(blob, members))
    digest = hashlib.sha256(result).hexdigest()
    folder = ROOT / 'artifacts/sparring-maps'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('LR-kfai-observer-' + digest[:16] + '.w3x')
    if not target.exists():
        target.write_bytes(result)
    if target.read_bytes() != result:
        raise RuntimeError('KFAI observer copy differs from expected bytes')
    derived = {**catalog, 'map_sha256': digest, 'source_map_sha256': SOURCE_SHA,
               'source_map_path': str(SOURCE), 'scenario': 'kfai_observer_sparring',
               'script_sha256': hashlib.sha256(members['war3map.j']).hexdigest(),
               'opponent_fairness': 'native_KFAI_unverified',
               'victory': 'runner_all_enemy_buildings_destroyed'}
    if strategy_trace:
        derived['strategy_trace'] = dict(schema='kfai-strategy-trace-v1', live_verified=False,
                                        human_ai_sha256=hashlib.sha256(members[HUMAN_AI_MEMBER]).hexdigest())
    target.with_suffix('.json').write_text(json.dumps(derived, ensure_ascii=False, indent=2), encoding='utf-8')
    return target, derived
