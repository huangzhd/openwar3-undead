"""Read-only Windows IPC diagnostics; never load code into a game process."""
import ctypes
from ctypes import wintypes

FILE_MAP_READ = 0x0004
FILE_MAP_ALL = 0x000F001F  # Match w3world.World's required access exactly.


def mapping_access(name, access):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel.OpenFileMappingW(access, False, name)
    error = 0 if handle else ctypes.get_last_error()
    if handle:
        kernel.CloseHandle(handle)
    return dict(name=name, access=access, winerror=error,
                message=ctypes.FormatError(error).strip())


def diagnose_unavailable(pid, sdk_detail):
    """Distinguish absent IPC, denied access and incomplete/incompatible IPC.

    Opening and closing an existing mapping does not map its data or write to it.
    An absent object does not prove that the DLL is absent or anti-cheat blocked it.
    """
    name = f'Local\\War3World_{pid}'
    checks = [mapping_access(name, FILE_MAP_READ)]
    error = checks[0]['winerror']
    if error == 2:
        state = 'mapping_absent'
        reason = '当前会话中不存在世界状态共享内存；运行时可能未加载或尚未建立接口。'
        next_step = '需要运行时的加载及初始化流程；反复 attach 或换 PID 不能创建接口。'
    elif error == 5:
        state = 'access_denied'
        reason = 'Windows 拒绝访问世界状态接口，不能据此认定运行时未加载。'
        next_step = '核对游戏与工具的用户、Windows 会话和权限级别；本工具不自动提权。'
    elif error:
        state = 'mapping_open_error'
        reason = '打开世界状态接口失败，详见 Windows 错误码。'
        next_step = '先排查所列 Windows 错误，不能按缺少 DLL 处理。'
    else:
        checks.append(mapping_access(name, FILE_MAP_ALL))
        error = checks[-1]['winerror']
        if error == 5:
            state = 'access_denied'
            reason = '世界状态接口可读，但 SDK 所需访问权限被 Windows 拒绝。'
            next_step = '核对游戏与工具的权限级别；不要重复加载运行时。'
        elif error:
            state = 'mapping_changed_or_error'
            reason = '世界状态接口在检测期间变化，或无法取得 SDK 所需访问权限。'
            next_step = '核对原游戏进程是否仍在运行，再检查 Windows 错误码。'
        else:
            checks.extend(mapping_access(f'Local\\War3{part}_{pid}', FILE_MAP_READ)
                          for part in ('Trees', 'Events'))
            state = 'runtime_incomplete_or_incompatible'
            reason = '世界接口存在，但 SDK 初始化失败：检查配套接口、协议版本和映射大小。'
            next_step = '保留 SDK 原始错误并核对运行时版本；不要把此情况当成未加载后重复加载。'
    return dict(bridge_state=state, reason=reason, next_step=next_step,
                diagnostic=dict(checks=checks, sdk_detail=sdk_detail,
                                platform_block_proven=False))
