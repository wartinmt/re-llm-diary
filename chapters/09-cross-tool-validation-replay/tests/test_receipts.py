import json
from models import ToolReceipt
from receipts import ReceiptStore, ReceiptStoreError
from common import RuntimeCase

class ReceiptTests(RuntimeCase):
    def receipt(self, key="k", rid="r"): return ToolReceipt(rid,"tool",key,"op","ref","applied",{})
    def test_11_missing_returns_none(self): self.assertIsNone(ReceiptStore(self.root/"r.json").get("x"))
    def test_12_save_and_get(self):
        s=ReceiptStore(self.root/"r.json"); r=self.receipt(); s.save(r); self.assertEqual(s.get("k"),r)
    def test_13_save_same_twice(self):
        s=ReceiptStore(self.root/"r.json"); r=self.receipt(); s.save(r); s.save(r); self.assertEqual(len(s.all()),1)
    def test_14_conflict_rejected(self):
        s=ReceiptStore(self.root/"r.json"); s.save(self.receipt());
        with self.assertRaises(ReceiptStoreError): s.save(self.receipt(rid="r2"))
    def test_15_invalid_json(self):
        p=self.root/"r.json"; p.write_text("{",encoding="utf-8")
        with self.assertRaises(ReceiptStoreError): ReceiptStore(p).all()
    def test_16_invalid_top(self):
        p=self.root/"r.json"; p.write_text("[]",encoding="utf-8")
        with self.assertRaises(ReceiptStoreError): ReceiptStore(p).all()
    def test_17_unicode_roundtrip(self):
        s=ReceiptStore(self.root/"r.json"); r=ToolReceipt("r","工具","键","op","引用","applied",{"标题":"中文"}); s.save(r); self.assertEqual(s.get("键"),r)
    def test_18_atomic_leaves_no_tmp(self):
        s=ReceiptStore(self.root/"r.json"); s.save(self.receipt()); self.assertFalse(any(p.suffix==".tmp" for p in self.root.iterdir()))
