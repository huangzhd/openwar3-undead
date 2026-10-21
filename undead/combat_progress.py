"""Bound a motionless, ineffective roadside engagement using fair observations."""
from math import hypot
from statistics import median
from .structures import is_structure


class CombatProgress:
    def __init__(self,log):
        self.log=log;self.sample=None;self.deferred={};self.previous_hp={}
        self.failed={};self.quarantined={};self.rejections={}

    @staticmethod
    def state(target):return (target.type,target.x,target.y,target.hp)

    def changed(self,target,old):
        return (target.type!=old[0] or hypot(target.x-old[1],target.y-old[2])>80
                or abs(target.hp-old[3])>2)

    def release(self,target,now,reason):
        key=target.handle
        if key in self.quarantined:
            self.log('combat_target_released',clock=now,target=key,reason=reason)
        self.quarantined.pop(key,None);self.failed.pop(key,None)
        self.rejections.pop(key,None);self.deferred.pop(key,None)

    def quarantine(self,target,now,reason):
        if target.handle not in self.quarantined:
            self.quarantined[target.handle]=self.state(target)
            self.log('combat_target_quarantined',clock=now,target=target.handle,type=target.type,
                     reason=reason,release='observed_target_change_or_attack')
        self.deferred.pop(target.handle,None)

    def attack_result(self,unit,target,now,accepted,enabled=True):
        if not enabled:return
        if accepted:self.rejections.pop(target.handle,None);return
        row=self.rejections.get(target.handle)
        if row is None or self.changed(target,row['state']) or now-row['last']>5:
            row=dict(state=self.state(target),at=now,last=now,actors=set(),rounds=set())
            self.rejections[target.handle]=row
        row['last']=now;row['actors'].add(unit.handle);row['rounds'].add(now)
        if len(row['actors'])>=2 and len(row['rounds'])>=3 and now-row['at']>=2:
            self.quarantine(target,now,'repeated_rejected_attacks')

    def allowed(self,target,now):
        old=self.quarantined.get(target.handle)
        if old is not None and not self.changed(target,old):return False
        entry=self.deferred.get(target.handle)
        return entry is None or entry[0]!=target.type or now>=entry[1]

    def observe(self,army,foes,now,enabled,visible=None,current_target=None):
        visible=foes if visible is None else visible
        present={e.handle:e for e in visible if e.hp>0}
        own_handles={u.handle for u in army}
        for key in set(self.failed)|set(self.quarantined)|set(self.rejections):
            target=present.get(key)
            if target is None:
                self.failed.pop(key,None);self.quarantined.pop(key,None);self.rejections.pop(key,None)
                continue
            old=self.quarantined.get(key) or self.failed.get(key,{}).get('state') or self.rejections[key]['state']
            attacking=current_target(target) if current_target else None
            if self.changed(target,old) or attacking is not None and attacking.handle in own_handles:
                self.release(target,now,'observed_target_change_or_attack')
        foes=[e for e in foes if e.handle not in self.quarantined]
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
            for target in foes:
                entry=self.failed.setdefault(target.handle,dict(state=self.state(target),count=0))
                entry['count']+=1
                if entry['count']>=2:self.quarantine(target,now,'two_ineffective_engagements')
            self.sample=None
