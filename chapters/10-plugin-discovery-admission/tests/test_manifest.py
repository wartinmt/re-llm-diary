import json
import unittest
from pathlib import Path
from common import TempPluginMixin, ROOT
from manifest import load_manifest
from models import ManifestError

class ManifestTests(TempPluginMixin, unittest.TestCase):
    def test_01_load_safe(self): self.assertEqual(load_manifest(ROOT/'plugins/safe_lookup/plugin.json').name, 'safe_lookup')
    def test_02_required_inputs_tuple(self): self.assertEqual(load_manifest(ROOT/'plugins/local_note/plugin.json').required_inputs, ('title','directory'))
    def test_03_explicit_admission(self): self.assertTrue(load_manifest(ROOT/'plugins/local_note/plugin.json').requires_explicit_admission())
    def test_04_read_only_not_explicit(self): self.assertFalse(load_manifest(ROOT/'plugins/safe_lookup/plugin.json').requires_explicit_admission())
    def test_05_invalid_json(self):
        p=self.root/'plugin.json'; p.write_text('{',encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_06_top_level_array(self):
        p=self.root/'plugin.json'; p.write_text('[]',encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_07_missing_name(self):
        p=self.root/'plugin.json'; p.write_text(json.dumps({'version':'1','entrypoint':'plugin.py','display_name':'x','risk':'read_only','description':'x'}),encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_08_bad_risk(self):
        d=json.loads((ROOT/'plugins/safe_lookup/plugin.json').read_text()); d['risk']='magic'; p=self.root/'plugin.json'; p.write_text(json.dumps(d),encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_09_bad_entrypoint(self):
        d=json.loads((ROOT/'plugins/safe_lookup/plugin.json').read_text()); d['entrypoint']='../x.py'; p=self.root/'plugin.json'; p.write_text(json.dumps(d),encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_10_duplicate_inputs(self):
        d=json.loads((ROOT/'plugins/safe_lookup/plugin.json').read_text()); d['required_inputs']=['x','x']; p=self.root/'plugin.json'; p.write_text(json.dumps(d),encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
    def test_11_query_consistency(self):
        d=json.loads((ROOT/'plugins/safe_lookup/plugin.json').read_text()); d['supports_query']=True; p=self.root/'plugin.json'; p.write_text(json.dumps(d),encoding='utf-8')
        with self.assertRaises(ManifestError): load_manifest(p)
