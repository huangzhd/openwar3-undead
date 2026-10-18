"""Visible dispel priorities: own hero debuffs, enemy summons, enemy buffs."""
from functools import lru_cache
from .nc_combo import spell_data,DISABLED_CASTERS
from .targeting import enemy_player,buffs

# 1.27a public AbilityData/buffs.json identifiers; no blanket B* classification.
# Auras, stun, poison, Purge slow, invulnerability and transformation buffs are
# deliberately absent: having a buff object does not make it dispellable.
HERO_DEBUFFS=frozenset({'BOhx','Bply','BEer','BUsl','Bcyc','Bcy2','BHbn',
    'Bslo','Bcri','Bcrs','Bfae','BNsi','BNso','BNht','BNdh'})
ENEMY_BUFFS=frozenset({'Bblo','Binf','Brej','Broa','BNbr','BUfa','BUhf','Buhf',
    'Bspl','Binv','Blsh','Bspe','Bdef','BIrg','BIrl','BIrm','Brpb'})


@lru_cache(maxsize=1)
def summon_types():
    rows,_=spell_data()
    # Public summon spell outputs, not zero-cost heuristics or hidden unit flags.
    codes=set()
    for code in ('AHwe','AEfn','AOsf','ANsg','ANsq','ANsw','ANba','AUin','ANdo','ACwe','AIrd','Arai',
                 'ANlm','AHpx','AEsv','AOsw','ANsy'):
        codes.update(v for k,v in rows[code].items() if k.startswith('UnitID') and len(v)==4)
    codes.update(rows['AUcb']['DataC'+str(level)] for level in (1,2,3))
    codes.add('uskm') # Skeletal Mastery replaces one raised warrior with a mage.
    return frozenset(codes)


