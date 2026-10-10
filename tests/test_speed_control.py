import unittest
import argparse
from contextlib import nullcontext
from types import SimpleNamespace as N
from undead.speed_control import SpeedControl,speed_percent

class FakeCanvas:
    def __init__(self):self.items={}
    def batch(self):return nullcontext()
    def text(self,key,label,**kw):self.items[key]=dict(text=label,**kw)

class FakeUI:
    def __init__(self):
        self.canvas=FakeCanvas();self.callbacks={}
        self.block=N(state=lambda:{'back':(1024,768)})
    def button(self,key,label,on_click,**kw):self.callbacks[key]=on_click
    def remove(self,key):
        self.canvas.items.pop(key,None);self.callbacks.pop(key,None)

class SpeedTests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.sent=[];self.accept=True
        self.g=N(ui=FakeUI(),set_speed=self.send)
        self.control=SpeedControl(self.g,lambda *a,**k:None,lambda:self.now)
        self.control.observe(N(speed_pct=400,clock=1))
    def send(self,pct):self.sent.append(pct);return self.accept
    def click(self,key):self.g.ui.callbacks['bot.speed.'+key](self.g,None)

    def test_six_steps_are_reachable_and_stop_at_limits(self):
        self.control.observe(N(speed_pct=25,clock=1))
        for pct in (50,100,200,400,800):
            self.control.step(1)
            self.assertEqual(self.sent[-1],pct)
        self.control.step(1)
        self.assertEqual(self.sent,[50,100,200,400,800])
        for pct in (400,200,100,50,25):
            self.control.step(-1)
            self.assertEqual(self.sent[-1],pct)
        self.control.step(-1)
        self.assertEqual(self.sent,[50,100,200,400,800,400,200,100,50,25])
        for invalid in (24,801,'1.5','fast',True):
            with self.assertRaises(argparse.ArgumentTypeError):speed_percent(invalid)

    def test_manual_buttons_show_readback_between_slower_and_faster(self):
        self.click('slower')
        self.click('slower')
        self.assertEqual(self.sent,[200,100])
        self.assertEqual(self.g.ui.canvas.items['bot.speed.current']['text'],'4×')
        self.control.observe(N(speed_pct=100,clock=2))
        self.assertEqual(self.g.ui.canvas.items['bot.speed.current']['text'],'1×')
        self.click('faster')
        self.assertEqual(self.sent[-1],200)
        items=self.g.ui.canvas.items
        self.assertLess(items['bot.speed.slower']['screen'][0],items['bot.speed.current']['screen'][0])
        self.assertLess(items['bot.speed.current']['screen'][0],items['bot.speed.faster']['screen'][0])

    def test_failed_and_unconfirmed_requests_keep_actual_speed(self):
        self.accept=False
        self.control.request(37)
        self.assertIsNone(self.control.pending)
        self.assertEqual(self.control.actual,400)
        self.assertIn('失败',self.control.message)
        self.accept=True
        self.control.request(37)
        self.now=4
        self.control.observe(N(speed_pct=400,clock=2))
        self.assertIsNone(self.control.pending)
        self.assertIn('未确认',self.control.message)
        self.assertEqual(self.control.actual,400)
        self.control.observe(N(speed_pct=37,clock=3))
        self.assertEqual(self.control.actual,37)

if __name__=='__main__':unittest.main()
