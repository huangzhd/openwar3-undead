"""Isolated API fixture, NOT a fair match or training sample. No desktop input."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.economy import Economy
from undead.controller import Controller
from undead.policy import Action
from undead.speed_control import SpeedControl

def main():
    session=Session(800);dev=None
    report={'version':'0.1.3-dev','fixture':True,'counts_as_match':False,'passed':False,'events':[]}
    def log(event,**kw):
        report['events'].append(dict(event=event,**kw))
        if event in ('fiend_upgrade_started','fiend_upgrades_observed','portal_purchase','attack_portal_ready'):
            print(json.dumps(dict(event=event,**kw)),flush=True)
    try:
        g=session.start()
        # Separate development client builds the fixture; policy retains fair=True.
        dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0]
        x,y=home.x,home.y
        p=dev.jass.Player(g.me())
        dev.jass.SetPlayerState(p,dev.jass.ConvertPlayerState(1),10000)
        dev.jass.SetPlayerState(p,dev.jass.ConvertPlayerState(2),10000)
        fixture=[('unp2',600,0),('ugrv',0,-600),('utom',600,-600),
                 ('Udea',400,-600),('Ulic',100,-300),('Nbrn',-100,-300)]
        fixture += [(c,-300+(i%4)*100,-650-(i//4)*100) for i,c in enumerate(['ucry']*6+['uobs']*2+['uaco']*2+['ugho']*2)]
        for code,dx,dy in fixture:
            u=dev.spawn(code,x+dx,y+dy)
            if not u:raise RuntimeError('Could not spawn '+code)
        time.sleep(.2)
        g.snapshot(max_age=0)
        report['initial_resources']=g.resources()
        if g.resources()['food_used']!=50:raise RuntimeError('Fixture population is not 50')
        economy=Economy(log);economy.ever_heroes={h.type for h in g.my_heroes()}
        bot=Controller(g,log);bot.home=home;bot.action=Action.ATTACK
        panel=SpeedControl(g,log)
        deadline=time.monotonic()+150
        portal=False;levels={}
        checked=-100
        while time.monotonic()<deadline:
            s=g.snapshot(max_age=0);now=s.clock
            panel.observe(s);g.events()
            economy.research_upgrades(g,now)
            army=g.units('me',{'Udea','Ulic','Nbrn','ucry','uobs'})
            portal=bot.prepare_attack(army,now)
            if now-checked>=3:
                checked=now
                levels=g.tech_many(['Rura','Rucr'])
                report['last_levels']=levels
                report['last_clock']=now
                if levels.get('Rura')==3 and levels.get('Rucr',0)>=1 and portal:
                    report['passed']=True
                    break
            time.sleep(.15)
        report['portal_in_dk_inventory']=portal
        report['dk_inventory']=g.inventory(next(h for h in g.my_heroes() if h.type=='Udea'))
        report['research_order']=[(r['code'],r['target_level']) for r in report['events'] if r['event']=='fiend_upgrade_started']
        if not report['passed']:report['error']='Fixture deadline without all conditions'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop()
        report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-upgrades-portal-0.1.3.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False,indent=2),flush=True)
    return report['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
