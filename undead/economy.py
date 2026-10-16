"""Fixed tech-fiend economy. One purchase per decision avoids stale-budget overspend."""
from math import hypot
from .expansion import Expansion
from .building_repair import BuildingRepair
from .hall_rebuild import HallRebuild
from .home_layout import HomeLayout

HALLS={'unpl','unp1','unp2'}

class Economy:
    def __init__(self, log, third_hero="Nbrn"):
        self.log=log
        self.third_hero=third_hero
        self.complete=set()
        self.ghoul_reserved=set()
        self.ever_heroes=set()
        self.last_attempt={}
        self.last_build=-100
        self.builder=None
        self.scout=None
        self.scout_losses=0;self.enemy_start_known=False
        self.first_fiend=False
        self.opening_started=False
        self.opening_complete=False
        self.opening_rod_allowed=True
        self.opening_rod_seen=False
        self.opening_milestones=set()
        self.save_for_tp=False
        self.allow_tp=True
        self.frontline_combat=False
        self.home_tower_needed=False
        self.home_tower_point=None
        self.home_tower_attempts=0
        self.home_tower_at=-100
        self.save_for_trade=False
        self.upgrade_levels=None
        self.upgrade_checked=-100
        self.upgrade_reserving=False
        self.enemy_air_seen=False
        self.web_level=None
        self.web_checked=-100
        self.web_reserving=False
        self.web_attempts=0
        self.expansion=Expansion(log)
        self.repairs=BuildingRepair(log)
        self.hall_rebuild=HallRebuild(log)
        self.home_layout=HomeLayout(log)
        self.slaughter_missing_since=None
        self.mass_army=False
        self.bank_item_reserve=0
        self.upkeep_released=False
        self.upkeep_crossed=False
        self.upkeep_threat=False
        self.upkeep_log_at=-100
        self.home_handle=None
        self.revival_state=None
        self.revival_retry=None
        self.revival_attempts=0
        self.tech_budget_log_at=-100
        self.destroyer_research_attempts=0
        self.destroyer_research_at=-100

    def opening_observed(self,stage,now):
        if stage not in self.opening_milestones:
            self.opening_milestones.add(stage)
            self.log('opening_observed',clock=now,stage=stage)

    def ready(self,g,code):
        buildings=g.my_buildings({code})
        for b in buildings:
            p=g.production(b)
            if b.hp >= b.hp_max*.999 and (not p or p.kind!='construction'):
                self.complete.add(b.handle)
        return [b for b in buildings if b.handle in self.complete]

    def queued(self,g,code):
        return sum(p.queue.count(code) for _,p in g.all_production('me') if p.kind=='queue')

    def count(self,g,code):
        return len(g.units('me',{code}))+self.queued(g,code)

    def train(self,g,b,code,now):
        food={'ucry':3,'uobs':3,'ugho':2,'uaco':1}.get(code,0)
        res=g.resources()
        if (code=='ucry' and self.count(g,'ucry')>=2
                and 'Ulic' not in self.ever_heroes and not self.queued(g,'Ulic')):
            return False # Third fiend follows the paid tier-three and Lich orders.
        if (code=='ucry' and not self.upkeep_released and not self.upkeep_threat
                and res['food_used']<=50 and self.count(g,'ucry')>=4):return False
        # Leave two food for a statue's transformation before releasing upkeep.
        morph_food=2 if (self.mass_army and not self.upkeep_released and not self.upkeep_threat
                        and res['food_used']<=50 and not self.count(g,'ubsp')) else 0
        if food and morph_food and res['food_used']+food+morph_food>50:return False
        # Keep Lich's five food free while optional supply waits for his
        # recruitment and the slaughterhouse foundation (including tier-two research).
        if (code in {'ucry','ugho','uobs'} and self.opening_complete
                and 'Ulic' not in self.ever_heroes and not self.queued(g,'Ulic')
                and res['food_used']+food+5>res['food_cap']):
            return False
        # AZ 20261013-003657: the courier was still hiring when a spider
        # spent 45 -> 48 food; the third hero then forced 53 before research.
        # Warcraft charges queued unit food immediately, so food_used already
        # includes production queues. Reserve only the not-yet-paid hero slot.
        if (food and self.third_hero not in self.ever_heroes
                and self.count(g,self.third_hero)==0 and res['food_used']+food+5>50):
            if now-self.upkeep_log_at>=5:
                self.upkeep_log_at=now
                self.log('third_hero_food_reserved',clock=now,food=res['food_used'],
                         blocked=code,hero=self.third_hero,reserved_food=5)
            return False
        if (food and self.mass_army and not self.upkeep_released and not self.upkeep_threat
                and res['food_used']+food>50 and (res['food_used']<=50 or code=='ucry')):
            if now-self.upkeep_log_at>=5:
                self.upkeep_log_at=now
                self.log('upkeep_bank_wait',clock=now,gold=res['gold'],food=res['food_used'],blocked=code,target_gold=400)
            return False
        if g.production(b) or now-self.last_attempt.get((b.handle,code),-100)<2:
            return False
        self.last_attempt[(b.handle,code)]=now
        verdict=g.can_do(b,code)
        if verdict not in (0,220):
            return False
        r=g.train(b,code)
        self.log('purchase',clock=now,kind='train',code=code,accepted=bool(r),reason=r.reason)
        return bool(r)

    def build(self,g,code,home,now):
        if (code=='uzig' and len(g.my_buildings({'uzig','uzg1','uzg2'}))>=4
                and self.third_hero not in self.ever_heroes):return False
        if code in self.home_layout.pending:return True
        if not g.can_afford(code) or now-self.last_build<1:
            return False
        ws=[w for w in g.units('me',{'uaco'}) if w.handle != self.scout and w.handle not in self.home_layout.reserved and w.handle not in self.expansion.reserved and w.handle not in self.repairs.reserved and not g.is_constructing(w)]
        if not ws:
            return False
        # Prefer a released/idle worker over pulling another miner away.
        ws.sort(key=lambda w:(bool(g.order_of(w)),hypot(w.x-home.x,w.y-home.y)))
        self.last_build=now
        spot=self.home_layout.build(g,ws[0],code,home,now)
        if spot:
            self.log('purchase',clock=now,kind='build',code=code,spot=spot)
        return bool(spot)

    def tick(self,g,now,threat=False):
        self.upkeep_threat=threat
        halls=g.my_buildings(HALLS)
        if not halls:
            self.hall_rebuild.tick(g,self,now,threat)
            return
        home=next((h for h in halls if h.handle==self.home_handle),halls[0])
        self.hall_rebuild.observe(g,home,now)
        self.home_handle=home.handle
        self.home_layout.observe(g,now)
        if not self.opening_started:
            self.opening_started=True
            self.opening_complete=home.type in {"unp1","unp2"}
            self.opening_rod_allowed=True
        for b in g.my_buildings():
            p=g.production(b)
            if b.hp >= b.hp_max*.999 and (not p or p.kind!='construction'):
                self.complete.add(b.handle)
        for h in g.my_heroes():
            self.ever_heroes.add(h.type)
        workers=g.units('me',{'uaco'})
        self.expansion.observe(g)
        self.expansion.upkeep(g,home,now)
        repair_critical=self.repairs.tick(g,self,home,now)
        if self.scout is not None and not any(w.handle==self.scout for w in workers):
            self.scout_losses+=1
            self.log('scout_lost',clock=now,handle=self.scout,losses=self.scout_losses)
            self.scout=None
        # At most two replacement scouts; never take a worker from the five mining slots.
        need_scout=self.scout_losses==0 or (self.scout_losses<=2 and not self.enemy_start_known)
        if need_scout and self.scout is None and not self.expansion.retired_scout and len(workers)>=6:
            self.scout=workers[-1].handle
            self.log('scout_assigned',handle=self.scout)
        mine=g.nearest([m for m in g.gold_mines() if m.type=='ugol' and m.owner==g.me()],home)
        for w in g.idle_workers():
            if mine and w.handle!=self.scout and w.handle not in self.home_layout.reserved and w.handle not in self.ghoul_reserved and w.handle not in self.expansion.reserved and w.handle not in self.repairs.reserved:
                g.gather(w,mine)
        trees=None
        for w in g.units('me',{'ugho'}):
            if w.handle in self.ghoul_reserved:continue
            if not g.order_of(w) and not w.has_task:
                trees=trees if trees is not None else g.trees(home.x,home.y)
                if trees:
                    g.gather(w,trees[0])
        res=g.resources()
        if not res:
            return
        if res['food_used']>50:
            self.upkeep_crossed=True # A hired/revived hero crossing 50 is not a budget release.
        elif self.upkeep_crossed:
            self.upkeep_released=False;self.upkeep_crossed=False
            self.log('upkeep_bank_reset',clock=now,food=res['food_used'])
        if repair_critical:return # Preserve a critically damaged live base before paying for revival.
        if self.revive_priority(g,home,now,res):return
        if self.home_tower_needed and self.defense_tower(g,home,now):return
        if self.save_for_trade:return
        if self.save_for_tp and not threat and not self.frontline_combat:
            if not g.my_buildings({'utom'}):
                self.build(g,'utom',home,now)
            return
        # Buy the first rod as soon as DK exists; do not spend its gold on
        # another ghoul or Graveyard while the hero is approaching the shop.
        dk=next((h for h in g.my_heroes() if h.type=='Udea'),None)
        if not self.opening_complete and dk and not self.opening_rod_seen:
            self.opening_rod_seen='rnec' in (g.inventory(dk) or [])
            if not self.opening_rod_seen:
                if not g.my_buildings({'utom'}):self.build(g,'utom',home,now)
                return
        if self.expansion.pending_budget(now):return
        altars=self.ready(g,'uaod')
        if altars and not g.production(altars[0]):
            if 'Udea' not in self.ever_heroes and self.train(g,altars[0],'Udea',now):return
        # Independent producers: initial workers need not wait for altar construction.
        if self.count(g,'uaco')<5 and self.train(g,home,'uaco',now):
            # Snapshot resources precede the command; explicitly subtract its 75 gold.
            if not g.my_buildings({'uaod'}) and res['gold']>=75+180 and res['lumber']>=50:
                self.build(g,'uaod',home,now)
            return
        if self.research_web(g,now):
            return
        for code in ('uaod','uzig'):
            if not g.my_buildings({code}):
                self.build(g,code,home,now)
                return
        if not g.my_buildings({'usep'}):
            self.build(g,'usep',home,now)
            return
        if need_scout and self.scout is None and not self.expansion.retired_scout and self.count(g,'uaco')<6 and self.train(g,home,'uaco',now):
            return
        crypts=self.ready(g,'usep')
        hp=g.production(home)
        upgrading=hp is not None and hp.kind=='upgrade'
        tier=3 if home.type=='unp2' and not upgrading else 2 if home.type in {'unp1','unp2'} else 1
        fiends=self.count(g,'ucry')
        self.first_fiend=self.first_fiend or fiends>0
        # Opening spends in the user-confirmed order. Observe completion/inventory,
        # not a successful command receipt, before releasing the next budget.
        if not self.opening_complete:
            # Crypt readiness, not Graveyard completion, releases the two ghouls.
            if crypts:
                self.opening_observed('crypt_complete',now)
                if self.count(g,'ugho')<3:
                    self.train(g,crypts[0],'ugho',now)
                    return
            if not g.my_buildings({'utom'}):
                self.build(g,'utom',home,now)
                return
            if not g.my_buildings({'ugrv'}):
                self.build(g,'ugrv',home,now)
                return
            if not crypts or len(g.units('me',{'ugho'}))<3:return
            self.opening_observed('three_ghouls_alive',now)
            self.opening_rod_allowed=True
            dk=next((h for h in g.my_heroes() if h.type=='Udea'),None)
            self.opening_rod_seen=self.opening_rod_seen or bool(dk and 'rnec' in (g.inventory(dk) or []))
            if not self.opening_rod_seen:return
            self.opening_observed('dk_rod_in_inventory',now)
            if tier==1 and not upgrading:
                self.train(g,home,'unp1',now)
                return
            self.opening_observed('tier_two_started',now)
            # Pay the first fiend before the second ziggurat. Its observed
            # production queue releases supply; a command receipt alone does not.
            if not self.first_fiend:
                if not self.ready(g,'ugrv'):return
                self.opening_observed('graveyard_complete',now)
                if crypts:self.train(g,crypts[0],'ucry',now)
                return
            self.opening_observed('first_fiend_alive_or_queued',now)
            if len(g.my_buildings({'uzig'}))<2:
                self.build(g,'uzig',home,now)
                return
            self.opening_complete=True
            self.log('opening_order_complete',clock=now,rod_observed=True,fiend_present_or_queued=True)
        # Resume the original population, replacement and technology priorities.
        # Use actual construction records; a completed tower can already be damaged.
        pending_zig=any((p:=g.production(b)) is not None and p.kind=='construction'
                        for b in g.my_buildings({'uzig'}))
        lich=next((h for h in g.my_heroes() if h.type=='Ulic'),None)
        if tier==3 and lich and 'ocor' in (g.inventory(lich) or []):
            if not self.mass_army:self.log('army_growth_started',clock=now,food_target=100)
            self.mass_army=True
        # User order: pay tier three, then Lich, then slaughterhouse and new supply.
        if tier==2 and not upgrading:
            self.train(g,home,'unp2',now)
            return
        if tier>=2 and 'Ulic' not in self.ever_heroes and not self.queued(g,'Ulic'):
            if res['food_cap']-res['food_used']<5:
                if not pending_zig and res['food_cap']<100:self.build(g,'uzig',home,now)
                return # Only the population required to hire Lich may precede him.
            if altars and not g.production(altars[0]):self.train(g,altars[0],'Ulic',now)
            return
        if tier>=2 and not g.my_buildings({'uslh'}):
            if self.slaughter_missing_since is None:self.slaughter_missing_since=now
            # Tier three is already paid. Preserve the house budget if placement stalls.
            if (now-self.slaughter_missing_since>=10 and res['gold']>=355 and res['lumber']>=175
                    and crypts and fiends<6 and self.train(g,crypts[0],'ucry',now)):
                self.log('construction_stall_reinforcement',clock=now,blocked='uslh',gold=res['gold'],lumber=res['lumber'])
                return
            self.build(g,'uslh',home,now)
            return
        slaughter=self.ready(g,'uslh')
        if tier==3 and self.research_destroyer(g,slaughter,now):return
        supply_unlocked=(bool(g.my_buildings({'uslh'}))
                         and ('Ulic' in self.ever_heroes or bool(self.queued(g,'Ulic'))))
        if supply_unlocked and res['food_cap']-res['food_used']<=(12 if self.mass_army else 6) and res['food_cap']<100 and not pending_zig:
            if self.build(g,'uzig',home,now):return
        if not g.my_buildings({'utom'}):
            self.build(g,'utom',home,now)
            return
        if crypts and self.count(g,'ugho')<3 and self.train(g,crypts[0],'ugho',now):return
        if not g.my_buildings({'ugrv'}):
            self.build(g,'ugrv',home,now)
            return
        if tier==1 and not upgrading:
            self.train(g,home,'unp1',now)
            return
        if slaughter and self.count(g,'uobs')<self.army_targets(g,now)[1] and self.train(g,slaughter[0],'uobs',now):
            return
        # Preserve funds for the orb and third hero after tier 3.
        lich=next((h for h in g.my_heroes() if h.type=='Ulic'),None)
        if tier==3 and lich and 'ocor' not in (g.inventory(lich) or []) and res['gold']<450:
            return
        if tier==3 and self.third_hero not in self.ever_heroes and fiends>=4 and res['gold']<550:
            return
        if self.research_upgrades(g,now) or self.upgrade_reserving:
            return
        # Fiends/statues cost 3 food: 48-50 is the last batch before the 50 cap.
        if self.banking(g) and not threat:
            heroes=g.my_heroes()
            bags=[g.inventory(h) for h in heroes]
            reserve=(0 if not self.allow_tp or self.frontline_combat or any(b is None or 'stwp' in b for b in bags) else 350)+self.bank_item_reserve
            # LR 0.1.77 broke 50 at 757 gold while the third hero and first
            # attack upgrade still needed funding. Only uncommitted gold counts.
            reserve+=425 if self.third_hero not in self.ever_heroes else 0
            if not self.count(g,'ubsp'):reserve+=100 # Keep the first transformation funded.
            levels=g.tech_many(['Rura','Rucr'])
            attack,armor=levels.get('Rura'),levels.get('Rucr')
            if attack is None or armor is None:
                return # Unknown own research is not a completed upgrade.
            code,level=('Rura',attack) if attack<3 else ('Rucr',armor)
            queued={c for _,p in g.all_production('me') for c in p.queue}
            if level<3 and code not in queued:reserve+=150+50*level
            if self.bank_item_reserve or res['gold']<400+reserve:
                if now-self.upkeep_log_at>=5:
                    self.upkeep_log_at=now
                    self.log('upkeep_bank_wait',clock=now,gold=res['gold'],food=res['food_used'],target_gold=400,reserved_items=reserve)
                return
            if self.third_hero not in self.ever_heroes:
                return # Courier funds/food are not a release to break upkeep.
            self.upkeep_released=True
            self.log('upkeep_burst_released',clock=now,gold=res['gold'],food=res['food_used'],reserved_items=reserve)
        if self.mass_army and self.expansion.tick(g,self,home,now,threat):return
        if self.expansion.pending_budget(now):return
        target,_=self.army_targets(g,now)
        if fiends<target:
            # At the end of tier two research, reserve tier three before
            # another optional fiend consumes its bank.
            if (home.type=='unpl' and upgrading and getattr(hp,'progress',0)>=.6
                    and 'Ulic' not in self.ever_heroes and not self.queued(g,'Ulic')):
                gold=325
                lumber=230
                if res['gold']<gold+215 or res['lumber']<lumber+40:
                    if now-self.tech_budget_log_at>=5:
                        self.tech_budget_log_at=now
                        self.log('tech_transition_budget_reserved',clock=now,gold=res['gold'],lumber=res['lumber'],
                                 reserved_gold=gold,reserved_lumber=lumber,blocked='ucry')
                    return
            for crypt in crypts:
                if self.train(g,crypt,'ucry',now):return
        if self.mass_army and fiends<target and len(g.my_buildings({'usep'}))<2 and res['gold']>=900 and all(g.production(c) for c in crypts):
            if self.build(g,'usep',home,now):return
        if self.count(g,'uaco')<5 and self.train(g,home,'uaco',now):
            return

    def missing_heroes(self,g):
        return self.ever_heroes-{h.type for h in g.my_heroes()}

    def revival_pending(self,g):
        missing=self.missing_heroes(g)
        if not missing:return set()
        paid={code for b,p in g.all_production('me') if b.type=='uaod' and p.kind=='queue' for code in p.queue}
        return missing-paid

    def revive_priority(self,g,home,now,res):
        missing=self.missing_heroes(g);pending=self.revival_pending(g)
        state=(tuple(sorted(missing)),tuple(sorted(pending)))
        if state!=self.revival_state:
            if missing or self.revival_state and self.revival_state[0]:
                self.log('hero_revival_state',clock=now,missing=sorted(missing),
                         awaiting_payment=sorted(pending),queued=sorted(missing-pending))
            self.revival_state=state
        if not pending:return False # Observed queue is paid; remaining production may resume.
        # Only prerequisites to revive or restore a completely lost income source may spend.
        if not g.units('me',{'uaco'}):
            self.train(g,home,'uaco',now);return True
        if not g.my_buildings({'uaod'}):
            self.build(g,'uaod',home,now);return True
        if res['food_cap']-res['food_used']<5:
            if res['food_cap']<100 and not any(g.production(b) and g.production(b).kind=='construction'
                                              for b in g.my_buildings({'uzig'})):
                self.build(g,'uzig',home,now)
            return True
        altars=[b for b in self.ready(g,'uaod') if not g.production(b)]
        if not altars:return True
        signature=(tuple(sorted(pending)),res['gold'],res['lumber'],res['food_cap'],res['food_used'],altars[0].handle)
        if signature!=self.revival_retry:
            self.revival_retry=signature;self.revival_attempts=0
        if self.revival_attempts>=3 or now-self.last_attempt.get('revive',-100)<4:return True
        self.last_attempt['revive']=now;self.revival_attempts+=1
        r=g.revive(altars[0])
        self.log('revive_attempt',clock=now,heroes=sorted(pending),accepted=bool(r),
                 reason=getattr(r,'reason',None),note=getattr(r,'note',None),
                 gold=res['gold'],lumber=res['lumber'],attempt=self.revival_attempts)
        if r:self.log('revive',clock=now,heroes=sorted(pending))
        return True # Rejection or receipt alone never releases the reserved funds.

    def army_targets(self,g,now):
        if not self.upkeep_released and not self.upkeep_threat and g.resources()['food_used']<=50:
            tier_three=any(h.type=='unp2' and not (g.production(h) and g.production(h).kind=='upgrade')
                           for h in g.my_buildings(HALLS))
            return 4,3 if tier_three and not self.count(g,'ubsp') else 2
        statues=2 # One sustained life source and one sustained mana source.
        workers=max(10,self.count(g,'uaco'))
        fiends=max(0,(100-15-2*max(3,self.count(g,'ugho'))-workers-3*max(statues,self.count(g,'uobs'))-5*self.count(g,'ubsp'))//3)
        return fiends,statues

    def banking(self,g):
        # A four-fiend core holds at 47 before morph (49 after), not the old 48.
        ready=self.count(g,'ucry')>=4 and self.count(g,'uobs')>=self.army_targets(g,0)[1]
        return self.mass_army and not self.upkeep_released and (g.resources()['food_used']>=48
                or ready and g.resources()['food_used']>=47)

    def research_destroyer(self,g,slaughter,now):
        level=g.tech_many(['Rusp']).get('Rusp')
        if level is None or level>=1:return False
        if any('Rusp' in p.queue for _,p in g.all_production('me')):return False
        if self.destroyer_research_attempts>=3:return False
        idle=[b for b in slaughter if not g.production(b)]
        if not idle:return False
        res=g.resources()
        if res['gold']<75 or res['lumber']<150:return True
        if now-self.destroyer_research_at<4:return True
        self.destroyer_research_at=now;self.destroyer_research_attempts+=1
        accepted=self.train(g,idle[0],'Rusp',now)
        self.log('destroyer_research_attempt',clock=now,accepted=accepted,attempt=self.destroyer_research_attempts)
        return True

    def research_web(self,g,now):
        if not self.enemy_air_seen:return False
        if now-self.web_checked<3:return self.web_reserving
        self.web_checked=now;self.web_reserving=False
        level=g.tech_many(['Ruwb']).get('Ruwb')
        if level is None:return False
        if level!=self.web_level:
            self.web_level=level
            self.log('web_level_observed',clock=now,level=level)
        if level>=1:return False
        if any('Ruwb' in p.queue for _,p in g.all_production('me')):return False
        # One-time air response, ahead of optional tech/fiends/attack upgrades; do not cancel queues.
        if not g.my_buildings({'unp1','unp2'}):return False
        crypts=self.ready(g,'usep')
        if not crypts or not g.units('me',{'ucry'}) or self.web_attempts>=3:return False
        res=g.resources()
        self.web_reserving=True
        if res['gold']<150 or res['lumber']<150:return True
        for crypt in crypts:
            if g.production(crypt):continue
            if g.can_do(crypt,'Ruwb') not in (0,220):
                self.web_reserving=False
                continue
            self.web_attempts+=1
            accepted=self.train(g,crypt,'Ruwb',now)
            self.log('web_research_attempt',clock=now,accepted=accepted,attempt=self.web_attempts)
            if accepted:
                self.web_reserving=False
                return True
            if self.web_attempts>=3:
                self.web_reserving=False
                self.log('web_research_blocked',clock=now,reason='command_retry_limit')
            return self.web_reserving
        return self.web_reserving

    def defense_tower(self,g,home,now):
        """At most one Spirit Tower, upgrading existing supply only when harassed."""
        buildings=[b for b in g.my_buildings() if g.dist(b,home)<1600]
        if any(b.type=='uzg1' or (p:=g.production(b)) and 'uzg1' in p.queue for b in buildings):return False
        if self.home_tower_attempts>=3:return False
        choices=[b for b in self.ready(g,'uzig') if b in buildings and not g.production(b)]
        if not choices:return False
        res=g.resources()
        # Installed unit costs are cumulative: 295/90 minus Ziggurat 150/50.
        if res['gold']<145 or res['lumber']<40:return True
        if now-self.home_tower_at<4:return True
        tower=min(choices,key=lambda b:g.dist(b,self.home_tower_point or home))
        if g.can_do(tower,'uzg1') not in (0,220):return False
        self.home_tower_at=now;self.home_tower_attempts+=1
        result=g.train(tower,'uzg1')
        self.log('home_tower_upgrade_attempt',clock=now,handle=tower.handle,accepted=bool(result),
                 reason=getattr(result,'reason',None),attempt=self.home_tower_attempts)
        return bool(result)

    def research_upgrades(self,g,now):
        res=g.resources()
        banking=self.banking(g)
        self.upgrade_reserving=False
        if res['food_used']<50 and not banking:return False
        graves=self.ready(g,'ugrv')
        if not graves:return False
        levels=g.tech_many(['Rura','Rucr']) # own player only; unknown is not level zero
        attack,armor=levels.get('Rura'),levels.get('Rucr')
        if attack is None or armor is None:return False
        if self.upgrade_levels!=(attack,armor):
            self.upgrade_levels=(attack,armor)
            self.log('fiend_upgrades_observed',clock=now,attack=attack,armor=armor)
        if attack>=3 and armor>=3:return False
        code,level=('Rura',attack) if attack<3 else ('Rucr',armor)
        # Exact per-level costs from this installation's UpgradeData.slk.
        gold=150+50*level
        lumber=(50+75*level) if code=='Rura' else (75+125*level)
        heroes=g.my_heroes()
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        dk=next((h for h in heroes if h.type=='Udea'),None)
        target,statues=self.army_targets(g,now)
        reserve_gold=215*max(0,min(4,target)-self.count(g,'ucry'))+200*max(0,statues-self.count(g,'uobs'))
        reserve_lumber=40*max(0,min(4,target)-self.count(g,'ucry'))+35*max(0,statues-self.count(g,'uobs'))
        if banking:reserve_gold=reserve_lumber=0 # Prioritize tech over units held by the upkeep cap.
        if lich and 'ocor' not in (g.inventory(lich) or []):reserve_gold+=375
        if self.third_hero not in self.ever_heroes:
            reserve_gold+=425;reserve_lumber+=135
        if self.allow_tp and not self.frontline_combat and not any('stwp' in (g.inventory(h) or []) for h in heroes):reserve_gold+=350
        # A paid research queue runs alongside spiders. An idle Graveyard saves
        # for the next attack/armor level instead of losing its budget to fiends.
        if any(code in p.queue for _,p in g.all_production('me')):return False
        graves=[b for b in graves if not g.production(b)]
        if not graves:return False
        self.upgrade_reserving=self.mass_army
        if res['gold']<gold+reserve_gold or res['lumber']<lumber+reserve_lumber:
            if now-self.upgrade_checked>=3:
                self.upgrade_checked=now
                self.log('fiend_upgrade_saving',clock=now,code=code,target_level=level+1,
                         gold=res['gold'],required_gold=gold+reserve_gold,
                         lumber=res['lumber'],required_lumber=lumber+reserve_lumber)
            return False
        if now-self.upgrade_checked<3:return False
        self.upgrade_checked=now
        for grave in graves:
            if self.train(g,grave,code,now):
                self.log('fiend_upgrade_started',clock=now,code=code,target_level=level+1,
                         gold=gold,lumber=lumber,reserved_gold=reserve_gold,reserved_lumber=reserve_lumber)
                return True
        return False

    def optional_reserve(self,g,now):
        """Gold commitments before optional scrolls; queued costs are already paid."""
        heroes=g.my_heroes();types={h.type for h in heroes}
        # Finish reviving missing heroes before discretionary shopping.
        if self.ever_heroes-types:return float('inf')
        target,statues=self.army_targets(g,now)
        # Reserve the next concurrent production cycle, not an entire future army.
        gold=215*min(2,max(0,target-self.count(g,'ucry')))+200*max(0,statues-self.count(g,'uobs'))
        if self.banking(g):gold=0
        gold+=75*max(0,5-self.count(g,'uaco'))
        for code,cost in [('Udea',425),('Ulic',425),(self.third_hero,425)]:
            if code not in types and not self.queued(g,code):gold+=cost
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        dk=next((h for h in heroes if h.type=='Udea'),None)
        if not lich or 'ocor' not in (g.inventory(lich) or []):gold+=375
        if self.allow_tp and not self.frontline_combat and not any('stwp' in (g.inventory(h) or []) for h in heroes):gold+=350
        halls=g.my_buildings(HALLS)
        if not halls:return float('inf')
        home=next((h for h in halls if h.handle==self.home_handle),halls[0]);upgrading=bool(g.production(home) and g.production(home).kind=='upgrade')
        if home.type=='unpl':gold+=325 if upgrading else 645
        elif home.type=='unp1' and not upgrading:gold+=325
        for code,cost in [('uslh',140),('ugrv',215),('utom',130)]:
            if not g.my_buildings({code}):gold+=cost
        res=g.resources()
        if res.get('food_cap',100)-res.get('food_used',0)<=6 and not any(
            g.production(b) and g.production(b).kind=='construction' for b in g.my_buildings({'uzig'})):gold+=150
        levels=g.tech_many(['Rura','Rucr','Ruwb'])
        if levels.get('Rura') is None or levels.get('Rucr') is None:return float('inf')
        queued={c for _,p in g.all_production('me') for c in p.queue}
        attack,armor=levels['Rura'],levels['Rucr']
        code,level=('Rura',attack) if attack<3 else ('Rucr',armor)
        if level<3 and code not in queued:gold+=150+50*level
        if self.enemy_air_seen and levels.get('Ruwb') is None:return float('inf')
        if self.enemy_air_seen and levels.get('Ruwb',0)<1 and 'Ruwb' not in queued:gold+=150
        return gold
