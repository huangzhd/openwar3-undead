"""Isolated air/web API fixture; not a normal match or training sample."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller


def main():
    report={'version':'0.1.9-dev','fixture':True,'counts_as_match':False,'passed':False,'events':[]}
    session=Session(400);dev=None
    def log(event,**kw):
        row=dict(event=event,**kw);report['events'].append(row)
        if event.startswith(('enemy_air','web_')):print(json.dumps(row),flush=True)
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0];x,y=home.x,home.y
        player=dev.jass.Player(g.me())
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(1),2000)
        dev.jass.SetPlayerState(player,dev.jass.ConvertPlayerState(2),2000)
        for code,dx,dy in [('unp2',650,0),('usep',0,-650),('ugrv',650,-650),
                           ('ucry',-300,-400),('ucry',-100,-400),('ucry',100,-400)]:
            if not dev.spawn(code,x+dx,y+dy):raise RuntimeError('Could not spawn '+code)
        enemy=dev.spawn('hgry',x-100,y-650,player=1 if g.me()==0 else 0)
        if not enemy:raise RuntimeError('Could not spawn visible air fixture')
        dev.jass.PauseUnit(enemy.jass_handle,True) # fixture target stays in sight; engine still applies web
        bot=Controller(g,log);deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            s=g.snapshot(max_age=0);now=s.clock
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop')
            bot.observe_air(g.enemies(),now)
            bot.economy.research_web(g,now)
            bot.skills(now)
            report['level']=bot.economy.web_level
            if report['level']==1 and bot.web_effects:
                report['passed']=True;report['game_seconds']=now;break
            time.sleep(.2)
        if not report['passed']:report['error']='Deadline without confirmed research and real web buff'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-web-fixture-0.1.9.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False),flush=True)
    return report['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
