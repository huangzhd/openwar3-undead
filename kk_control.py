"""Explicit user surrender: actual chat first, then exit this same game only."""
import re
import time


def send_gg(pid):
    """Post chat input to the game's own window, never to the foreground app."""
    import ctypes
    from ctypes import wintypes
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT]
    user32.GetWindow.restype=wintypes.HWND
    user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user32.PostMessageW.restype=wintypes.BOOL
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    windows=[]
    @callback_type
    def collect(hwnd,param):
        owner=wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd,4):
            windows.append(hwnd)
        return True
    user32.EnumWindows(collect,0)
    if len(windows)!=1:raise RuntimeError('无法唯一确认当前游戏窗口，未发送聊天')
    hwnd=windows[0]
    def post(message,key,lparam=0):
        if not user32.PostMessageW(hwnd,message,key,lparam):
            raise OSError(ctypes.get_last_error(),'游戏窗口拒绝输入')
    def key(vk,scan):
        post(0x100,vk,1|(scan<<16))
        post(0x101,vk,1|(scan<<16)|(3<<30))
    # Escape discards an existing edit/targeting mode before opening fresh chat.
    key(0x1b,1);time.sleep(.1)
    key(0x0d,0x1c);time.sleep(.15)
    post(0x102,ord('g'));post(0x102,ord('g'));time.sleep(.1)
    key(0x0d,0x1c)


def exit_game(g):
    # Game.end_game swallows errors and always returns True; verify externally.
    return g._control().action(22,0,timeout=1.0)


class Surrender:
    def __init__(self,request_id,local_name,send=send_gg,leave=exit_game):
        self.request_id=request_id;self.local_name=local_name
        self.send=send;self.leave=leave;self.stage='new';self.message='准备认输'
        self.at=0;self.gg_confirmed=False;self.exit_requested=False

    @property
    def active(self):return self.stage not in ('failed','finished')

    def state(self):
        return dict(request_id=self.request_id,stage=self.stage,message=self.message,
                    gg_confirmed=self.gg_confirmed,exit_requested=self.exit_requested)

    def fail(self,message):
        self.stage='failed';self.message=message

    def step(self,g,events,now):
        if self.stage=='new':
            if not self.local_name:
                self.fail('未识别本机玩家名称，无法核验 gg；已交还人工控制');return
            try:self.send(g.pid)
            except Exception as exc:
                self.fail('发送 gg 失败：'+str(exc));return
            self.stage='waiting_gg';self.at=now;self.message='等待确认 gg 已发送'
            return
        if self.stage=='waiting_gg':
            clean=lambda text:re.sub(r'\|c[0-9a-fA-F]{8}|\|r','',text or '').strip()
            observed=any(getattr(e,'kind',None)=='message' and getattr(e,'chat',None)
                         and clean(e.chat.get('sender'))==clean(self.local_name)
                         and e.chat.get('text','').strip().lower()=='gg' for e in events)
            if observed:
                self.gg_confirmed=True;self.exit_requested=True
                self.stage='exiting';self.at=now;self.message='gg 已确认，正在退出游戏'
                try:self.leave(g)
                except Exception:
                    # Exiting can destroy the reply channel; wait for process exit.
                    self.message='gg 已确认，等待游戏退出确认'
            elif now-self.at>=5:self.fail('未观察到本机 gg，未退出；当前为人工控制，可重试')
        elif self.stage=='exiting' and now-self.at>=8:
            self.fail('gg 已确认，但未确认游戏退出；当前为人工控制，可重试')
