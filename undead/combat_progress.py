"""Bound a motionless, ineffective roadside engagement using fair observations."""
from math import hypot
from statistics import median
from .structures import is_structure


class CombatProgress:
    def __init__(self,log):
        self.log=log;self.sample=None;self.deferred={};self.previous_hp={}

    def allowed(self,target,now):
        entry=self.deferred.get(target.handle)
        return entry is None or entry[0]!=target.type or now>=entry[1]

    def observe(self,army,foes,now,enabled):
        own={u.handle:(u.x,u.y,u.hp) for u in army if u.hp>0}
        enemies={e.handle:(e.type,e.hp) for e in foes if e.hp>0}
        # Never bypass live incoming damage, a newly arrived threat, or a
        # surfaced/morphed unit merely because the previous fight stalled.
        damage=any(h in self.previous_hp and u[2]<self.previous_hp[h]-2 for h,u in own.items())
        lost=bool(self.previous_hp.keys()-own.keys())
        self.previous_hp={h:u[2] for h,u in own.items()}
        if damage or lost or not enabled:
            self.deferred.clear();self.sample=None
        self.deferred={h:v for h,v in self.deferred.items()
                       if h in enemies and v[0]==enemies[h][0] and now<v[1]}
        if self.deferred and any(h not in self.deferred for h in enemies):
            self.deferred.clear();self.sample=None
        if not enabled or not own or not enemies or any(is_structure(e) for e in foes):
            self.sample=None;return
        if self.deferred:return
        old=self.sample
        changed=(old is None or old['enemies'].keys()!=enemies.keys() or old['own'].keys()!=own.keys()
                 or any(old['enemies'][h][0]!=v[0] for h,v in enemies.items()))
        if not changed:
            progress=any(v[1]<old['enemies'][h][1]-2 for h,v in enemies.items())
            progress |= any(v[2]<old['own'][h][2]-2 for h,v in own.items())
            progress |= median(hypot(v[0]-old['own'][h][0],v[1]-old['own'][h][1]) for h,v in own.items())>80
            changed=progress or now-old['last']>3
        if changed:
            self.sample=dict(at=now,last=now,own=own,enemies=enemies);return
        old['last']=now
        if now-old['at']>=8:
            self.deferred={h:(v[0],now+10) for h,v in enemies.items()}
            self.log('combat_stall_bypassed',clock=now,since=old['at'],targets=list(enemies),
                     until=now+10,reason='no_motion_or_observed_damage')
            self.sample=None
