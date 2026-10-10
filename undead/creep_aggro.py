"""One brief allied attack to transfer visible creep aggro, with bounded retries."""
from .scouting import SKELETONS

class CreepAggro:
    def __init__(self,log):
        self.log=log;self.active=None;self.attempts={};self.retry_at={}

    @property
    def protected(self):
        return {self.active['victim']} if self.active else set()

    def step(self,g,army,foes,now,allowed,blocked=()):
        own={u.handle:u for u in army}
        skeletons={h:u for h,u in own.items() if u.type in SKELETONS}
        creeps={e.handle:e for e in foes if getattr(e,'owner',None)==12}
        target=lambda e:(t.handle if (t:=g.current_target(e)) else None)
        if self.active:
            job=self.active;victim=own.get(job['victim']);sk=skeletons.get(job['skeleton'])
            tracked=[creeps[h] for h in job['creeps'] if h in creeps]
            safe=allowed and victim is not None and victim.handle not in blocked and sk is not None
            confirmed=(safe and len(tracked)==len(job['creeps']) and
                       all(target(e) in skeletons for e in tracked) and
                       not any(target(e)==victim.handle for e in creeps.values()))
            if confirmed or not safe or now-job['started']>=1.2:
                reason='confirmed' if confirmed else 'safety_cancelled' if not safe else 'unconfirmed'
                # Never cancel a newer healing cast or safety move. Otherwise stop
                # the allied attack even when no target has appeared in the snapshot.
                if victim and victim.handle not in blocked:
                    if confirmed:g.attack(victim,min(tracked,key=lambda e:g.dist(e,victim)))
                    else:g.stop(victim)
                self.retry_at[job['victim']]=now+8
                self.log('creep_aggro_'+reason,clock=now,**job,
                         observed_targets=[dict(creep=e.handle,target=target(e)) for e in tracked])
                self.active=None
            return
        if not allowed:return
        for victim in army:
            if not (victim.is_hero or victim.type=='ucry') or victim.handle in blocked:continue
            if now<self.retry_at.get(victim.handle,0):continue
            attackers=[e for e in creeps.values() if target(e)==victim.handle and g.dist(e,victim)<900]
            if not attackers:continue
            choices=[s for s in skeletons.values() if s.handle not in blocked and s.hp>80 and
                     g.dist(s,victim)<600 and all(g.dist(s,e)<500 for e in attackers)]
            if not choices:continue
            key=(victim.handle,tuple(sorted(e.handle for e in attackers)))
            if self.attempts.get(key,0)>=2:continue
            sk=min(choices,key=lambda s:sum(g.dist(s,e) for e in attackers))
            self.attempts[key]=self.attempts.get(key,0)+1
            enemy=min(attackers,key=lambda e:g.dist(e,sk))
            g.attack(sk,enemy)
            receipt=g.attack(victim,sk,force=True)
            self.retry_at[victim.handle]=now+8
            self.log('creep_aggro_attempt',clock=now,victim=victim.handle,unit=victim.type,
                     skeleton=sk.handle,creeps=list(key[1]),accepted=bool(receipt),attempt=self.attempts[key])
            if receipt:self.active=dict(victim=victim.handle,skeleton=sk.handle,creeps=list(key[1]),started=now)
            return