class Destroyer:
    def __init__(self,log):
        self.log=log;self.morph=None;self.morph_attempts={};self.next_morph=0
        self.dispel={};self.attempts={};self.next_cast={}

    def targets(self,b,army,enemies):
        g=b.g;targets=[]
        heroes=g.my_heroes() if hasattr(g,'my_heroes') else [u for u in army if u.is_hero]
        for u in heroes:
            effects=buffs(g,u)&HERO_DEBUFFS
            if effects and u.hp>0 and u.alive and u.owner==g.me():
                targets.append(dict(unit=u,priority=0,reason='hero_debuff',effects=sorted(effects)))
        for u in enemies:
            effects=buffs(g,u)&ENEMY_BUFFS
            summon=u.type in summon_types() and u.type!='ninf'
            if not (effects or summon):continue
            if not (u.alive and u.hp>0 and enemy_player(g,u) and u.visible_to(g.me())):continue
            # Infernals are summoned but spell immune, so not dispel fodder.
            if summon:
                targets.append(dict(unit=u,priority=1,reason='enemy_summon',effects=sorted(effects)))
            elif effects:
                targets.append(dict(unit=u,priority=2,reason='enemy_buff',effects=sorted(effects)))
        return targets

    def observe(self,b,now):
        g=b.g
        if self.morph:
            p=self.morph;unit=g.unit(p['handle'])
            if unit and unit.type=='ubsp':
                self.log('destroyer_morph_confirmed',clock=now,handle=unit.handle,mana=unit.mana)
                self.morph=None
            elif now-p['started']>=8 or unit is None:
                self.log('destroyer_morph_unconfirmed',clock=now,handle=p['handle'])
                self.morph=None
            else:b.cast_until[p['handle']]=max(b.cast_until.get(p['handle'],0),now+1)
        for handle,p in list(self.dispel.items()):
            unit=g.unit(handle)
            cd=g.cooldown(unit,'Advm') if unit else None
            if cd is not None and cd>0 or now-p['started']>=3 or unit is None:
                changes=[]
                for h,hp in p['targets']:
                    target=g.unit(h)
                    if target and target.visible_to(g.me()):
                        changes.append(dict(handle=h,hp_before=hp,hp_after=target.hp,alive=target.alive))
                effects=[]
                for h,before in p.get('effects',[]):
                    target=g.unit(h)
                    if target and getattr(target,'has_detail',False) and target.visible_to(g.me()):
                        after=buffs(g,target)
                        effects.append(dict(handle=h,before=before,remaining=sorted(set(before)&after),
                                            absent=sorted(set(before)-after)))
                confirmed=cd is not None and cd>0
                self.log('destroyer_dispel_cast_observed' if confirmed else 'destroyer_dispel_unconfirmed',
                         clock=now,handle=handle,cooldown=cd,targets=changes,effects=effects,
                         reason=p.get('reason','enemy_summon'),
                         basis='cooldown confirms cast; buff absence may include expiry/other dispels; hidden targets unknown')
                if confirmed:self.attempts.pop(p['key'],None)
                self.dispel.pop(handle,None)

    def tick(self,b,army,enemies,now,blocked=()):
        g=b.g;self.observe(b,now)
        if b.teleport:return
        targets=self.targets(b,army,enemies)
        # During retreat only an existing, unblocked destroyer may free a hero.
        retreat=b.action.name=='RETREAT'
        if retreat:targets=[t for t in targets if t['priority']==0]
        if not targets:return
        available=[u for u in army if u.handle not in blocked and now>=b.cast_until.get(u.handle,0)
                   and not buffs(g,u)&(DISABLED_CASTERS|{'BOhx'})]
        destroyers=g.units('me',{'ubsp'})
        if not retreat and not destroyers and not self.morph and now>=self.next_morph:
            level=g.tech_many(['Rusp']).get('Rusp');res=g.resources()
            hero_food=5 if b.economy.third_hero not in b.economy.ever_heroes else 0
            cap=res['food_cap'] if b.economy.upkeep_released or res['food_used']>50 else min(50,res['food_cap'])
            if (level is not None and level>=1 and res['gold']>=100 and res['lumber']>=50
                    and res['food_used']+2+hero_food<=cap):
                statues=[u for u in available if u.type=='uobs' and g.cooldown(u,'Aave')==0
                         and self.morph_attempts.get(u.handle,0)<3
                         and any(g.dist(u,t['unit'])<=900 for t in targets)]
                if statues:
                    priority=lambda u:min(t['priority'] for t in targets if g.dist(u,t['unit'])<=900)
                    u=min(statues,key=lambda u:(priority(u),u.mana,u.handle));n=self.morph_attempts.get(u.handle,0)+1
                    self.morph_attempts[u.handle]=n;self.next_morph=now+4
                    receipt=g.cast(u,'avengerform')
                    self.log('destroyer_morph_attempt',clock=now,handle=u.handle,mana=u.mana,
                             accepted=bool(receipt),attempt=n,trigger_priority=priority(u))
                    if receipt:
                        self.morph=dict(handle=u.handle,started=now);b.cast_until[u.handle]=now+2.5
        row=spell_data()[0]['Advm'];reach=float(row['Rng1']);area=float(row['Area1'])
        for u in available:
            if u.type!='ubsp' or u.handle in self.dispel or now<self.next_cast.get(u.handle,0):continue
            if g.cooldown(u,'Advm')!=0:continue
            reachable=[t for t in targets if g.dist(u,t['unit'])<=reach
                       and self.attempts.get((u.handle,t['unit'].handle),0)<3]
            if not reachable:continue
            def score(t):
                e=t['unit']
                counts=tuple(-sum(v['priority']==rank and g.dist(e,v['unit'])<=area for v in targets) for rank in range(3))
                return (t['priority'],*counts,e.hp,e.handle)
            selected=min(reachable,key=score);target=selected['unit']
            key=(u.handle,target.handle)
            self.attempts[key]=self.attempts.get(key,0)+1;self.next_cast[u.handle]=now+2
            receipt=g.cast(u,'devourmagic',x=target.x,y=target.y)
            self.log('destroyer_dispel_attempt',clock=now,handle=u.handle,target=target.handle,
                     point=(target.x,target.y),accepted=bool(receipt),attempt=self.attempts[key],
                     reason=selected['reason'],priority=selected['priority'],effects=selected['effects'])
            if receipt:
                b.cast_until[u.handle]=now+1.2
                self.dispel[u.handle]=dict(started=now,key=key,
                    reason=selected['reason'],
                    targets=[(t['unit'].handle,t['unit'].hp) for t in targets if g.dist(t['unit'],target)<=area],
                    effects=[(t['unit'].handle,t['effects']) for t in targets if t['effects'] and g.dist(t['unit'],target)<=area])
