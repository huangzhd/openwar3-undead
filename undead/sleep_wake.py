"""One bounded allied hit to release observed Sleep; never chase a sleeper."""
from .scouting import SKELETONS
from .targeting import in_weapon_range

DISABLED={'BUsl','BUsp','BUim','BSTN','Bstn','Bcyc','Bens','BEer'}

class SleepWake:
    def __init__(self,log):
        self.log=log;self.active=None;self.episodes={}

    def cancel(self,g,now,cast_until,reason):
        p=self.active
        if not p:return
        actor=g.unit(p['actor'])
        # This actor is reserved only for our bounded attack, not a hero cast.
        if actor:g.stop(actor)
        if cast_until.get(p['actor'])==p['until']:cast_until.pop(p['actor'],None)
        self.log('sleep_wake_end',clock=now,reason=reason,**p)
        self.active=None

    def observe(self,g,now,cast_until):
        p=self.active
        if not p:return
        actor=g.unit(p['actor']);target=g.unit(p['target'])
        reason=None
        if not actor or not target or actor.hp<=0 or target.hp<=0:reason='unit_unavailable'
        elif 'BUsl' not in set(g.buffs(target)):
            self.log('sleep_wake_observed',clock=now,actor=p['actor'],target=p['target'],
                     hp_delta=round(target.hp-p['hp'],1),elapsed=round(now-p['started'],2))
            reason='sleep_removed'
        elif actor.hp/actor.hp_max<.6 or target.hp<max(150,.4*target.hp_max):reason='health_priority'
        elif now>=p['until']:reason='unconfirmed_timeout'
        if reason:self.cancel(g,now,cast_until,reason)

    def start(self,g,army,now,cast_until,blocked=()):
        if self.active or not hasattr(g,'buffs'):return
        sleepers={u.handle:u for u in army if u.hp>0 and 'BUsl' in set(g.buffs(u))}
        self.episodes={h:p for h,p in self.episodes.items() if h in sleepers}
        for target in sorted(sleepers.values(),key=lambda u:(not u.is_hero,-u.hp)):
            state=self.episodes.setdefault(target.handle,dict(attempts=0,retry=0))
            if state['attempts']>=2 or now<state['retry']:continue
            # BUsp is the initial protected interval; do not hit fragile allies.
            if 'BUsp' in set(g.buffs(target)) or target.hp<max(150,.4*target.hp_max):continue
            actors=[u for u in army if u.handle!=target.handle and u.handle not in blocked and
                    (u.type=='ucry' or u.type in SKELETONS) and u.hp/u.hp_max>=.6 and
                    now>=cast_until.get(u.handle,0) and not DISABLED.intersection(g.buffs(u)) and
                    g.dist(u,target)<=450 and in_weapon_range(g,u,target)]
            if not actors:continue
            actor=min(actors,key=lambda u:(u.type not in SKELETONS,g.dist(u,target)))
            state['attempts']+=1;state['retry']=now+4
            receipt=g.attack(actor,target,force=True)
            self.log('sleep_wake_attempt',clock=now,actor=actor.handle,target=target.handle,
                     accepted=bool(receipt),attempt=state['attempts'])
            if receipt:
                self.active=dict(actor=actor.handle,target=target.handle,started=now,until=now+2,hp=target.hp)
                cast_until[actor.handle]=now+2
            return
