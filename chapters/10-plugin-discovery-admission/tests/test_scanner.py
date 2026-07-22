import unittest
from pathlib import Path
from common import TempPluginMixin, ROOT
from scanner import discover_plugins, scan_plugin, fingerprint_files

class ScannerTests(TempPluginMixin, unittest.TestCase):
    def test_01_safe_static_ok(self): self.assertTrue(scan_plugin(ROOT/'plugins/safe_lookup').accepted_static)
    def test_02_local_note_static_ok(self): self.assertTrue(scan_plugin(ROOT/'plugins/local_note').accepted_static)
    def test_03_mismatch_rejected(self): self.assertFalse(scan_plugin(ROOT/'plugins/manifest_mismatch').accepted_static)
    def test_04_missing_method_reason(self): self.assertIn('query', ' '.join(scan_plugin(ROOT/'plugins/manifest_mismatch').reasons))
    def test_05_bad_probe_static_passes(self): self.assertTrue(scan_plugin(ROOT/'plugins/bad_probe').accepted_static)
    def test_06_fingerprint_stable(self):
        d=ROOT/'plugins/safe_lookup'; self.assertEqual(fingerprint_files(d/'plugin.json',d/'plugin.py'), fingerprint_files(d/'plugin.json',d/'plugin.py'))
    def test_07_fingerprint_changes(self):
        d=self.copy_plugin('safe_lookup'); a=scan_plugin(d).fingerprint; (d/'plugin.py').write_text((d/'plugin.py').read_text()+'\n# x',encoding='utf-8'); self.assertNotEqual(a,scan_plugin(d).fingerprint)
    def test_08_missing_entrypoint(self):
        d=self.copy_plugin('safe_lookup'); (d/'plugin.py').unlink(); self.assertFalse(scan_plugin(d).accepted_static)
    def test_09_syntax_error(self):
        d=self.copy_plugin('safe_lookup'); (d/'plugin.py').write_text('def broken(',encoding='utf-8'); self.assertFalse(scan_plugin(d).accepted_static)
    def test_10_missing_class(self):
        d=self.copy_plugin('safe_lookup'); (d/'plugin.py').write_text('x=1\n',encoding='utf-8'); self.assertFalse(scan_plugin(d).accepted_static)
    def test_11_discover_four(self): self.assertEqual(len(discover_plugins(ROOT/'plugins')),4)
    def test_12_discover_missing_root(self): self.assertEqual(discover_plugins(self.root/'none'),[])
