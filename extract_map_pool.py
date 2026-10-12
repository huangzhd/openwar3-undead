"""Extract public neutral placements from the eight fingerprinted KK maps; never launch."""
import argparse, hashlib, json, re, sys
from math import hypot
from pathlib import Path
from bootstrap import ROOT, UPSTREAM
from w3mpq import Mpq, parse_wts, parse_objects
from w3slk import read_slk
import w3paths
from openwar3 import combat
sys.path.insert(0,str(UPSTREAM/'console/server'))
from mapinfo import parse_w3i,plain

POOL={'AZ':'Amazonia','AL':'Autumn Leaves v2.0','CH':'Concealed Hill',
      'LR':'Last Refuge v1.5','NI':'Northern Isles','TH':'Tidehunters v1.2',
      'TR':'Turtle Rock S2','TM':'Twisted Meadows v1.1'}
NUM=r'[+-]?\s*\d+(?:\.\d+)?'
CREATE=re.compile(r"(?:BlzCreateUnitWithSkin|CreateUnit)\(\s*p\s*,\s*'(\w{4})'\s*,\s*("+NUM+r")\s*,\s*("+NUM+r")\s*,")
POISON={'ACpo','ACvs','Aspo','Aven','ACss'}
HAZARDS={'ACen':'ensnare','ACtb':'stun','ACsw':'slow','ACmi':'spell_immunity',
         'ACc2':'chain_lightning','ACcl':'chain_lightning','ACls':'lightning_shield',
         'ACst':'stomp','ACcs':'curse','ACpa':'purge','ACbl':'bloodlust',
         'Anh2':'heal','Anhe':'heal','ACif':'inner_fire','ANth':'thorns'}

def placements(script,function):
    match=re.search(r'function '+function+r' takes nothing returns nothing(.*?)endfunction',script,re.S)
    if not match:return []
    body=match.group(1)
    rows=[]
    matches=list(CREATE.finditer(body))
    for i,m in enumerate(matches):
        c,x,y=m.groups();row=dict(code=c,x=float(x.replace(' ','')),y=float(y.replace(' ','')))
        segment=body[m.end():matches[i+1].start() if i+1<len(matches) else len(body)]
        action=re.search(r'TriggerAddAction\(\s*t\s*,\s*function\s+(\w+_DropItems)\s*\)',segment)
        if action and re.search(r'TriggerRegisterUnitEvent\(\s*t\s*,\s*u\s*,\s*EVENT_UNIT_DEATH',segment):
            fn=action.group(1)
            table=re.search(r'function '+re.escape(fn)+r' takes nothing returns nothing(.*?)endfunction',script,re.S)
            if table and 'UnitDropItem' in table.group(1) and 'RandomDistAddItem' in table.group(1):
                row.update(drops_items=True,drop_function=fn,
                           drop_table_sha256=hashlib.sha256(table.group(1).encode()).hexdigest())
        rows.append(row)
    calls=re.findall(r'(?:BlzCreateUnitWithSkin|CreateUnit)\(',body)
    if len(rows)!=len(calls):raise ValueError('Nonliteral placement in '+function)
    return rows

def clusters(rows,link=600):
    groups=[]
    for row in rows:
        near=[g for g in groups if any(hypot(row['x']-u['x'],row['y']-u['y'])<=link for u in g)]
        group=[row]
        for g in near:group+=g;groups.remove(g)
        groups.append(group)
    return sorted(groups,key=lambda g:(sum(u['x'] for u in g)/len(g),sum(u['y'] for u in g)/len(g)))

