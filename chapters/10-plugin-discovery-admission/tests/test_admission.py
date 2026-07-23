import unittest
from common import TempPluginMixin, ROOT
from admission import evaluate_admission, run_method, snapshot
from models import AdmissionError
from registry import AdmissionStore
from scanner import scan_plugin

class AdmissionTests(TempPluginMixin, unittest.TestCase):
    def store(self): return AdmissionStore(self.root/'data/admissions.json')
    def test_01_safe_admitted(self): self.assertEqual(evaluate_admission(scan_plugin(ROOT/'plugins/safe_lookup'),self.store()),'admitted')
    def test_02_note_pending(self): self.assertEqual(evaluate_admission(scan_plugin(ROOT/'plugins/local_note'),self.store()),'pending_confirmation')
    def test_03_note_confirmed(self): self.assertEqual(evaluate_admission(scan_plugin(ROOT/'plugins/local_note'),self.store(),'CONFIRM'),'admitted')
    def test_04_bad_probe_rejected(self): self.assertEqual(evaluate_admission(scan_plugin(ROOT/'plugins/bad_probe'),self.store()),'rejected')
    def test_05_static_bad_rejected(self): self.assertEqual(evaluate_admission(scan_plugin(ROOT/'plugins/manifest_mismatch'),self.store()),'rejected')
    def test_06_probe_json(self): self.assertTrue(run_method(scan_plugin(ROOT/'plugins/safe_lookup'),'probe',self.root)['ok'])
    def test_07_preview_json(self): self.assertEqual(run_method(scan_plugin(ROOT/'plugins/safe_lookup'),'preview',self.root,{'query':'runtime'})['query'],'runtime')
    def test_08_snapshot_empty(self): self.assertEqual(snapshot(self.root),{})
    def test_09_snapshot_file(self):
        (self.root/'a').write_text('x'); self.assertIn('a',snapshot(self.root))
    def test_10_status_saved(self):
        s=self.store(); r=scan_plugin(ROOT/'plugins/safe_lookup'); evaluate_admission(r,s); self.assertEqual(s.status_for(r),'admitted')
    def test_11_pending_saved(self):
        s=self.store(); r=scan_plugin(ROOT/'plugins/local_note'); evaluate_admission(r,s); self.assertEqual(s.status_for(r),'pending_confirmation')
    def test_12_bad_method_raises(self):
        with self.assertRaises(Exception): run_method(scan_plugin(ROOT/'plugins/safe_lookup'),'execute',self.root)
    def test_13_probe_does_not_write_bytecode_into_plugin(self):
        d=self.copy_plugin('safe_lookup'); run_method(scan_plugin(d),'probe',self.root/'workspace')
        self.assertFalse((d/'__pycache__').exists())
