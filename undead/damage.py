"""Short-lived incoming-damage estimates from own hero health observations only."""
class DamageTrend:
    def __init__(self):self.samples={};self.rates={}
    def observe(self,heroes,now):
        live={u.handle for u in heroes}
        self.samples={h:v for h,v in self.samples.items() if h in live};self.rates={}
        for u in heroes:
            samples=[p for p in self.samples.get(u.handle,[]) if 0<now-p[0]<=3]
            rates=[max(0,p[1]-u.hp)/(now-p[0]) for p in samples if now-p[0]>=.5]
            self.rates[u.handle]=max(rates,default=0)
            self.samples[u.handle]=samples+[(now,u.hp)]
    def urgent(self,u,window=8):
        rate=self.rates.get(u.handle,0)
        return u.hp/u.hp_max<.8 and rate>0 and u.hp/rate<=window
