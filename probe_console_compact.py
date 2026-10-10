"""Bounded compact UI observation through OpenWar3AI; never a normal match."""
import hashlib,json,time,traceback
from pathlib import Path
from bootstrap import ROOT
from session import Session
from undead.controller import Controller
from undead.debug_console import DebugConsole
from openwar3.screenshot import png_bytes

def run():
 prefix=ROOT/'artifacts/p1-console-compact-0.1.37'
 report=dict(version='0.1.37-dev',rules_version='0.1.37',normal_match=False,source_hashes={},screenshots=[],interactions=[])
 for p in [ROOT/'bot.py',ROOT/'run_match.py',ROOT/'probe_console_compact.py',*sorted((ROOT/'undead').glob('*.py'))]:
  report['source_hashes'][p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
 session=Session(400,2,4);console=None;start=time.monotonic()
 fh=Path(str(prefix)+'.events.jsonl').open('w',encoding='utf-8')
 def log(event,**kw):
  row=dict(event=event,**kw);fh.write(json.dumps(row,ensure_ascii=False)+'\n');fh.flush()
  if event=='debug_console_ui':report['interactions'].append(row)
 def capture(label,g):
  data=png_bytes(g.pid,scale=1)
  if data:
   path=ROOT/f'artifacts/p1-console-compact-0.1.37-{label}.png';path.write_bytes(data)
   report['screenshots'].append(dict(path=str(path),collapsed=console.collapsed,history_open=console.history_open,position=console.layout()[:2]))
 try:
  g=session.start();report['owned_processes']=list(session.owned)
  bot=Controller(g,log,2);console=DebugConsole(g,log);baseline=g.canvas.stats()
  s=g.snapshot(max_age=0);console.observe(s,bot)
  report['initial_collapsed']=console.collapsed and set(g.canvas.items)=={'bot.console.toggle'}
  console.toggle();console.start_move(source='fixture');console.finish_move(cancel=True)
  report['placement_api_registration_and_cleanup']=not console.moving and 'bot.console.placement' not in g.canvas.items
  compact_shot=False;history_shot=False
  while time.monotonic()-start<85 and g.clock()<290:
   s=g.snapshot(max_age=0);g.events();bot.tick();console.observe(s,bot)
   if s.clock>=30 and not compact_shot:capture('compact',g);compact_shot=True
   if s.clock>=220 and not history_shot:
    if console.collapsed:console.toggle()
    if not console.history_open:console.toggle_history()
    capture('history',g);history_shot=True
   time.sleep(.2)
  capture('final',g)
  report['canvas']=g.canvas.stats();report['decision_history']=console.history
  report['checks_passed']=bool(report['initial_collapsed'] and report['placement_api_registration_and_cleanup'] and
      report['canvas']['drawnFrames']>baseline['drawnFrames'] and report['canvas']['faults']==baseline['faults'] and compact_shot and history_shot)
  report['manual_move_committed']=any(e.get('action')=='move_commit' for e in report['interactions'])
 except Exception as exc:
  report['error']=repr(exc);traceback.print_exc()
 finally:
  if console:console.close()
  session.stop();fh.close()
  report['owned_processes_closed']=not any(Session.matches(r) for r in report.get('owned_processes',[]))
  report['wall_seconds']=round(time.monotonic()-start,2)
  Path(str(prefix)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','decision_history')},ensure_ascii=False,indent=2))
 return 0 if report.get('checks_passed') and report['owned_processes_closed'] else 1

if __name__=='__main__':raise SystemExit(run())
