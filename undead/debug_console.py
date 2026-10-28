"""Strategic HUD, manual match controls and accepted semantic-command APM."""
from collections import deque
import time
from .speed_control import SpeedControl


def initialize_ui(g,log,clock=time.monotonic):
    """Allow cold font/render setup up to 45 seconds, only for UI enable calls."""
    started=clock()
    original=g.lane.commands
    enable_ops={g._w3fast.OP[n] for n in ('input_enable','canvas_enable') if n in g._w3fast.OP}
    def commands(calls,timeout=.25):
        if calls and all(c.op in enable_ops for c in calls):
            timeout=45-(clock()-started)
            if timeout<=0:raise TimeoutError('UI initialization exceeded 45 seconds')
        return original(calls,timeout=timeout)
    log('ui_initializing',timeout_seconds=45)
    g.lane.commands=commands
    try:
        ui=g.ui
    finally:
        g.lane.commands=original
    log('ui_ready',wall_seconds=round(clock()-started,3))
    return ui


def region(point):
    x,y=point
    return ('西' if x<-1800 else '东' if x>1800 else '')+('北' if y>1800 else '南' if y<-1800 else '')+'侧' if abs(x)>1800 or abs(y)>1800 else '中央'


def camp_name(camp,point):
    names={'marketplace':'市场营地','shop':'地精商店营地','gnoll':'豺狼人营地',
           'ogre':'食人魔营地','expansion':'分矿营地','murloc':'鱼人营地',
           'mercenary':'雇佣兵营地','turtle':'海龟营地'}
    return region(point)+names.get((camp or {}).get('kind'),'野怪营地')


class ActionMeter:
    """One accepted per-unit semantic command is one action, including batch members.

    This is bot command APM, not human input/replay APM or successful ability effects.
    Queries, rejected orders, speed/UI/camera commands never contribute.
    """
    def __init__(self,g,trace=None):
        self.g=g;self.samples=deque();self.total=0
        self.trace=trace;self.trace_enabled=trace is not None;self.trace_error=None;self.trace_batch=0
        self.started=self.last=float(g.clock())
        self.original=g.lane.commands
        self.action_ops={g._w3fast.OP[n] for n in ('point','target','immediate','build','learn',
                          'use_item','revive','rally','buy','item_drop')}
        self.op_names={value:name for name,value in g._w3fast.OP.items()}
        self.wrapper=self.commands
        g.lane.commands=self.wrapper

    def advance(self,now):
        now=float(now)
        if now<self.last:
            self.samples.clear();self.total=0;self.started=now
        self.last=now
        while self.samples and self.samples[0][0]<=now-60:self.samples.popleft()

    def record(self,event,**data):
        if self.trace is None:return
        try:self.trace(event,**data)
        except Exception as exc:
            # Diagnostic disk failures must never suppress or repeat a game order.
            self.trace_error=repr(exc);self.trace=None

    def commands(self,calls,*args,**kwargs):
        selected=[i for i,c in enumerate(calls) if c.op in self.action_ops] if self.trace is not None else []
        if selected:
            self.trace_batch+=1;batch_id=self.trace_batch
            self.record('attachment_commands_submitted',batch_id=batch_id,
                        clock=getattr(getattr(self.g,'_snap',None),'clock',self.last),
                        clock_basis='cached_snapshot',wall_time=time.time(),
                        commands=[dict(index=i,op=self.op_names[calls[i].op],args=list(getattr(calls[i],'args',())))
                                  for i in selected])
        try:receipts=self.original(calls,*args,**kwargs)
        except Exception as exc:
            if selected:self.record('attachment_commands_failed',batch_id=batch_id,wall_time=time.time(),error=repr(exc))
            raise
        self.advance(self.g.clock())
        if selected:
            self.record('attachment_commands_completed',batch_id=batch_id,clock=self.last,wall_time=time.time(),
                        receipts=[dict(index=i,ok=bool(r.ok),reason=getattr(r,'reason',None),
                                       faulted=getattr(r,'faulted',None),ret=getattr(r,'ret',None),
                                       order_after=getattr(r,'order_after',None))
                                  for i,r in enumerate(receipts) if i in selected])
        count=sum(c.op in self.action_ops and r.ok for c,r in zip(calls,receipts))
        if count:self.samples.append((self.last,count));self.total+=count
        return receipts

    def value(self,now):
        self.advance(now)
        span=min(60,max(1,self.last-self.started))
        return round(sum(n for _,n in self.samples)*60/span)

    def summary(self,now):
        # A snapshot captured before orders may lag the clock read in commands.
        # That is not a new game. Keep counters and the elapsed denominator.
        self.advance(max(float(now),self.last))
        elapsed=max(0,self.last-self.started)
        result=dict(accepted_actions=self.total,apm_game_seconds=round(elapsed,3),
                    average_apm=round(self.total*60/max(1,elapsed),1),
                    apm=self.value(self.last),apm_basis='accepted_unit_commands_game_time_v2')
        if self.trace_enabled:result['command_trace_error']=self.trace_error
        return result

    def close(self):
        if self.g.lane.commands is self.wrapper:self.g.lane.commands=self.original


