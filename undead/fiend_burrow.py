"""Shared fiend recovery; own morph snapshots, never receipts, prove burrow."""
from .nc_combo import DISABLED_CASTERS


class FiendBurrow:
    def __init__(self,log):
        self.log=log;self.pending={};self.attempts={};self.retry={};self.hp={};self.escape_until={}

    def tick(self,b,fiends,heroes,foes,now,blocked=()):
        g=b.g;live={u.handle:u for u in fiends if u.hp>0 and getattr(u,'alive',True)}
        for handle,p in list(self.pending.items()):
            u=live.get(handle)
            if u and u.type==p['expected']:
                self.log('fiend_burrow_observed',clock=now,handle=handle,type=u.type,hp=u.hp,action=p['action'])
                self.pending.pop(handle);self.attempts.pop((handle,p['action']),None)
            elif not u or now-p['started']>=2.5:
                self.log('fiend_burrow_unconfirmed',clock=now,handle=handle,action=p['action'])
                self.pending.pop(handle)
        reserved={h for h,u in live.items() if u.type=='ucrm'}|set(self.pending)
        dk=next((h for h in heroes if h.type=='Udea' and h.hp>0),None)
        for h,u in live.items():
            previous=self.hp.get(h,u.hp);self.hp[h]=u.hp
            if h in blocked or h in self.pending or now<b.cast_until.get(h,0):continue
            ratio=u.hp/max(1,u.hp_max);buried=u.type=='ucrm'
            nearby=any(g.dist(u,e)<800 for e in foes)
            taking_damage=buried and u.hp<previous-5 and nearby
            if buried:
                if ratio<.7 and not taking_damage:continue
                action='unburrow';expected='ucry'
            else:
                if ratio>.4 or not nearby or now<self.escape_until.get(h,0):continue
                if (dk and dk.mana>=75 and dk.handle not in blocked and g.dist(dk,u)<750
                        and b.rescue_coil_ready(dk,now)):continue
                action='burrow';expected='ucrm'
            key=(h,action)
            if self.attempts.get(key,0)>=3 or now<self.retry.get(key,0):continue
            if not all(hasattr(g,n) for n in ('abilities','cooldown','buffs','tech_many')):continue
            if not any(a['code']=='Abur' and a.get('level',0)>0 for a in g.abilities(u)):continue
            if g.cooldown(u,'Abur')!=0 or set(g.buffs(u))&DISABLED_CASTERS:continue
            # The learned ability alone does not establish that its research is done.
            if not buried and (g.tech_many(['Rubu']).get('Rubu') or 0)<1:continue
            accepted=bool(g.cast(u,action))
            self.attempts[key]=self.attempts.get(key,0)+1;self.retry[key]=now+2.5
            self.log('fiend_burrow_attempt',clock=now,handle=h,action=action,hp=u.hp,hp_max=u.hp_max,
                     accepted=accepted,attempt=self.attempts[key],reason='taking_damage' if taking_damage else 'recovered' if buried else 'coil_unavailable')
            if accepted:
                b.cast_until[h]=now+1.8
                self.pending[h]=dict(expected=expected,action=action,started=now)
                reserved.add(h)
                if taking_damage:self.escape_until[h]=now+8
        self.hp={h:hp for h,hp in self.hp.items() if h in live}
        return reserved
