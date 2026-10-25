"""Fair, bounded N/C/F finishers. Accepted orders are not confirmed damage."""
from functools import lru_cache
from itertools import combinations
import bootstrap
import w3paths
from w3slk import read_slk
from openwar3 import combat
from .coil import can_damage, ready as coil_ready, level as coil_level
from .hero_spell_telemetry import ready as hero_spell_ready, level as hero_spell_level

BLOCKED_BUFFS = {'BHds','Bvul','Bams','Bam2','BNms','BNss','Bcmg'}
BLOCKED_ABILITIES = {'Avul','Amim','ACmi','ACm2','ACm3','AImx','ANss','ANse'}
DISABLED_CASTERS = {'BNsi','BEsh','BPse','BPSE','BUsl','BSTN','Bstn','Bply','Bcyc','BOhx'}
SPELLS = (('N','Ulic','AUfn','frostnova'), ('C','Udea','AUdc','deathcoil'),
          ('F','Nngs','ANfl','forkedlightning'))

@lru_cache(maxsize=1)
def spell_data():
    rows={r['alias']:r for r in read_slk(w3paths.game_data('AbilityData.slk')) if r.get('alias')}
    return rows,float(combat.misc_game()['DamageBonusSpells'].split(',')[5])

def spell_damage(code,level,bracers=False):
    if level not in (1,2,3):return 0
    rows,factor=spell_data();row=rows[code];suffix=str(level)
    raw=float(row['DataA'+suffix])
    if code=='AUdc':raw/=2
    if code=='AUfn':raw+=float(row['DataB'+suffix])
    if bracers:factor*=1-float(rows['AIsr']['DataB1'])
    return raw*factor

def damage(coil_level,nova_level,bracers=False):
    if coil_level not in (1,2,3) or nova_level not in (1,2,3):return None
    return spell_damage('AUdc',coil_level,bracers),spell_damage('AUfn',nova_level,bracers)

def target_legal(g,e):
    if (not e.is_hero or e.hp<=0 or not getattr(e,'has_detail',False) or
        not 0<=getattr(e,'owner',12)<12 or e.owner==g.me()):return False
    abilities={a['code']:a for a in g.abilities(e)}
    return not (BLOCKED_BUFFS & set(g.buffs(e)) or BLOCKED_ABILITIES & abilities.keys() or
                ('AHav' in abilities and abilities['AHav'].get('cooldown')!=0))

def aoe_threat(g,target):
    """Visible high area-damage heroes; no hidden cooldown or skill queries."""
    if not target.is_hero or not getattr(target,'has_detail',False):return False
    return target.type in {'Otch','Hblm'} or any(
        a['code'] in {'AOsh','AOws','AHfs','AHbz','ANbf'} and a.get('level',0)>0
        for a in g.abilities(target))

