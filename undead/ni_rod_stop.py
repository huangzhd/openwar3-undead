"""One DK rod rebuy after the second prescribed NI, TH or AL camp."""
from math import hypot
from .battle_shop import RINGS


class NIRodStop:
    def __init__(self,log):
        self.log=log;self.mission=None;self.done=False;self.failed=False;self.map_alias='NI'

    def finish(self,now,reason,success=False):
        self.log(self.map_alias.lower()+'_dk_rod_end',clock=now,reason=reason,inventory_confirmed=success)
        self.done=success;self.failed=not success;self.mission=None

    def tick(self,b,army,now):
        c=b.creeping
        th=c.map_alias=='TH'
        al=c.map_alias=='AL'
        route=c.al_route(b.home) if al else c.th_route(b.home) if th else c.ni_opening(b.home)
        stage=c.al_route_stage(b.home) if al else c.th_route_stage(b.home) if th else c.ni_route_stage(b.home)
        if self.done or self.failed or len(route)<3 or stage!=route[2]:return False
        self.map_alias=c.map_alias
        if (c.al_contested if al else c.th_contested if th else c.ni_contested) or b.action.name in {'DEFEND','RETREAT'} or b.teleport:return False
        g=b.g;dk=next((h for h in g.my_heroes() if h.type=='Udea'),None)
        if dk is None:return False
        if self.mission is None:
            # An earlier actual second acquisition already fulfils the one rebuy.
            if not al and b.rod_acquisitions.get('Udea',0)>=2:
                self.done=True;return False
            bag=g.inventory(dk)
            if bag is None:return True
            camp=next(p for p in c.catalog if p['id']==route[2])
            length=max(1,hypot(b.home.x-camp['x'],b.home.y-camp['y']))
            rally=(camp['x']+(b.home.x-camp['x'])*1100/length,
                   camp['y']+(b.home.y-camp['y'])*1100/length)
            self.mission=dict(started=now,attempts=0,before={h.handle:(g.inventory(h) or []).count('rnec')
                              for h in g.my_heroes()},returning=False,rally=rally,sales={})
            if al:
                self.mission['rally']=(b.home.x,b.home.y)
            # A generic rod trip must not compete with this explicit route stop.
            if th or al:
                b.shop_goal=None;b.shop_code=None
            self.log(self.map_alias.lower()+'_dk_rod_started',clock=now,hero=dk.handle,after=route[1],before=route[2])
        m=self.mission
        if now-m['started']>120:
            self.finish(now,'purchase_or_rejoin_timeout');return False
        bag=g.inventory(dk)
        if bag is None:return True
        receipt=b.battle_shop.confirmed_buys.get((dk.handle,'rnec'))
        receipt=receipt if receipt and receipt['clock']>=m['started'] else None
        if receipt and bag.count('rnec')>m['before'].get(dk.handle,0) and not m['returning']:
            m['returning']=True
            b.rod_acquisitions['Udea']=max(2,b.rod_acquisitions.get('Udea',0))
            self.log(self.map_alias.lower()+'_dk_rod_inventory_confirmed',clock=now,hero=dk.handle)
        if al:c.pause(now,'al_home_rod_stop')
        # AL deliberately returns home once; NI/TH stage outside the next camp.
        escorts=[u for u in army if u.handle!=dk.handle]
        for u in escorts:
            if g.path_distance((u.x,u.y),m['rally']) is not None and c.safe_route(g,(u.x,u.y),m['rally']):
                b.go_raw([u],m['rally'],now)
        b.set_intent('AL前两营已清 · 回家补棒，冷却就绪则补骷髅后接商店' if al else
                     '第二营鱼人已清 · DK补一组骷髅棒后接门口433' if th else
                     '四鱼人已清 · DK补一组骷髅棒后接食人魔')
        if dk.handle in b.micro.pulling:return True
        if m['returning']:
            if al:return self.home_summon(b,dk,bag,now)
            if g.dist(dk,m['rally'])<=550:
                self.finish(now,'bought_and_rejoined',True);b.formation.reset();b.formation_at=-100
                return False
            target=m['rally']
        else:
            donor=next((h for h in g.my_heroes() if h.handle!=dk.handle and
                        receipt and (g.inventory(h) or []).count('rnec')>receipt['before'].get(h.handle,0)),None)
            shops=b.economy.ready(g,'utom')
            if al:shops=[s for s in shops if g.dist(s,b.home)<1200]
            shop=min(shops,key=lambda s:g.dist(s,dk),default=None)
            if donor is None and shop is None:return True
            recipient=donor or shop;target=(recipient.x,recipient.y)
            if g.dist(dk,target)<=280:
                if b.battle_shop.pending:return True
                if donor:
                    b.battle_shop.transact(g,donor,'rnec','give',now,b.cast_until,dk)
                elif th and (code:=next((c for c in bag if c in set(RINGS)|{'clsd'}
                                        and m['sales'].get(c,0)<3),None)):
                    if b.battle_shop.transact(g,dk,code,'sell',now,b.cast_until,shop):
                        m['sales'][code]=m['sales'].get(code,0)+1
                elif m['attempts']>=3:
                    self.finish(now,'three_unconfirmed_purchases');return False
                elif None in bag and g.resources()['gold']>=150 and not b.economy.revival_pending(g):
                    if b.battle_shop.transact(g,dk,'rnec','buy',now,b.cast_until,shop):m['attempts']+=1
                return True
        if g.path_distance((dk.x,dk.y),target) is None or not c.safe_route(g,(dk.x,dk.y),target):
            self.finish(now,'unsafe_or_unreachable');return False
        b.go_raw([dk],target,now)
        return True

    def home_summon(self,b,dk,bag,now):
        """Optional AL summon: no cooldown wait, bounded travel/effect confirmation."""
        g=b.g;m=self.mission
        def finish(reason,observed=False):
            self.log('al_home_summon_end',clock=now,reason=reason,skeletons_observed=observed)
            self.finish(now,'bought_home_stop_complete',True)
            b.formation.reset();b.formation_at=-100
            return False
        if now<b.cast_until.get(dk.handle,0):return True
        s=m.setdefault('summon',dict(started=now,at=None,tries=0,before=set()))
        if s['at'] is not None:
            fresh=[u for u in g.units('me',{'uske'}) if u.handle not in s['before'] and g.dist(u,dk)<1000]
            if len(fresh)>=2:return finish('two_new_skeletons_observed',True)
            if now-s['at']<3:return True
            if s['tries']>=2:return finish('summon_unconfirmed')
        if now-s['started']>=20:return finish('summon_time_limit')
        if 'rnec' not in bag:return finish('rod_unavailable')
        cooldown=g.cooldown(dk,'AIrd')
        if cooldown!=0:return finish('cooldown_unknown' if cooldown is None else 'cooldown_not_ready')
        yards=[u for u in b.economy.ready(g,'ugrv') if g.dist(u,b.home)<1200]
        if not yards:return finish('graveyard_unavailable')
        yard=min(yards,key=lambda u:g.dist(u,dk));point=(yard.x,yard.y)
        if g.path_distance((dk.x,dk.y),point) is None or not b.creeping.safe_route(g,(dk.x,dk.y),point):
            return finish('graveyard_unreachable_or_unsafe')
        if g.dist(dk,yard)>350:
            b.go_raw([dk],point,now);return True
        s['before']={u.handle for u in g.units('me',{'uske'})};s['at']=now;s['tries']+=1
        accepted=b.use_rod(dk,bag.index('rnec'),now)
        self.log('al_home_summon_attempt',clock=now,accepted=bool(accepted),attempt=s['tries'])
        return True
