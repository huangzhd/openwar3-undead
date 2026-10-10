"""Manual in-game speed controls; display engine readback, never optimistic state."""
import argparse
import time

MIN_SPEED=25
MAX_SPEED=800
SPEEDS=(25,50,100,200,400,800)
LABELS={25:"1/4×",50:"1/2×",100:"1×",200:"2×",400:"4×",800:"8×"}

def speed_percent(value):
    try:
        percent=int(value)
        if str(percent)!=str(value).strip() or not MIN_SPEED<=percent<=MAX_SPEED:
            raise ValueError
    except (ValueError,TypeError):
        raise argparse.ArgumentTypeError('speed must be an integer percentage from 25 to 800')
    return percent

class SpeedControl:
    def __init__(self,g,log,clock=time.monotonic,embedded=False):
        self.g,self.log,self.clock=g,log,clock
        self.embedded=embedded
        self.visible=True;self.position=None
        self.ui=g.ui
        self.actual=None
        self.pending=None
        self.requested_at=0
        self.message=''
        self.drawn=None
        self.keys=set()

    def request(self,percent):
        percent=speed_percent(percent)
        self.pending=percent
        self.requested_at=self.clock()
        self.message=''
        try:
            accepted=bool(self.g.set_speed(percent))
        except Exception as exc:
            accepted=False
            self.log('speed_request_error',error=repr(exc))
        self.log('speed_requested',percent=percent,accepted=accepted,source='manual_panel')
        if not accepted:
            self.pending=None
            self.message='设置失败，请重试'
        self.render()

    def step(self,direction):
        base=self.pending if self.pending is not None else self.actual
        if base is None:return
        candidates=[p for p in SPEEDS if p>base] if direction>0 else [p for p in SPEEDS if p<base]
        if candidates:self.request(min(candidates) if direction>0 else max(candidates))

    def observe(self,snapshot):
        self.actual=snapshot.speed_pct
        if self.pending is not None:
            if self.actual==self.pending:
                self.log('speed_confirmed',percent=self.actual,clock=snapshot.clock)
                self.pending=None
                self.message=''
            elif self.clock()-self.requested_at>3:
                self.log('speed_unconfirmed',requested=self.pending,actual=self.actual)
                self.pending=None
                self.message='未确认切换，请重试'
        self.render()

    def render(self):
        if not self.visible:
            for key in self.keys:self.ui.remove(key)
            self.keys=set();self.drawn=None
            return
        width,height=self.ui.block.state().get('back') or (1024,768)
        width,height=width or 1024,height or 768
        position=self.position() if self.position else None
        state=(self.actual,self.pending,self.message,width,height,position)
        if state==self.drawn:return
        self.drawn=state
        c=self.ui.canvas
        x=width*.95-306;y=max(80,height*.13)
        if self.embedded:x=max(8,width*.95-330)+12;y+=146
        if position:x,y=position
        active=set()
        def text(key,label,dx,dy,w,callback=None,selected=False):
            key='bot.speed.'+key
            active.add(key)
            style=dict(screen=(x+dx,y+dy),width=w,size=14 if self.embedded else 18,
                       color=(255,244,200) if selected else (244,246,250),
                       bg=(19,25,36,245),border=(220,186,102) if selected else (106,127,153),
                       radius=5,layer=60,over_ui=True)
            if callback:
                self.ui.button(key,label,on_click=lambda g,event:callback(),**style)
            c.text(key,label,height=28 if self.embedded else 44,clickable=bool(callback),hover=(255,255,255,40),**style)
        value=LABELS.get(self.actual,f'{self.actual/100:g}×') if self.actual is not None else '读取中'
        with c.batch():
            if self.embedded:
                text('slower','−',0,0,28,lambda:self.step(-1))
                text('current',value,32,0,68,selected=True)
                text('faster','+',104,0,28,lambda:self.step(1))
                status=f'正在设置 {LABELS.get(self.pending,str(self.pending)+"%")}' if self.pending is not None else self.message
                if status:
                    key='bot.speed.status';active.add(key)
                    c.text(key,status,screen=(x-150,y+74),width=284,height=22,size=12,
                           color=(255,220,150),layer=60,over_ui=True)
            else:
                text('slower','减速',0,0,80,lambda:self.step(-1))
                text('current',value,86,0,134,selected=True)
                text('faster','加速',226,0,80,lambda:self.step(1))
                if self.pending is not None:
                    text('status',f'正在设置 {LABELS.get(self.pending,str(self.pending)+"%")}',0,48,306)
                elif self.message:
                    text('status',self.message,0,48,306)
            for key in self.keys-active:self.ui.remove(key)
        self.keys=active
