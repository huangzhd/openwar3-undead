"""Bounded, local AL camp-entry summons; receipts never count as skeletons."""
from .policy import Action


class ALCampSummon:
    def __init__(self,log):
        self.log=log;self.active=None;self.checked=set()

    def pending(self,b):
        c=b.creeping;route=c.al_route(b.home);stage=c.al_route_stage(b.home)
        return bool(route and stage in route[1:] and stage not in self.checked)

    def finish(self,now,reason,confirmed=False):
        self.log('al_camp_summon_end',clock=now,camp=self.active['camp'],reason=reason,confirmed=confirmed)
        self.checked.add(self.active['camp']);self.active=None

    def tick(self,b,army,now):
        if not self.pending(b):
            if self.active:self.finish(now,'objective_changed')
            return False
        c=b.creeping;g=b.g;route=c.al_route(b.home);stage=c.al_route_stage(b.home)
        # The existing second-camp home stop owns its purchase and conditional summon.
        if stage==route[2] and not (b.ni_rod_stop.done or b.ni_rod_stop.failed):return False
        if b.action!=Action.CREEP or b.attack_committed or b.player_contact or b.teleport or b.situation.threatened:
            if self.active:self.finish(now,'safety_or_objective_changed')
            return False
        own={u.handle for u in army}
        guards=g.creeps()
        engaged=any((t:=g.current_target(e)) is not None and t.handle in own for e in guards)
        engaged=engaged or any((t:=g.current_target(u)) is not None and t.handle in {e.handle for e in guards} for u in army)
        if engaged:
            if self.active:self.finish(now,'already_fighting')
            else:self.checked.add(stage)
            return False
        if self.active and self.active['camp']!=stage:self.finish(now,'objective_changed')
        if self.active is None:
            camp=next(p for p in c.catalog if p['id']==stage)
            candidates=[h for h in army if h.type in {'Udea','Ulic'} and 'rnec' in (g.inventory(h) or [])
                        and h.handle not in b.micro.pulling and h.handle not in b.shopping
                        and h.handle not in b.battle_shop.reserved and h.hp/h.hp_max>=.5]
            hero=min(candidates,key=lambda h:h.type!='Udea',default=None)
            if hero is None:
                self.checked.add(stage);self.log('al_camp_summon_skipped',clock=now,camp=stage,reason='no_available_rod_carrier')
                return False
            distance=g.path_distance((hero.x,hero.y),(camp['x'],camp['y']))
            if distance is None:
                self.checked.add(stage);self.log('al_camp_summon_skipped',clock=now,camp=stage,reason='next_camp_unreachable')
                return False
            required=distance/270+20
            healthy=[u for u in g.units('me',{'uske'}) if u.handle not in b.skeleton_scouts.assignments
                     and g.dist(u,hero)<900 and u.hp/u.hp_max>=.5
                     and b.skeleton_expiry.get(u.handle,now)-now>=required]
            force=stage==route[1]
            if not force and len(healthy)>=2:
                self.checked.add(stage);return False
            self.active=dict(camp=stage,hero=hero.handle,started=now,force=force,at=None,
                             attempts=0,before=set(),corpse=None)
            self.log('al_camp_summon_started',clock=now,camp=stage,forced_first_clear=force,
                     healthy_skeletons=len(healthy),required_lifetime=required,hero=hero.handle)
        job=self.active;hero=g.unit(job['hero'])
        casting=hero and now<b.cast_until.get(hero.handle,0) and job['at'] is not None
        if (not hero or hero.handle not in own and not casting or hero.hp/hero.hp_max<.5 or hero.handle in b.micro.pulling
                or hero.handle in b.shopping or hero.handle in b.battle_shop.reserved):
            self.finish(now,'carrier_unavailable');return False
        if job['at'] is not None:
            fresh=[u for u in g.units('me',{'uske'}) if u.handle not in job['before'] and g.dist(u,hero)<1000]
            if job.get('accepted') and len(fresh)>=2:
                if job['corpse'] is not None:b.rod_used.add(job['corpse'])
                self.finish(now,'two_new_skeletons_observed',True);b.formation.reset();b.formation_at=-100
                return False
            if now-job['at']<3:return True
            if job['attempts']>=3:
                self.finish(now,'summon_unconfirmed');return False
        if now-job['started']>=30:
            self.finish(now,'time_limit');return False
        bag=g.inventory(hero) or []
        if 'rnec' not in bag:
            self.finish(now,'rod_unavailable');return False
        cooldown=g.cooldown(hero,'AIrd')
        if cooldown is None or cooldown>0 and not job['force']:
            self.finish(now,'cooldown_unknown' if cooldown is None else 'cooldown_not_ready');return False
        corpses=[(g.dist(hero,r['point']),h,r) for h,r in b.rod_corpses.items()
                 if h not in b.rod_used and now-r['clock']<60 and g.dist(hero,r['point'])<=1000
                 and g.path_distance((hero.x,hero.y),r['point']) is not None
                 and c.safe_route(g,(hero.x,hero.y),r['point'])
                 and not any(g.dist(e,r['point'])<600 for e in guards if e.hp>0)]
        if not corpses:
            self.finish(now,'no_safe_local_corpse');return False
        distance,handle,corpse=min(corpses)
        c.pause(now,'entry_skeletons');b.set_intent('练级前补骷髅 · 确认新一组后继续')
        # Keep the party at this cleared site. No trip home or repeated holds.
        followers=[u for u in army if u.handle!=hero.handle and g.dist(u,hero)>450
                   and u.handle not in b.shopping and u.handle not in b.micro.pulling]
        b.go_raw(followers,(hero.x,hero.y),now)
        if now<b.cast_until.get(hero.handle,0):return True
        if distance>400:
            b.go_raw([hero],corpse['point'],now);return True
        if cooldown>0:return True
        job.update(at=now,attempts=job['attempts']+1,before={u.handle for u in g.units('me',{'uske'})},corpse=handle)
        accepted=b.use_rod(hero,bag.index('rnec'),now)
        job['accepted']=bool(accepted)
        if accepted:b.rod_birth_windows[-1]['corpse']=handle
        self.log('al_camp_summon_attempt',clock=now,camp=stage,hero=hero.handle,corpse=handle,
                 accepted=bool(accepted),attempt=job['attempts'])
        return True
