"""CH Graveyard summons before the ogre and first post-opening shop camp."""


class CHResummon:
    def __init__(self, log):
        self.log=log;self.done=False;self.shop_done=False;self.mission=None;self.stage=None;self.next_camp=None

    def finish(self, now, reason):
        self.log('ch_graveyard_resummon_end',clock=now,reason=reason,next_camp=self.next_camp,stage=self.stage)
        if self.stage=='shop':self.shop_done=True
        else:self.done=True
        self.mission=None

    def tick(self,b,army,now):
        g=b.g;c=b.creeping
        if c.map_alias!='CH' or b.attack_committed:return False
        route=c.ch_home_opening(b.home)
        active=getattr(c,'active',None)
        if self.mission is None:
            if len(route)!=2:return False
            if not self.done and route[0]['id'] in c.cleared and route[1]['id'] not in c.cleared:
                self.stage='ogre';self.next_camp=route[1]['id']
            elif (not self.shop_done and all(camp['id'] in c.cleared for camp in route)
                  and active and active['kind']=='shop' and active['id'] not in c.cleared):
                self.stage='shop';self.next_camp=active['id']
            else:return False
        if self.next_camp in c.cleared:
            self.finish(now,'target_already_cleared');return False
        dk=next((u for u in army if u.type=='Udea'),None)
        if not dk or b.battle_enemies or dk.handle in b.micro.pulling:return False
        bag=g.inventory(dk)
        yards=[u for u in g.my_buildings({'ugrv'}) if g.dist(u,b.home)<1200]
        if bag is None:return False
        if 'rnec' not in bag or not yards:
            self.finish(now,'rod_or_graveyard_unavailable');return False
        yard=min(yards,key=lambda u:g.dist(u,dk));point=(yard.x,yard.y)
        distance=g.path_distance((dk.x,dk.y),point)
        if distance is None or distance>4000 or not c.safe_route(g,(dk.x,dk.y),point):
            self.finish(now,'unsafe_or_unreachable');return False
        if self.mission is None:
            self.mission=dict(started=now,cast=None,before=set(),tries=0,at=-100)
            self.log('ch_graveyard_resummon_started',clock=now,point=point,next_camp=self.next_camp,stage=self.stage)
        m=self.mission
        fresh=[u for u in g.units('me',{'uske'}) if u.handle not in m['before'] and g.dist(u,dk)<1000]
        if m['cast'] is not None and len(fresh)>=2:
            self.finish(now,'two_new_skeletons_observed');return False
        if now-m['started']>60 or m['tries']>=3 and now-m['at']>3:
            self.finish(now,'bounded_timeout');return False
        c.pause(now,'ch_graveyard_resummon');b.set_intent('CH连续练级 · 坟场补骷髅后接'+('商店' if self.stage=='shop' else '食人魔'))
        if now<b.cast_until.get(dk.handle,0):return True
        if g.dist(dk,yard)>350:
            b.go(army,point,now);return True
        production=g.production(yard)
        if production and production.kind=='construction':return True
        if g.cooldown(dk,'AIrd')==0 and now-m['at']>=3:
            m['before']={u.handle for u in g.units('me',{'uske'})}
            m['tries']+=1;m['at']=now
            receipt=b.use_rod(dk,bag.index('rnec'),now)
            if receipt:m['cast']=now
            self.log('ch_graveyard_resummon_attempt',clock=now,accepted=bool(receipt),attempt=m['tries'])
        return True
