"""One observed destroyer; visible summons trigger bounded morph and dispel orders."""
from functools import lru_cache
from .nc_combo import spell_data,DISABLED_CASTERS
from .targeting import enemy_player,buffs


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
                confirmed=cd is not None and cd>0
                self.log('destroyer_dispel_cast_observed' if confirmed else 'destroyer_dispel_unconfirmed',
                         clock=now,handle=handle,cooldown=cd,targets=changes,
                         basis='cooldown confirms cast; health changes may include other damage; hidden targets unknown')
                if confirmed:self.attempts.pop(p['key'],None)
                self.dispel.pop(handle,None)

    def tick(self,b,army,enemies,now,blocked=()):
        g=b.g;self.observe(b,now)
        if b.action.name not in {'ATTACK','HARASS'} or b.teleport:return
        summons=[e for e in enemies if e.type in summon_types() and e.alive and e.hp>0 and enemy_player(g,e)
                 and e.visible_to(g.me())]
        if not summons:return
        available=[u for u in army if u.handle not in blocked and now>=b.cast_until.get(u.handle,0)
                   and not buffs(g,u)&DISABLED_CASTERS]
        destroyers=g.units('me',{'ubsp'})
        if not destroyers and not self.morph and now>=self.next_morph:
            level=g.tech_many(['Rusp']).get('Rusp');res=g.resources()
            hero_food=5 if b.economy.third_hero not in b.economy.ever_heroes else 0
            cap=res['food_cap'] if b.economy.upkeep_released or res['food_used']>50 else min(50,res['food_cap'])
            if (level is not None and level>=1 and res['gold']>=100 and res['lumber']>=50
                    and res['food_used']+2+hero_food<=cap):
                statues=[u for u in available if u.type=='uobs' and g.cooldown(u,'Aave')==0
                         and self.morph_attempts.get(u.handle,0)<3
                         and any(g.dist(u,e)<=900 for e in summons)]
                if statues:
                    u=min(statues,key=lambda u:(u.mana,u.handle));n=self.morph_attempts.get(u.handle,0)+1
                    self.morph_attempts[u.handle]=n;self.next_morph=now+4
                    receipt=g.cast(u,'avengerform')
                    self.log('destroyer_morph_attempt',clock=now,handle=u.handle,mana=u.mana,
                             accepted=bool(receipt),attempt=n)
                    if receipt:
                        self.morph=dict(handle=u.handle,started=now);b.cast_until[u.handle]=now+2.5
        row=spell_data()[0]['Advm'];reach=float(row['Rng1']);area=float(row['Area1'])
        for u in available:
            if u.type!='ubsp' or u.handle in self.dispel or now<self.next_cast.get(u.handle,0):continue
            if g.cooldown(u,'Advm')!=0:continue
            targets=[e for e in summons if g.dist(u,e)<=reach]
            if not targets:continue
            target=min(targets,key=lambda e:(-sum(g.dist(e,v)<=area for v in summons),e.hp,e.handle))
            key=(u.handle,target.handle)
            if self.attempts.get(key,0)>=3:continue
            self.attempts[key]=self.attempts.get(key,0)+1;self.next_cast[u.handle]=now+2
            receipt=g.cast(u,'devourmagic',x=target.x,y=target.y)
            self.log('destroyer_dispel_attempt',clock=now,handle=u.handle,target=target.handle,
                     point=(target.x,target.y),accepted=bool(receipt),attempt=self.attempts[key])
            if receipt:
                b.cast_until[u.handle]=now+1.2
                self.dispel[u.handle]=dict(started=now,key=key,
                    targets=[(e.handle,e.hp) for e in summons if g.dist(e,target)<=area])
