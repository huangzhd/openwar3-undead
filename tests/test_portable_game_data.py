"""Real encrypted/listfile-free MPQs exercise the portable extraction boundary."""
import ctypes
import hashlib
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

import mpyq
import portable_game_data as data

ROOT = Path(__file__).resolve().parents[1]


class CreateInfo(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('version', ctypes.c_uint32), ('user', ctypes.c_void_p)] + [
        (name, ctypes.c_uint32) for name in ('user_size', 'stream_flags', 'list_flags', 'attribute_flags',
        'signature_flags', 'attributes', 'sector_size', 'chunk_size', 'max_files')]


@unittest.skipUnless(sys.platform == 'win32', 'Bundled Windows StormLib')
class PortableArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / '魔兽 游戏'; self.game.mkdir()
        self.output = self.game / 'output'
        self.lib = data.load_stormlib(ROOT)
        ptr, uint = ctypes.c_void_p, ctypes.c_uint32
        specs = {
            'SFileCreateArchive2': [ctypes.c_wchar_p, ctypes.POINTER(CreateInfo), ctypes.POINTER(ptr)],
            'SFileCreateFile': [ptr, ctypes.c_char_p, ctypes.c_uint64, uint, uint, uint, ctypes.POINTER(ptr)],
            'SFileWriteFile': [ptr, ptr, uint, uint],
            'SFileFinishFile': [ptr],
        }
        for name, arguments in specs.items():
            fn = getattr(self.lib, name); fn.argtypes = arguments; fn.restype = ctypes.c_bool

    def archive(self, name, files, flags=0x30200, list_flags=0):
        path = self.game / name
        handle = ctypes.c_void_p()
        info = CreateInfo(size=ctypes.sizeof(CreateInfo), list_flags=list_flags, sector_size=4096, max_files=64)
        self.assertTrue(self.lib.SFileCreateArchive2(str(path), ctypes.byref(info), ctypes.byref(handle)))
        try:
            for inner, payload in files.items():
                item = ctypes.c_void_p()
                self.assertTrue(self.lib.SFileCreateFile(handle, inner.encode('ascii'), 0,
                                len(payload), 0, flags, ctypes.byref(item)))
                try:
                    self.assertTrue(self.lib.SFileWriteFile(item, ctypes.c_char_p(payload), len(payload), 2))
                finally:
                    self.assertTrue(self.lib.SFileFinishFile(item))
        finally:
            self.assertTrue(self.lib.SFileCloseArchive(handle))
        return path

    def extract(self):
        with redirect_stdout(io.StringIO()):
            return data.extract(self.game, self.output, ROOT)

    def test_listfile_absent_and_encrypted_tables_extract_without_modifying_archives(self):
        payload = b'ID;PWXL;N;E\r\n' * 1000
        path = self.archive('war3.mpq', {inner: payload for inner in data.WANT.values()})
        legacy = mpyq.MPQArchive(str(path), listfile=False)
        try:
            self.assertIsNone(legacy.read_file('(listfile)'))
            with self.assertRaisesRegex(NotImplementedError, 'Encryption'):
                legacy.read_file('Units\\UnitBalance.slk')
        finally:
            legacy.file.close()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        report = self.extract()
        self.assertEqual(len(report['files']), 18)
        for name in data.TABLES:self.assertEqual((self.output / name).read_bytes(), payload)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_encrypted_listfile_does_not_prevent_opening(self):
        files = {inner: b'fixture' for inner in data.WANT.values()}
        path = self.archive('war3.mpq', files, list_flags=0x30200)
        legacy = mpyq.MPQArchive(str(path), listfile=False)
        try:
            with self.assertRaisesRegex(NotImplementedError, 'Encryption'):
                legacy.read_file('(listfile)')
        finally:legacy.file.close()
        self.assertEqual(len(self.extract()['files']), 18)

    def test_patch_locale_expansion_and_base_priority(self):
        self.archive('war3.mpq', {inner: b'base' for inner in data.WANT.values()})
        self.archive('War3x.mpq', {data.WANT[n]: b'expansion' for n in data.TABLES[:3]})
        self.archive('War3xLocal.mpq', {data.WANT[n]: b'locale' for n in data.TABLES[:2]})
        self.archive('War3Patch.mpq', {data.WANT[data.TABLES[0]]: b'patch'})
        self.extract()
        for name, expected in zip(data.TABLES, (b'patch', b'locale', b'expansion', b'base')):
            self.assertEqual((self.output / name).read_bytes(), expected)
        self.assertEqual((self.output / 'MiscData.txt').read_bytes(), b'base')
        self.assertEqual((self.output / 'UI_MiscData.txt').read_bytes(), b'base')

    def test_broken_patch_is_not_silently_replaced_by_base(self):
        self.archive('war3.mpq', {inner: b'base' for inner in data.WANT.values()})
        (self.game / 'War3Patch.mpq').write_bytes(b'broken archive')
        with self.assertRaisesRegex(OSError, 'War3Patch.mpq'):self.extract()
        self.assertFalse(self.output.exists())

    def test_missing_table_rejects_stale_output(self):
        self.archive('war3.mpq', {'Units\\UnitBalance.slk': b'new'})
        self.output.mkdir()
        for name in data.TABLES:(self.output / name).write_bytes(b'stale')
        with self.assertRaisesRegex(RuntimeError, '缺少所需数据'):self.extract()
        self.assertFalse((self.output / 'dayuan-data-sources.json').exists())
        self.assertEqual((self.output / 'UnitBalance.slk').read_bytes(), b'stale')

    def test_empty_patch_table_does_not_fall_back(self):
        self.archive('war3.mpq', {inner: b'base' for inner in data.WANT.values()})
        self.archive('War3Patch.mpq', {'Units\\UnitBalance.slk': b''}, flags=0)
        with self.assertRaisesRegex(ValueError, '数据大小异常'):self.extract()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':unittest.main()