class DebugConsole:
    """Compact in-game HUD with click-to-move placement through OpenWar3AI only."""
    def __init__(self,g,log,clock=time.monotonic):
        self.g,self.log,self.clock=g,log,clock
        initialize_ui(g,log,clock)
        self.speed=SpeedControl(g,log,clock,embedded=True)
        self.meter=ActionMeter(g)
        self.speed.position=lambda:(self.layout()[0]+158,self.layout()[1]+34)
        self.collapsed=True;self.history_open=False;self.speed.visible=False
        self.match_action=None
        self.position=None;self.moving=False;self.move_origin=None;self.move_offset=(30,14)
        self.move_started=0;self.escape_key=None
        self.last_draw=-100;self.state=None;self.last_intent=None;self.last_log=-100
        self.history=[];self.view_end=None;self.unread=0;self.keys=set();self.latest=None

    def request_match_action(self,action):
        if action not in ('surrender','restart'):raise ValueError('Unknown match action')
        if self.match_action is not None:return
        self.match_action=action
        self.log('match_control_requested',clock=self.g.clock(),action=action,source='manual_panel')
        self.state=None;self.render()

    def panel_height(self):
        return 28 if self.collapsed else 148+(24 if self.speed.pending is not None or self.speed.message else 0)+(152 if self.history_open else 0)

    def layout(self):
        width,height=self.g.ui.block.state().get('back') or (1024,768)
        width,height=width or 1024,height or 768
        x,y=self.position or (max(8,width-308),max(8,height*.75-self.panel_height()))
        x=max(8,min(x,max(8,width-308)))
        y=max(8,min(y,max(8,height-self.panel_height()-8)))
        return x,y,3,width,height

    def pointer(self):
        point=self.g.ui.cursor().get('screen')
        _,_,_,w,h=self.layout()
        if point and 0<=point[0]<w and 0<=point[1]<h:return point
        return None

    def start_move(self,source='panel'):
        if self.moving:return
        self.move_origin=self.position
        x,y,*_=self.layout();point=self.pointer()
        self.move_offset=(point[0]-x,point[1]-y) if point else (30,14)
        self.moving=True;self.move_started=self.clock()
        self.escape_key=self.g.ui.hotkey('esc',lambda g,e:self.finish_move(cancel=True))
        self.state=None;self.render()
        self.log('debug_console_ui',clock=self.g.clock(),action='move_start',source=source)

    def update_movement(self):
        if not self.moving:return
        if self.clock()-self.move_started>=15:
            self.finish_move(cancel=True);return
        point=self.pointer()
        if point:
            self.position=(point[0]-self.move_offset[0],point[1]-self.move_offset[1])
            self.position=self.layout()[:2]

    def finish_move(self,cancel=False):
        if not self.moving:return
        if not cancel:
            point=self.pointer()
            if point:
                self.position=(point[0]-self.move_offset[0],point[1]-self.move_offset[1])
                self.position=self.layout()[:2]
        else:self.position=self.move_origin
        self.moving=False
        if self.escape_key is not None:self.g.ui.remove_hotkey(self.escape_key)
        self.escape_key=None;self.state=None;self.render()
        self.log('debug_console_ui',clock=self.g.clock(),action='move_cancel' if cancel else 'move_commit',position=self.position)

    def toggle(self,source='api'):
        self.collapsed=not self.collapsed
        self.speed.visible=not self.collapsed
        self.state=None;self.render()
        self.log('debug_console_ui',clock=self.g.clock(),action='toggle',source=source,collapsed=self.collapsed)

    def toggle_history(self):
        self.history_open=not self.history_open;self.state=None;self.render()

    def scroll(self,direction,source='api'):
        rows=self.layout()[2];count=len(self.history)
        end=count if self.view_end is None else self.view_end
        end=max(min(rows,count),min(count,end+direction*rows))
        self.view_end=None if end==count else end
        if self.view_end is None:self.unread=0
        self.state=None;self.render()
        self.log('debug_console_ui',clock=self.g.clock(),action='scroll',source=source,view_end=self.view_end)

    def follow_latest(self,source='api'):
        self.view_end=None;self.unread=0;self.state=None;self.render()
        self.log('debug_console_ui',clock=self.g.clock(),action='latest',source=source)

    @staticmethod
    def stamp(clock):
        seconds=max(0,int(clock))
        return f'{seconds//60:02d}:{seconds%60:02d}'

    def observe(self,snapshot,bot,paused=False):
        self.update_movement()
        self.speed.observe(snapshot)
        game_now=max(snapshot.clock,self.meter.last)
        intent='游戏暂停 · 等待继续' if paused else bot.intent
        if intent!=self.last_intent:
            at=game_now if paused else getattr(bot,'intent_clock',snapshot.clock)
            entry=dict(clock=at,text=intent)
            self.history.append(entry)
            if self.view_end is not None:self.unread+=1
            self.log('strategic_intent',**entry)
            self.last_intent=intent
        apm=self.meter.value(game_now)
        self.latest=(game_now,apm,intent)
        if game_now-self.last_log>=5:
            self.last_log=game_now
            self.log('debug_console',clock=game_now,apm=apm,accepted_actions=self.meter.total,
                     intent=intent,apm_basis='accepted_unit_commands_per_60_game_seconds')
        now=self.clock()
        if now-self.last_draw>=(.05 if self.moving else .5):
            self.last_draw=now;self.render()

    def render(self):
        if self.latest is None:return
        game_now,apm,intent=self.latest;x,y,rows,width,height=self.layout()
        state=(int(game_now),apm,intent,width,height,x,y,self.collapsed,self.history_open,self.moving,
               len(self.history),self.view_end,self.unread,self.speed.pending,self.speed.message,self.match_action)
        if state==self.state:return
        self.state=state
        c=self.g.ui.canvas;active=set()
        def text(key,label,dx,dy,w,h,size=14,color=(244,246,250),**kw):
            key='bot.console.'+key;active.add(key)
            c.text(key,label,screen=(x+dx,y+dy),width=w,height=h,size=size,color=color,layer=59,over_ui=True,**kw)
        def button(key,label,dx,dy,w,h,callback,selected=False):
            key='bot.console.'+key;active.add(key)
            style=dict(screen=(x+dx,y+dy),width=w,size=13,
                       color=(255,244,200) if selected else (244,246,250) if callback else (125,140,157),
                       bg=(19,25,36,240),border=(220,186,102) if selected else (80,98,122),
                       radius=3,layer=61,over_ui=True)
            if callback:self.g.ui.button(key,label,on_click=lambda g,event:callback(),**style)
            else:self.g.ui.remove(key)
            c.text(key,label,height=h,clickable=bool(callback),hover=(255,255,255,40),**style)
        with c.batch():
            if self.collapsed:
                button('toggle','调试台 +',218,0,82,28,lambda:self.toggle('panel'))
            else:
                text('frame','',0,0,300,self.panel_height(),bg=(19,25,36,230),border=(80,98,122),radius=4)
                button('move','移动中 · 点击固定' if self.moving else '调试台 0.1.55 · 点此移动',6,4,194,26,self.start_move)
                button('history','历史' if not self.history_open else '折叠',204,4,46,26,self.toggle_history,selected=self.history_open)
                button('toggle','－',254,4,40,26,lambda:self.toggle('panel'))
                text('metrics',f'{self.stamp(game_now)}  APM {apm}',8,35,144,26,14)
                text('intent',f'[{self.stamp(self.history[-1]["clock"])}] '+intent,8,65,284,40,14,(255,244,200))
                controls_top=108+(24 if self.speed.pending is not None or self.speed.message else 0)
                button('surrender','正在认输…' if self.match_action=='surrender' else '认输',8,controls_top,138,28,
                       (lambda:self.request_match_action('surrender')) if self.match_action is None else None)
                button('restart','正在重开…' if self.match_action=='restart' else '重开',154,controls_top,138,28,
                       (lambda:self.request_match_action('restart')) if self.match_action is None else None)
                if self.history_open:
                    top=148+(24 if self.speed.pending is not None or self.speed.message else 0)
                    label='最新' if self.view_end is None else f'{self.unread}条新消息'
                    end=len(self.history) if self.view_end is None else self.view_end
                    start=max(0,end-rows)
                    button('older','较早',8,top,48,24,(lambda:self.scroll(-1,'panel')) if start>0 else None)
                    button('latest','回到最新',62,top,82,24,self.follow_latest,selected=self.view_end is None)
                    button('newer','较新',150,top,48,24,(lambda:self.scroll(1,'panel')) if end<len(self.history) else None)
                    text('label',label,204,top,88,24,12,(180,194,212))
                    for i,entry in enumerate(self.history[start:end]):
                        text(f'entry.{i}',f'[{self.stamp(entry["clock"])}] '+entry['text'],8,top+28+i*40,284,40,14)
            if self.moving:
                # Capture only during placement so the fixing click never orders game units.
                key='bot.console.placement';active.add(key)
                style=dict(screen=(0,0),width=width,height=height,size=12,bg=(0,0,0,0),layer=100,over_ui=True)
                self.g.ui.button(key,'',on_click=lambda g,e:self.finish_move(),**{k:v for k,v in style.items() if k!='height'})
                c.text(key,'',clickable=True,**style)
            for key in self.keys-active:self.g.ui.remove(key)
            self.keys=active
            self.speed.visible=not self.collapsed
            self.speed.render()

    def close(self):
        if self.moving:self.finish_move(cancel=True)
        for key in self.keys|self.speed.keys:self.g.ui.remove(key)
        self.keys=set();self.speed.keys=set()
        self.meter.close()
