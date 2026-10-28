"""Native-resolution settings for local human practice, applied before launch."""
import ctypes
from ctypes import wintypes as W
import json
import winreg
from bootstrap import ROOT

KEY = r'Software\Blizzard Entertainment\Warcraft III\Video'
BACKUP = ROOT/'artifacts/human-practice-video-before.json'
NAMES = ('reswidth','resheight','colordepth','texcolordepth','refreshrate')


class DisplayMode(ctypes.Structure):
    _fields_ = [('device',W.WCHAR*32),('spec',W.WORD),('driver',W.WORD),('size',W.WORD),
                ('extra',W.WORD),('fields',W.DWORD),('x',W.LONG),('y',W.LONG),
                ('orientation',W.DWORD),('fixed',W.DWORD),('color',W.SHORT),('duplex',W.SHORT),
                ('yres',W.SHORT),('tt',W.SHORT),('collate',W.SHORT),('form',W.WCHAR*32),
                ('pixels',W.WORD),('bits',W.DWORD),('width',W.DWORD),('height',W.DWORD),
                ('flags',W.DWORD),('frequency',W.DWORD),('icm_method',W.DWORD),
                ('icm_intent',W.DWORD),('media',W.DWORD),('dither',W.DWORD),
                ('reserved1',W.DWORD),('reserved2',W.DWORD),('pan_width',W.DWORD),('pan_height',W.DWORD)]


def current_display():
    mode=DisplayMode();mode.size=ctypes.sizeof(mode)
    enum=ctypes.WinDLL('user32',use_last_error=True).EnumDisplaySettingsW
    enum.argtypes=[W.LPCWSTR,W.DWORD,ctypes.POINTER(DisplayMode)];enum.restype=W.BOOL
    if not enum(None,0xffffffff,ctypes.byref(mode)) or mode.width<800 or mode.height<600:
        raise RuntimeError('无法读取显示器当前分辨率，未启动练习')
    return dict(width=int(mode.width),height=int(mode.height),refresh_hz=int(mode.frequency),color_depth=32)


def read_video():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as key:
        values={}
        for name in NAMES:
            try:values[name]=winreg.QueryValueEx(key,name)[0]
            except FileNotFoundError:values[name]=None
        return values


def configure_video():
    from machine_start import active_processes
    active=active_processes()
    if active:raise RuntimeError('请先退出当前游戏，再更新练习分辨率')
    display=current_display()
    wanted=dict(reswidth=display['width'],resheight=display['height'],colordepth=32,texcolordepth=32)
    if display['refresh_hz']>1:wanted['refreshrate']=display['refresh_hz']
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,KEY,0,
                           winreg.KEY_READ|winreg.KEY_SET_VALUE|winreg.KEY_WOW64_32KEY) as key:
        before={}
        for name in NAMES:
            try:
                value,kind=winreg.QueryValueEx(key,name)
                before[name]=dict(exists=True,value=value,type=kind)
            except FileNotFoundError:before[name]=dict(exists=False)
        if not BACKUP.exists():
            BACKUP.parent.mkdir(parents=True,exist_ok=True)
            BACKUP.write_text(json.dumps(dict(key=KEY,values=before),indent=2),encoding='utf-8')
        for name,value in wanted.items():winreg.SetValueEx(key,name,0,winreg.REG_DWORD,value)
        winreg.FlushKey(key)
    actual=read_video()
    if any(actual[name]!=value for name,value in wanted.items()):
        raise RuntimeError('游戏分辨率设置未通过回读校验')
    return dict(**display,registry=actual,basis='current_windows_display')
