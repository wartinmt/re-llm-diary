import unittest
from common import TempPluginMixin
from receipts import ReceiptStore, stable_plan_key
from models import RunReceipt

class ReceiptTests(TempPluginMixin, unittest.TestCase):
    def store(self): return ReceiptStore(self.root/'data/receipts.json')
    def test_01_stable_key(self): self.assertEqual(stable_plan_key('x',{'a':'b'}),stable_plan_key('x',{'a':'b'}))
    def test_02_key_order_independent(self): self.assertEqual(stable_plan_key('x',{'a':'1','b':'2'}),stable_plan_key('x',{'b':'2','a':'1'}))
    def test_03_key_changes_plugin(self): self.assertNotEqual(stable_plan_key('x',{}),stable_plan_key('y',{}))
    def test_04_empty_store(self): self.assertEqual(self.store().load(),{})
    def test_05_put_get(self):
        s=self.store(); r=RunReceipt('r','p','k',{'ok':1}); s.put(r); self.assertEqual(s.get('k').receipt_id,'r')
    def test_06_missing_get(self): self.assertIsNone(self.store().get('none'))
    def test_07_replace(self):
        s=self.store(); s.put(RunReceipt('a','p','k',{})); s.put(RunReceipt('b','p','k',{})); self.assertEqual(s.get('k').receipt_id,'b')
    def test_08_parent_created(self):
        s=self.store(); s.put(RunReceipt('a','p','k',{})); self.assertTrue(s.path.exists())
    def test_09_corrupt_rejected(self):
        s=self.store(); s.path.parent.mkdir(parents=True); s.path.write_text('{}')
        with self.assertRaises(RuntimeError): s.load()
    def test_10_output_roundtrip(self):
        s=self.store(); s.put(RunReceipt('a','p','k',{'path':'x'})); self.assertEqual(s.get('k').output['path'],'x')