def extract(path,alias):
    blob=path.read_bytes();mpq=Mpq(blob);script=mpq.read('war3map.j').decode('utf-8')
    meta=parse_w3i(mpq.read('war3map.w3i'),parse_wts(mpq.read('war3map.wts') or b''))
    if plain(meta['name'])!=POOL[alias]:raise ValueError('Unexpected map name')
    ud={r['unitID']:r for r in read_slk(w3paths.game_data('UnitData.slk'))}
    ub={r['unitBalanceID']:r for r in read_slk(w3paths.game_data('UnitBalance.slk'))}
    ua={r['unitAbilID']:r for r in read_slk(w3paths.game_data('UnitAbilities.slk'))}
    hostile=placements(script,'CreateNeutralHostile')
    passive=placements(script,'CreateNeutralPassive')+placements(script,'CreateNeutralPassiveBuildings')
    mods=parse_objects(mpq.read('war3map.w3u'),{}) if mpq.read('war3map.w3u') else {}
    relevant={u['code'] for u in hostile+passive}
    if relevant & mods.keys():raise ValueError('Neutral object overrides need explicit support')
    critters=[u for u in passive if ud.get(u['code'],{}).get('race')=='critters' and not combat.stats(u['code']).is_air]
    buildings=[u for u in passive if ub.get(u['code'],{}).get('isbldg')=='1']
    for u in hostile:
        code=u['code'];stat=combat.stats(code)
        if not stat or code not in ub:raise ValueError('Unknown neutral '+code)
        ab=[a for a in ua.get(code,{}).get('abilList','').split(',') if a and a!='_']
        u.update(level=int(ub[code]['level']),hp=stat.hp,abilities=ab,
                 poison_abilities=sorted(set(ab)&POISON),hazards=sorted({HAZARDS[a] for a in ab if a in HAZARDS}))
    camps=[]
    for i,group in enumerate(clusters(hostile)):
        x=sum(u['x'] for u in group)/len(group);y=sum(u['y'] for u in group)/len(group)
        nearby=sorted(buildings,key=lambda b:hypot(b['x']-x,b['y']-y))
        site=next((b for b in nearby if b['code'] in {'ngol','nmer','ngme','ngad','nmrk'} and hypot(b['x']-x,b['y']-y)<700),None)
        codes=[u['code'] for u in group]
        kind={'ngol':'expansion','nmer':'mercenary','ngme':'shop','ngad':'laboratory','nmrk':'marketplace'}.get(site['code']) if site else None
        if kind is None:
            kind='murloc' if any(c.startswith('nmr') for c in codes) else 'turtle' if any(c.startswith('ntr') for c in codes) else 'gnoll' if all(c.startswith('ngn') for c in codes) else 'ogre' if any(c in {'nogr','nomg','nogm'} for c in codes) else 'neutral'
        poison=sum(bool(u['poison_abilities']) for u in group);level=sum(u['level'] for u in group)
        camps.append(dict(id=f'{alias.lower()}-{i}',kind=kind,x=round(x,2),y=round(y,2),
                          max_level=max(u['level'] for u in group),hp=sum(u['hp'] for u in group),
                          level_sum=level,poison_units=poison,difficulty=level+2*poison,
                          requires_support=bool(poison) or kind in {'murloc','mercenary','turtle'},
                          hazards=sorted({h for u in group for h in u['hazards']}),spawns=group))
    starts=[dict(x=p['x'],y=p['y'],slot=p['id']) for p in meta['players']]
    return dict(alias=alias,name=POOL[alias],file=path.name,map_sha256=hashlib.sha256(blob).hexdigest(),
                script_sha256=hashlib.sha256(script.encode()).hexdigest(),starts=starts,critters=critters,
                neutral_buildings=buildings,camps=camps,
                source='Static map JASS placements and local 1.27a unit data; not live hidden state',
                difficulty_formula='level_sum + 2 * poison_units; heuristic, not predicted losses',
                cluster_link=600)

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);args=p.parse_args()
    found={}
    for path in args.directory.glob('*.w3x'):
        mpq=Mpq(path.read_bytes());m=parse_w3i(mpq.read('war3map.w3i'),parse_wts(mpq.read('war3map.wts') or b''))
        name=plain(m['name'])
        for alias,title in POOL.items():
            if name==title:
                if alias in found:raise ValueError('Duplicate '+title)
                found[alias]=extract(path,alias)
    if set(found)!=set(POOL):raise ValueError('Missing maps '+str(set(POOL)-set(found)))
    dest=ROOT/'data/kk_map_pool.json'
    dest.write_text(json.dumps(found,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:dict(name=v['name'],camps=len(v['camps']),critters=len(v['critters']),creeps=sum(len(c['spawns']) for c in v['camps'])) for k,v in found.items()},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
