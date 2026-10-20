"""One DK rod rebuy after the second prescribed NI or TH camp."""
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
        route=c.th_route(b.home) if th else c.ni_opening(b.home)
        stage=c.th_route_stage(b.home) if th else c.ni_route_stage(b.home)
        if self.done or self.failed or len(route)<3 or stage!=route[2]:return False
        self.map_alias='TH' if th else 'NI'
        if (c.th_contested if th else c.ni_contested) or b.action.name in {'DEFEND','RETREAT'} or b.teleport:return False
        g=b.g;dk=next((h for h in g.my_heroes() if h.type=='Udea'),None)
        if dk is None:return False
        if self.mission is None:
            # An earlier actual second acquisition already fulfils the one rebuy.
            if b.rod_acquisitions.get('Udea',0)>=2:
                self.done=True;return False
            bag=g.inventory(dk)
            if bag is None:return True
            camp=next(p for p in c.catalog if p['id']==route[2])
            length=max(1,hypot(b.home.x-camp['x'],b.home.y-camp['y']))
            rally=(camp['x']+(b.home.x-camp['x'])*1100/length,
                   camp['y']+(b.home.y-camp['y'])*1100/length)
            self.mission=dict(started=now,attempts=0,before={h.handle:(g.inventory(h) or []).count('rnec')
                              for h in g.my_heroes()},returning=False,rally=rally,sales={})
            # A generic rod trip must not compete with this explicit route stop.
            if th:
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
        # Reinforcements stage outside the next camp, rather than following DK home.
        escorts=[u for u in army if u.handle!=dk.handle]
        for u in escorts:
            if g.path_distance((u.x,u.y),m['rally']) is not None and c.safe_route(g,(u.x,u.y),m['rally']):
                b.go_raw([u],m['rally'],now)
        b.set_intent('第二营鱼人已清 · DK补一组骷髅棒后接门口433' if th else
                     '四鱼人已清 · DK补一组骷髅棒后接食人魔')
        if dk.handle in b.micro.pulling:return True
        if m['returning']:
            if g.dist(dk,m['rally'])<=550:
                self.finish(now,'bought_and_rejoined',True);b.formation.reset();b.formation_at=-100
                return False
            target=m['rally']
        else:
            donor=next((h for h in g.my_heroes() if h.handle!=dk.handle and
                        receipt and (g.inventory(h) or []).count('rnec')>receipt['before'].get(h.handle,0)),None)
            shops=b.economy.ready(g,'utom')
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
