"""Dust uses only a fresh visible Wind Walk or a recent last-seen position."""
from .nc_combo import spell_data
from .consumables import ITEM_DISABLED
from .targeting import buffs, enemy_player


class BattleDetection:
    def __init__(self,log):
        self.log=log;self.seen={};self.used=set();self.tries={};self.next_at=0;self.pending=None

    def tick(self,b,army,foes,now,blocked=()):
        g=b.g;visible={e.handle:e for e in foes if e.type=='Obla' and enemy_player(g,e)
                     and getattr(e,'visible_to',lambda _:False)(g.me())}
        suspects=[]
        for h,e in visible.items():
            if e.hp<=0 or not e.alive:
                self.seen.pop(h,None);continue
            effects=buffs(g,e)
            if 'BOwk' not in effects or 'Bdet' in effects:
                self.seen[h]=dict(point=(e.x,e.y),at=now);self.used.discard(h)
            elif h not in self.used:
                suspects.append((h,(e.x,e.y),'visible_windwalk'))
        for h,s in list(self.seen.items()):
            if now-s['at']>3:
                self.seen.pop(h,None);continue
            if h not in visible and h not in self.used:suspects.append((h,s['point'],'recent_visibility_loss'))
        if self.pending:
            p=self.pending;hero=next((u for u in army if u.handle==p['hero']),None)
            cd=g.cooldown(hero,'AItb') if hero else None
            revealed=any(e.handle==p['target'] and 'Bdet' in buffs(g,e) for e in visible.values())
            if revealed or cd is not None and cd>0 or now-p['at']>=3:
                if revealed or cd is not None and cd>0:self.tries.pop((p['hero'],p['target']),None)
                self.log('battle_dust_observed',clock=now,handle=p['hero'],target=p['target'],
                         cooldown=cd,revealed=revealed,basis='Bdet on visible target confirms detection; cooldown only confirms item use')
                self.pending=None
        if not suspects or self.pending or now<self.next_at or b.teleport or b.action.name=='RETREAT':return
        excluded=set(blocked)|set(b.shopping)|set(b.battle_shop.reserved)|set(b.micro.pulling)|set(b.shield_moves)
        radius=float(spell_data()[0]['AItb']['Area1'])
        for u in army:
            if not u.is_hero or u.hp<=u.hp_max*.35 or u.handle in excluded or now<b.cast_until.get(u.handle,0):continue
            if buffs(g,u)&ITEM_DISABLED:continue
            bag=g.inventory(u) or []
            if 'dust' not in bag or g.cooldown(u,'AItb')!=0:continue
            for h,point,reason in suspects:
                key=(u.handle,h)
                if g.dist(u,point)>radius-100 or self.tries.get(key,0)>=3:continue
                self.tries[key]=self.tries.get(key,0)+1;self.next_at=now+2
                receipt=g.use_item(u,bag.index('dust'))
                self.log('battle_dust_attempt',clock=now,handle=u.handle,target=h,last_visible_point=point,
                         reason=reason,accepted=bool(receipt))
                if receipt:
                    self.used.add(h);self.next_at=now+20;b.cast_until[u.handle]=now+.4
                    self.pending=dict(hero=u.handle,target=h,at=now)
                return
