"""Generate a separate LR scenario: P0 spectator, P1 undead, P2 human.

Terrain, units, objects and drop tables remain byte-for-byte intact. Only the
map script and lobby metadata change. Never edit the registered source map.
"""
import hashlib
import json
import re
import struct
from bootstrap import ROOT
from w3mpq import Mpq, CT, mpq_hash
from undead.maps import resolve_map


def encrypt(data,key):
    seed=0xEEEEEEEE;out=[]
    for plain, in struct.iter_unpack('<I',data):
        seed=(seed+CT[0x400+(key&0xFF)])&0xFFFFFFFF
        out.append(plain^((key+seed)&0xFFFFFFFF))
        key=(((((~key)<<21)&0xFFFFFFFF)+0x11111111)|(key>>11))&0xFFFFFFFF
        seed=(plain+seed+(seed<<5)+3)&0xFFFFFFFF
    return struct.pack('<'+'I'*len(out),*out)


def replace_members(blob,members):
    """Append replacement members and relocate only the block table (MPQ v0)."""
    archive=Mpq(blob);base=archive.base
    header=struct.unpack_from('<IIHHIIII',blob,base+4)
    if header[2]!=0:raise ValueError('Only reviewed MPQ v0 maps are supported')
    out=bytearray(blob[:base+header[1]])
    blocks=bytearray(archive.block)
    for name,payload in members.items():
        a,b=mpq_hash(name,1),mpq_hash(name,2)
        matches=[bi for ha,hb,loc,platform,bi in struct.iter_unpack('<IIHHI',archive.hash)
                 if (ha,hb)==(a,b) and bi<0xFFFFFFFE]
        if len(matches)!=1:raise ValueError('Expected exactly one archive member: '+name)
        struct.pack_into('<IIII',blocks,matches[0]*16,len(out)-base,len(payload),len(payload),0x81000000)
        out.extend(payload)
    block_pos=len(out)-base
    out.extend(encrypt(blocks,mpq_hash('(block table)',3)))
    struct.pack_into('<I',out,base+8,len(out)-base)
    struct.pack_into('<I',out,base+20,block_pos)
    result=bytes(out);check=Mpq(result)
    if any(check.read(name)!=data for name,data in members.items()):raise RuntimeError('Map replacement verification failed')
    return result


def lobby_metadata(blob,starts):
    data=bytearray(blob);pos=12
    if struct.unpack_from('<I',data)[0]!=25:raise ValueError('Only reviewed W3I v25 maps are supported')
    def string():
        nonlocal pos
        pos=data.index(0,pos)+1
    for _ in range(4):string()
    pos+=8*4+4*4+2*4
    flags=struct.unpack_from('<I',data,pos)[0]
    struct.pack_into('<I',data,pos,(flags|16|32)&~4) # custom forces/fixed slots; scenario, not melee lobby
    pos+=5
    pos+=4
    for _ in range(4):string()
    pos+=4
    for _ in range(4):string()
    pos+=24;string();pos+=5
    player_start=pos
    n=struct.unpack_from('<I',data,pos)[0];pos+=4
    for _ in range(n):pos+=16;string();pos+=16
    force_count=struct.unpack_from('<I',data,pos)[0];pos+=4
    for _ in range(force_count):pos+=8;string()
    tail=data[pos:]
    rows=bytearray(struct.pack('<I',3))
    for slot,kind,race,label,start in [(0,1,1,'Observer',starts[0]),(1,2,3,'dayuan',starts[1]),(2,2,1,'Human opponent',starts[0])]:
        rows.extend(struct.pack('<4I',slot,kind,race,1)+label.encode()+b'\0')
        rows.extend(struct.pack('<ffII',start['x'],start['y'],0,0))
    rows.extend(struct.pack('<I',3))
    for slot,label in enumerate(('Observer','dayuan','Human opponent')):
        rows.extend(struct.pack('<II',0,1<<slot)+label.encode()+b'\0')
    return bytes(data[:player_start]+rows+tail)


