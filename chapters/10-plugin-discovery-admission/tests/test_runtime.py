import unittest
from common import TempPluginMixin, ROOT
from admission import evaluate_admission
from models import ClarificationState
from receipts import ReceiptStore
from registry import AdmissionStore
from runtime import PluginRuntime
from scanner import scan_plugin

class RuntimeTests(TempPluginMixin, unittest.TestCase):
    def setup_runtime(self):
        a=AdmissionStore(self.root/'data/admissions.json'); r=ReceiptStore(self.root/'data/receipts.json'); rt=PluginRuntime(a,r,self.root/'workspace'); return a,r,rt
    def test_01_first_question(self):
        _,_,rt=self.setup_runtime(); self.assertEqual(rt.next_question(scan_plugin(ROOT/'plugins/local_note'),ClarificationState('local_note')),'笔记标题是什么？')
    def test_02_second_question(self):
        _,_,rt=self.setup_runtime(); s=ClarificationState('local_note',{'title':'x'}); self.assertEqual(rt.next_question(scan_plugin(ROOT/'plugins/local_note'),s),'要保存到哪个目录？')
    def test_03_complete_no_question(self):
        _,_,rt=self.setup_runtime(); s=ClarificationState('local_note',{'title':'x','directory':'d'}); self.assertIsNone(rt.next_question(scan_plugin(ROOT/'plugins/local_note'),s))
    def test_04_provide_strips(self):
        _,_,rt=self.setup_runtime(); s=ClarificationState('x'); rt.provide(s,'a',' x '); self.assertEqual(s.values['a'],'x')
    def test_05_unadmitted_rejected(self):
        _,_,rt=self.setup_runtime();
        with self.assertRaises(RuntimeError): rt.execute(scan_plugin(ROOT/'plugins/local_note'),{'title':'x','directory':'d'})
    def test_06_missing_input(self):
        a,_,rt=self.setup_runtime(); p=scan_plugin(ROOT/'plugins/local_note'); evaluate_admission(p,a,'CONFIRM')
        with self.assertRaises(RuntimeError): rt.execute(p,{'title':'x'})
    def test_07_execute_note(self):
        a,_,rt=self.setup_runtime(); p=scan_plugin(ROOT/'plugins/local_note'); evaluate_admission(p,a,'CONFIRM'); x=rt.execute(p,{'title':'x','directory':'d'}); self.assertTrue((self.root/'workspace/d/x.md').exists())
    def test_08_reuse_note(self):
        a,_,rt=self.setup_runtime(); p=scan_plugin(ROOT/'plugins/local_note'); evaluate_admission(p,a,'CONFIRM'); x=rt.execute(p,{'title':'x','directory':'d'}); y=rt.execute(p,{'title':'x','directory':'d'}); self.assertTrue(y.reused); self.assertEqual(x.receipt_id,y.receipt_id)
    def test_09_single_file(self):
        a,_,rt=self.setup_runtime(); p=scan_plugin(ROOT/'plugins/local_note'); evaluate_admission(p,a,'CONFIRM'); rt.execute(p,{'title':'x','directory':'d'}); rt.execute(p,{'title':'x','directory':'d'}); self.assertEqual(len(list((self.root/'workspace').rglob('*.md'))),1)
    def test_10_read_only_execute_preview(self):
        a,_,rt=self.setup_runtime(); p=scan_plugin(ROOT/'plugins/safe_lookup'); evaluate_admission(p,a); x=rt.execute(p,{'query':'runtime'}); self.assertEqual(x.output['answer'],'运行时协调层')
