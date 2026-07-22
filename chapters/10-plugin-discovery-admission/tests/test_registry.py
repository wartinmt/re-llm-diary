import unittest
from common import TempPluginMixin, ROOT
from registry import AdmissionStore
from scanner import scan_plugin

class RegistryTests(TempPluginMixin, unittest.TestCase):
    def store(self): return AdmissionStore(self.root/'data/admissions.json')
    def test_01_empty(self): self.assertEqual(self.store().load(),{})
    def test_02_record(self): self.assertEqual(self.store().record('x','f','admitted','ok').status,'admitted')
    def test_03_roundtrip(self):
        s=self.store(); s.record('x','f','admitted','ok'); self.assertEqual(s.load()['x'].fingerprint,'f')
    def test_04_unreviewed(self): self.assertEqual(self.store().status_for(scan_plugin(ROOT/'plugins/safe_lookup')),'unreviewed')
    def test_05_rejected_static(self): self.assertEqual(self.store().status_for(scan_plugin(ROOT/'plugins/manifest_mismatch')),'rejected')
    def test_06_admitted(self):
        r=scan_plugin(ROOT/'plugins/safe_lookup'); s=self.store(); s.record(r.manifest.name,r.fingerprint,'admitted','ok'); self.assertEqual(s.status_for(r),'admitted')
    def test_07_stale(self):
        d=self.copy_plugin('safe_lookup'); r=scan_plugin(d); s=self.store(); s.record(r.manifest.name,r.fingerprint,'admitted','ok'); (d/'plugin.py').write_text((d/'plugin.py').read_text()+'\n# changed',encoding='utf-8'); self.assertEqual(s.status_for(scan_plugin(d)),'stale')
    def test_08_atomic_parent_created(self):
        s=self.store(); s.record('x','f','admitted','ok'); self.assertTrue(s.path.exists())
    def test_09_replace_record(self):
        s=self.store(); s.record('x','a','rejected','bad'); s.record('x','b','admitted','ok'); self.assertEqual(s.load()['x'].fingerprint,'b')
    def test_10_corrupt_rejected(self):
        s=self.store(); s.path.parent.mkdir(parents=True); s.path.write_text('{}',encoding='utf-8')
        with self.assertRaises(RuntimeError): s.load()
