"""Isolated real Lightning Shield fixture; never a normal match or training sample."""
import json,time,traceback
from bootstrap import ROOT
from session import Session
from openwar3 import Game
from undead.controller import Controller
from undead.hazards import SHIELD_BUFFS,SAFE_GAP


def main():
    report=dict(version='0.1.19-dev',fixture=True,counts_as_match=False,passed=False,events=[],samples=[])
    session=Session(400);dev=None
    try:
        g=session.start();dev=Game(pid=g.pid,fair=False)
        home=g.my_buildings({'unpl'})[0];mp=g.map()
        origin=next(( (home.x+dx,home.y+dy) for dx,dy in [(700,-500),(700,500),(-700,-500),(-700,500)]
                     if all(mp.walkable(home.x+dx+ox,home.y+dy) for ox in [0,70,-400])),None)
        if not origin:raise RuntimeError('No walkable fixture location')
        x,y=origin
        carrier=dev.spawn('ucry',x,y);ally=dev.spawn('ucry',x+70,y);caster=dev.spawn('nwzg',x-400,y)
        if not all([carrier,ally,caster]):raise RuntimeError('Fixture spawn failed')
        bot=Controller(g,lambda event,**kw:report['events'].append(dict(event=event,**kw)))
        handles=[carrier.handle,ally.handle]
        deadline=time.monotonic()+60;cast=False;seen=False;separated=False;stable=[];expired=False
        while time.monotonic()<deadline:
            now=g.clock()
            if (ROOT/'artifacts/STOP').exists():raise RuntimeError('User stop')
            units=[g.unit(h) for h in handles];wizard=g.unit(caster.handle)
            if not all(units) or not wizard:time.sleep(.2);continue
            if not cast:
                result=g.cast(wizard,'lightningshield',target=units[0]);cast=True
                report['cast_accepted']=bool(result)
                if not result:raise RuntimeError('Shield cast rejected: '+str(result.reason))
            buffs=g.buffs(units[0]);active=bool(SHIELD_BUFFS & set(buffs))
            gap=g.dist(*units)
            seen|=active
            if active and gap>=SAFE_GAP:
                separated=True;stable.append((now,units[1].hp))
            if seen and not active:expired=True
            bot.shield_moves=bot.shields.plan(units,[],now,g.buffs,mp.walkable,g.path_distance)
            for u in units:
                if u.handle in bot.shield_moves:bot.go_raw([u],bot.shield_moves[u.handle],now)
            # This normal movement must not bring the shield carrier back prematurely.
            bot.go(units,origin,now)
            report['samples'].append(dict(clock=now,buffs=buffs,gap=round(gap),ally_hp=units[1].hp,
                carrier=[units[0].x,units[0].y],expired=expired))
            if expired and separated and g.dist(units[0],origin)<120:
                report['passed']=len(stable)>=2 and stable[-1][0]-stable[0][0]>=4 and stable[-1][1]>=stable[0][1]-.5
                break
            time.sleep(.2)
        report.update(buff_observed=seen,separation_observed=separated,expiry_and_return=expired and g.dist(units[0],origin)<120)
        if not report['passed']:report['error']='No complete buff/separation/stable ally HP/expiry return evidence'
    except Exception as exc:
        report['error']=repr(exc);traceback.print_exc()
    finally:
        if dev:dev.close()
        session.stop();report['owned_processes_closed']=not session.owned
        (ROOT/'artifacts/p1-shield-fixture-0.1.19.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'events','samples'}},ensure_ascii=False),flush=True)
    return report['passed']


if __name__=='__main__':raise SystemExit(0 if main() else 1)
