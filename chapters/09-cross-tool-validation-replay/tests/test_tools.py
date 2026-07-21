from tools import DocumentTool, IndexTool, ToolError
from receipts import ReceiptStore
from models import digest_text
from common import RuntimeCase

class ToolTests(RuntimeCase):
    def setUp(self):
        super().setUp(); self.ds=ReceiptStore(self.root/"dr.json"); self.is_=ReceiptStore(self.root/"ir.json"); self.doc=DocumentTool(self.root/"docs",self.ds); self.idx=IndexTool(self.root/"index.json",self.is_)
    def test_29_document_write(self): self.assertEqual(self.doc.write("k","a.md","x").outcome,"applied")
    def test_30_document_exists(self): self.doc.write("k","a.md","x"); self.assertTrue((self.root/"docs/a.md").is_file())
    def test_31_document_idempotent(self):
        a=self.doc.write("k","a.md","x"); b=self.doc.write("k","a.md","DIFF"); self.assertEqual(a.receipt_id,b.receipt_id); self.assertEqual((self.root/"docs/a.md").read_text(),"x")
    def test_32_document_query(self): self.doc.write("k","a.md","x"); self.assertIsNotNone(self.doc.query("k"))
    def test_33_document_escape(self):
        with self.assertRaises(ToolError): self.doc.write("k","../x","x")
    def test_34_document_delete(self): self.doc.write("k","a.md","x"); self.doc.delete("c","a.md","r"); self.assertFalse((self.root/"docs/a.md").exists())
    def test_35_delete_idempotent(self):
        self.doc.write("k","a.md","x"); a=self.doc.delete("c","a.md","r"); b=self.doc.delete("c","a.md","r"); self.assertEqual(a.receipt_id,b.receipt_id)
    def test_36_index_register(self): self.idx.register("k","t","a.md","h"); self.assertEqual(self.idx.record("t")["sha256"],"h")
    def test_37_index_idempotent(self):
        a=self.idx.register("k","t","a","h"); b=self.idx.register("k","t","b","x"); self.assertEqual(a.receipt_id,b.receipt_id); self.assertEqual(self.idx.record("t")["path"],"a")
    def test_38_index_remove(self): self.idx.register("k","t","a","h"); self.idx.remove("c","t","r"); self.assertIsNone(self.idx.record("t"))
    def test_39_index_corrupt(self):
        self.idx.path.write_text("{",encoding="utf-8")
        with self.assertRaises(ToolError): self.idx.record("t")
    def test_40_receipt_hash(self): self.assertEqual(self.doc.write("k","a.md","x").metadata["sha256"],digest_text("x"))