class NCCombo:
    # Keep the public name/log names for existing match review tools.
    def __init__(self,log):
        self.log=log;self.failures={};self.retry_at={};self.pending=None
        self.single_attempt_at=-100
        self.healing_sources=None

    def observe(self,g,now):
        p=self.pending
        if not p:return
        target=next((u for u in g.enemies() if u.handle==p['target']),None)
        if target is None or target.hp<=0 or now-p['clock']>=3:
            if target is not None and target.hp>=p['hp']:
                for key in p['keys']:self.failures[key]=self.failures.get(key,0)+1
            casters=[g.unit(h) for h in p['casters']]
            self.log('hero_finisher_observed' if p['single'] else 'nc_observed',clock=now,target=p['target'],start_hp=p['hp'],
                     visible_hp=target.hp if target else None,
                     outcome='visible_dead' if target and target.hp<=0 else
                             'target_unavailable' if target is None else
                             'hp_decreased' if target.hp<p['hp'] else 'unconfirmed',
                     cooldowns=[g.cooldown(u,a) if u else None for u,a in zip(casters,p['spells'])],
                     mana=[u.mana if u else None for u in casters],combination=p['combination'])
            self.pending=None

    def focus(self,foes,now):
        if self.pending and now-self.pending['clock']<3:
            return next((e for e in foes if e.handle==self.pending['target'] and e.hp>0),None)

    def options(self,g,army,target,anchor,now,cast_until,blocked):
        if not target_legal(g,target) or g.dist(target,anchor)>=650:return []
        rows,_=spell_data();result=[]
        bracers=any(a['code']=='AIsr' for a in g.abilities(target))
        for letter,kind,code,spell in SPELLS:
            u=next((u for u in army if u.type==kind),None)
            if (not u or u.hp<=0 or u.handle in blocked or not getattr(u,'has_detail',False) or
                now<cast_until.get(u.handle,0) or g.dist(u,anchor)>=700 or
                not hero_spell_ready(g,u,code,now) or DISABLED_CASTERS & set(g.buffs(u))):continue
            level=hero_spell_level(g,u,code)
            if level not in (1,2,3):continue
            row=rows[code];cost=float(row['Cost'+str(level)]);reach=float(row['Rng'+str(level)])
            # Preserve the established NC safety margin; F has its own 600 range.
            if code!='ANfl':reach=min(reach,750)
            if u.mana<cost or g.dist(u,target)>reach or (code=='AUdc' and not can_damage(target.type)):continue
            result.append(dict(letter=letter,caster=u,code=code,spell=spell,level=level,cost=cost,
                               damage=spell_damage(code,level,bracers),bracers=bracers,
                               key=(u.handle,target.handle,code)))
        return result

    def select(self,options,hp,now):
        if hp<=0:return ()
        for size in range(1,len(options)+1):
            lethal=[s for s in combinations(options,size) if sum(a['damage'] for a in s)+1e-8>=hp]
            if not lethal:continue
            # A spent retry budget cannot justify spending an extra spell.
            usable=[s for s in lethal if all(self.failures.get(a['key'],0)<3 and now>=self.retry_at.get(a['key'],0) for a in s)]
            return min(usable,key=lambda s:(sum(a['cost'] for a in s),sum(a['damage'] for a in s)-hp,
                                           tuple(a['letter'] for a in s))) if usable else None
        return None

    def try_cast(self,g,army,foes,now,cast_until,blocked=(),pressure=False,key_pressure=False):
        if self.pending or not army:return None
        anchor=min(army,key=lambda u:sum(g.dist(u,v) for v in army));candidates=[]
        for e in foes:
            options=self.options(g,army,e,anchor,now,cast_until,blocked)
            chosen=self.select(options,e.hp,now)
            if chosen:candidates.append((e,chosen))
        pressuring=False
        if not candidates and pressure:
            for e in foes:
                if not aoe_threat(g,e) and not key_pressure:continue
                opts=[a for a in self.options(g,army,e,anchor,now,cast_until,blocked)
                      if a['letter'] in {'N','C'} and self.failures.get(a['key'],0)<3 and now>=self.retry_at.get(a['key'],0)]
                if {a['letter'] for a in opts}=={'N','C'}:candidates.append((e,tuple(opts)))
            pressuring=bool(candidates)
        if not candidates:return None
        target,chosen=min(candidates,key=lambda row:(not aoe_threat(g,row[0]),len(row[1]),sum(a['cost'] for a in row[1]),
                          sum(a['damage'] for a in row[1])-row[0].hp,row[0].handle))
        start_hp=target.hp;remaining=list(chosen);sent=[];receipts={};pending_damage=0;last_hp=start_hp
        self.single_attempt_at=now # Suppress all ordinary offensive casts on any attempt.
        while remaining:
            fresh=next((e for e in g.enemies() if e.handle==target.handle),None)
            if fresh is None or not target_legal(g,fresh):break
            # Retire observed HP loss from the pending upper bound; never add it twice.
            pending_damage=max(0,pending_damage-max(0,last_hp-fresh.hp));last_hp=fresh.hp
            ready=self.options(g,army,fresh,anchor,now,cast_until,blocked)
            ready=[a for a in ready if any(a['key']==b['key'] for b in remaining)]
            next_plan=(ready if fresh.hp>pending_damage else ()) if pressuring else self.select(ready,max(0,fresh.hp-pending_damage),now)
            if not next_plan:break # Dead, already covered, or newly healed beyond this plan.
            a=next_plan[0] # Nova first whenever included; C/F remain independently legal.
            self.retry_at[a['key']]=now+2
            accepted=bool(g.cast(a['caster'],a['spell'],target=fresh));receipts[a['letter']]=accepted
            cast_until[a['caster'].handle]=max(cast_until.get(a['caster'].handle,0),now+.8)
            if not accepted:
                self.failures[a['key']]=self.failures.get(a['key'],0)+1;break
            sent.append(a);pending_damage+=a['damage'];remaining=[b for b in remaining if b['key']!=a['key']]
        for a in chosen:cast_until[a['caster'].handle]=max(cast_until.get(a['caster'].handle,0),now+.8)
        combo=''.join(a['letter'] for a in chosen);single=len(chosen)==1
        fields=dict(clock=now,target=target.type,handle=target.handle,hp=start_hp,combination=combo,
                    intent='aoe_pressure' if pressuring else 'finisher',
                    estimated_damage=sum(a['damage'] for a in chosen),hero_multiplier=spell_data()[1],
                    bracers=chosen[0]['bracers'],accepted=all(receipts.get(a['letter'],False) for a in chosen),
                    failures=max(self.failures.get(a['key'],0) for a in chosen),receipts=receipts,
                    pending_damage=pending_damage,damage_confirmed=False)
        sources=self.healing_sources(g,target,now) if self.healing_sources else []
        fields.update(healing_window_uncertain=bool(sources),healing_sources=sources)
        if single:
            a=chosen[0];fields.update(caster=a['caster'].type,spell=a['spell'],level=a['level'])
        else:
            for a in chosen:fields[a['letter'].lower()+'_damage']=a['damage']
            for letter,name in (('C','coil'),('N','nova'),('F','fork')):
                a=next((a for a in chosen if a['letter']==letter),None)
                fields[name+'_accepted']=receipts.get(letter)
                fields[name+'_level']=a['level'] if a else None
                fields[name+'_damage']=a['damage'] if a else 0
            fields['extra_resistance']=float(spell_data()[0]['AIsr']['DataB1']) if chosen[0]['bracers'] else 0
        self.log('hero_finisher_attempt' if single else 'nc_attempt',**fields)
        if sent:
            self.pending=dict(target=target.handle,hp=start_hp,clock=now,casters=tuple(a['caster'].handle for a in sent),
                              spells=tuple(a['code'] for a in sent),keys=tuple(a['key'] for a in sent),
                              single=single,combination=combo,pending_damage=pending_damage)
        return target
