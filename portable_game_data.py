"""Read known WC3 tables using the bundled StormLib, without an MPQ listfile."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path

EXTRACTOR_VERSION = 'stormlib-known-paths-v1'
STORM_DLL_SHA = '93321f6f030be5d7d79eb4cbf433d6ef7e83ce20d47d8963717f207d54afbe16'
ORDER = ('War3Patch.mpq', 'War3xLocal.mpq', 'War3x.mpq', 'war3.mpq')
TABLES = ('UnitBalance.slk', 'UnitWeapons.slk', 'UnitData.slk', 'UnitUI.slk',
          'UnitAbilities.slk', 'AbilityData.slk', 'UpgradeData.slk', 'ItemData.slk',
          'DestructableData.slk', 'ItemFunc.txt', 'ItemStrings.txt', 'ItemAbilityFunc.txt',
          'ItemAbilityStrings.txt', 'HumanAbilityStrings.txt', 'MiscData.txt',
          'MiscGame.txt', 'MiscUI.txt', 'UI_MiscData.txt')
WANT = {name: 'Units\\' + name for name in TABLES}
WANT.update({'MiscUI.txt': 'UI\\MiscUI.txt', 'UI_MiscData.txt': 'UI\\MiscData.txt'})
OPEN_FLAGS = 0x100 | 0x10000 | 0x20000  # READ_ONLY | NO_LISTFILE | NO_ATTRIBUTES
MAX_TABLE_BYTES = 32 * 1024 * 1024


def load_stormlib(root):
    path = Path(root) / 'vendor/StormLib-9.40/x64/StormLib.dll'
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != STORM_DLL_SHA:
        raise RuntimeError('StormLib 组件缺失或损坏，请重新解压完整训练包。')
    lib = ctypes.WinDLL(str(path.resolve()), use_last_error=True)
    ptr, uint, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool
    specs = {
        'SFileOpenArchive': ([ctypes.c_wchar_p, uint, uint, ctypes.POINTER(ptr)], boolean),
        'SFileCloseArchive': ([ptr], boolean),
        'SFileOpenFileEx': ([ptr, ctypes.c_char_p, uint, ctypes.POINTER(ptr)], boolean),
        'SFileGetFileSize': ([ptr, ctypes.POINTER(uint)], uint),
        'SFileReadFile': ([ptr, ptr, uint, ctypes.POINTER(uint), ptr], boolean),
        'SFileCloseFile': ([ptr], boolean),
    }
    for name, (arguments, result) in specs.items():
        fn = getattr(lib, name); fn.argtypes = arguments; fn.restype = result
    return lib


class Archive:
    def __init__(self, path, lib):
        self.path, self.lib, self.handle = Path(path), lib, ctypes.c_void_p()

    def __enter__(self):
        if not self.lib.SFileOpenArchive(str(self.path.resolve()), 0, OPEN_FLAGS,
                                        ctypes.byref(self.handle)):
            raise OSError(ctypes.get_last_error(), f'MPQ 无法读取：{self.path}；请检查文件完整性或访问权限。')
        return self

    def __exit__(self, *args):
        self.lib.SFileCloseArchive(self.handle)

    def read(self, name):
        handle = ctypes.c_void_p()
        if not self.lib.SFileOpenFileEx(self.handle, name.encode('ascii'), 0, ctypes.byref(handle)):
            error = ctypes.get_last_error()
            if error == 2:  # ERROR_FILE_NOT_FOUND: only genuine absence may use a lower-priority MPQ.
                return None
            raise OSError(error, f'MPQ 内部文件无法打开：{self.path.name} / {name}')
        try:
            high = ctypes.c_uint32()
            size = self.lib.SFileGetFileSize(handle, ctypes.byref(high))
            if size == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), f'MPQ 文件大小读取失败：{self.path.name} / {name}')
            if high.value or not 0 < size <= MAX_TABLE_BYTES:
                raise ValueError(f'MPQ 数据大小异常：{self.path.name} / {name} ({high.value}:{size})')
            data, read = ctypes.create_string_buffer(size), ctypes.c_uint32()
            if not self.lib.SFileReadFile(handle, data, size, ctypes.byref(read), None):
                raise OSError(ctypes.get_last_error(), f'MPQ 数据读取失败：{self.path.name} / {name}')
            if read.value != size:
                raise ValueError(f'MPQ 数据读取不完整：{self.path.name} / {name}')
            return data.raw
        finally:
            self.lib.SFileCloseFile(handle)


def extract(game, output, root):
    game, output = Path(game), Path(output)
    lib, found, sources = load_stormlib(root), {}, {}
    for archive_name in ORDER:
        path = game / archive_name
        if not path.is_file():
            continue
        # Never silently replace an unreadable patch with an older base table.
        with Archive(path, lib) as archive:
            for name, inner in WANT.items():
                if name in found:
                    continue
                data = archive.read(inner)
                if data is not None:
                    found[name] = data
                    sources[name] = dict(archive=archive_name, path=inner,
                                         sha256=hashlib.sha256(data).hexdigest())
        if len(found) == len(WANT):
            break
    missing = [name for name in WANT if name not in found]
    if missing:
        raise RuntimeError('已读取的 MPQ 中缺少所需数据：' + ', '.join(missing) +
                           '。请检查是否为完整的 1.27a 安装；旧提取结果不会作为本次成功数据。')
    output.mkdir(parents=True, exist_ok=True)
    for name, data in found.items():
        temp = output / (name + '.tmp')
        temp.write_bytes(data); temp.replace(output / name)
        print(f'  OK {name} <- {sources[name]["archive"]}')
    report = dict(extractor=EXTRACTOR_VERSION, files=sources)
    (output / 'dayuan-data-sources.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    extract(args.game_dir, args.out, Path(__file__).resolve().parent)