def scenario_script(script,starts):
    # Restrict transformation to the standard melee initialization functions.
    # The original KK Lua entry can initialize the old participant layout again.
    script=re.sub(r'\s*call Cheat\("exec-lua:war3map"\)', '', script)
    def function(name,body):
        nonlocal script
        pattern=r'function '+name+r' takes nothing returns nothing\b.*?endfunction'
        script,n=re.subn(pattern,'function '+name+' takes nothing returns nothing\n'+body+'\nendfunction',script,flags=re.S)
        if n!=1:raise ValueError('Unexpected map function: '+name)
    function('InitCustomPlayerSlots','\n'.join(
        f'    call SetPlayerStartLocation(Player({slot}), {start})\n'
        f'    call ForcePlayerStartLocation(Player({slot}), {start})\n'
        f'    call SetPlayerColor(Player({slot}), ConvertPlayerColor({slot}))\n'
        f'    call SetPlayerRacePreference(Player({slot}), {race})\n'
        f'    call SetPlayerRaceSelectable(Player({slot}), false)\n'
        f'    call SetPlayerController(Player({slot}), {controller})\n'
        f'    call SetPlayerTeam(Player({slot}), {slot})'
        for slot,start,race,controller in [(0,0,'RACE_PREF_HUMAN','MAP_CONTROL_USER'),
                                         (1,1,'RACE_PREF_UNDEAD','MAP_CONTROL_COMPUTER'),
                                         (2,0,'RACE_PREF_HUMAN','MAP_CONTROL_COMPUTER')]))
    function('config','    call SetMapName("dayuan sparring - LR")\n'
             '    call SetMapDescription("P0 observer; P1 dayuan; P2 human opponent")\n'
             '    call SetPlayers(3)\n    call SetTeams(3)\n'
             '    call SetGamePlacement(MAP_PLACEMENT_FIXED)\n'+
             '\n'.join(f'    call DefineStartLocation({i}, {s["x"]}.0, {s["y"]}.0)' for i,s in enumerate(starts))+
             '\n    call InitCustomPlayerSlots()\n'+
             '\n'.join(f'    call SetPlayerSlotAvailable(Player({i}), {"MAP_CONTROL_USER" if i==0 else "MAP_CONTROL_COMPUTER"})' for i in range(3)))
    function('Trig_Melee_Initialization_Actions','''    call MeleeStartingVisibility()
    call MeleeStartingHeroLimit()
    call MeleeGrantHeroItems()
    call MeleeStartingResources()
    call MeleeClearExcessUnits()
    call MeleeStartingUnitsUndead(Player(1), GetStartLocationLoc(1), true, true, false)
    call MeleeStartingUnitsHuman(Player(2), GetStartLocationLoc(0), true, true, false)
    call SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD, 0)
    call SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_LUMBER, 0)
    call SetPlayerState(Player(0), PLAYER_STATE_OBSERVER, 1)
    call SetPlayerAlliance(Player(1), Player(2), ALLIANCE_PASSIVE, false)
    call SetPlayerAlliance(Player(2), Player(1), ALLIANCE_PASSIVE, false)
    call SetPlayerAlliance(Player(1), Player(2), ALLIANCE_SHARED_VISION, false)
    call SetPlayerAlliance(Player(2), Player(1), ALLIANCE_SHARED_VISION, false)
    call FogModifierStart(CreateFogModifierRect(Player(0), FOG_OF_WAR_VISIBLE, GetWorldBounds(), false, false))
    // No native AI scripts. The owned runner arbitrates building-elimination victory.
''')
    return script.encode('utf-8')


def prepare_map(alias='LR'):
    if alias!='LR':raise ValueError('The first observer sparring scenario supports LR only')
    original,catalog=resolve_map(alias)
    blob=original.read_bytes();archive=Mpq(blob)
    starts=sorted(catalog['starts'],key=lambda s:s['slot'])
    if len(starts)!=2:raise ValueError('Observer scenario requires exactly two original starts')
    replacements={'war3map.j':scenario_script(archive.read('war3map.j').decode('utf-8'),starts),
                  'war3map.w3i':lobby_metadata(archive.read('war3map.w3i'),starts)}
    result=replace_members(blob,replacements)
    digest=hashlib.sha256(result).hexdigest()
    folder=ROOT/'artifacts'/'sparring-maps';folder.mkdir(parents=True,exist_ok=True)
    target=folder/('LR-observer-'+digest[:16]+'.w3x')
    if not target.exists():target.write_bytes(result)
    if target.read_bytes()!=result:raise RuntimeError('Generated observer map differs from expected bytes')
    derived={**catalog,'map_sha256':digest,'script_sha256':hashlib.sha256(replacements['war3map.j']).hexdigest(),
             'source_map_sha256':catalog['map_sha256'],'source_map_path':str(original),
             'scenario':'observer_sparring','victory':'runner_all_enemy_buildings_destroyed'}
    target.with_suffix('.json').write_text(json.dumps(derived,ensure_ascii=False,indent=2),encoding='utf-8')
    return target,derived
