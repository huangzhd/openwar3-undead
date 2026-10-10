"""Requested local Warcraft III preferences. No mouse/keyboard automation."""
import json
import winreg
from bootstrap import ROOT

KEY=r'Software\Blizzard Entertainment\Warcraft III\Gameplay'
DEFAULTS={'allyFilter':2,'formations':0,'formationtoggle':0,'healthbars':1}
BACKUP=ROOT/'artifacts/gameplay-preferences-before.json'

def read_defaults():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as key:
        result={}
        for name in DEFAULTS:
            try:result[name]=winreg.QueryValueEx(key,name)[0]
            except FileNotFoundError:result[name]=None
        return result

def apply_defaults():
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_READ|winreg.KEY_SET_VALUE|winreg.KEY_WOW64_32KEY) as key:
        if not BACKUP.exists():
            before={}
            for name in DEFAULTS:
                try:
                    value,kind=winreg.QueryValueEx(key,name)
                    before[name]={'exists':True,'value':value,'type':kind}
                except FileNotFoundError:before[name]={'exists':False}
            BACKUP.parent.mkdir(parents=True,exist_ok=True)
            BACKUP.write_text(json.dumps({'key':KEY,'values':before},ensure_ascii=False,indent=2),encoding='utf-8')
        for name,value in DEFAULTS.items():
            winreg.SetValueEx(key,name,0,winreg.REG_DWORD,value)
        winreg.FlushKey(key)
    actual=read_defaults()
    if actual!=DEFAULTS:raise RuntimeError('Warcraft preference readback mismatch: '+repr(actual))
    return actual

def confirm_ally_colors(pid):
    # A separate setup-only client reads a local UI preference, never opponent data.
    from openwar3 import Game
    with Game(pid=pid,fair=False) as setup:
        actual=setup.jass.GetAllyColorFilterState()
        if actual!=DEFAULTS['allyFilter']:
            setup.jass.SetAllyColorFilterState(DEFAULTS['allyFilter'])
            actual=setup.jass.GetAllyColorFilterState()
        if actual!=DEFAULTS['allyFilter']:
            raise RuntimeError('Ally color preference did not take effect')
        return actual
