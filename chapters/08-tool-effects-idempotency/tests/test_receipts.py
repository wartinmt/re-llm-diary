from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from models import ToolReceipt
from receipts import ReceiptConflictError, ReceiptFormatError, ReceiptStore


class ReceiptStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "receipts.json"
        self.store = ReceiptStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def receipt(self, key="abc:receipt", ref="ref"):
        return ToolReceipt.create(
            tool_name="local_note", idempotency_key=key, effect_ref=ref
        )

    def test_01_missing_store_empty(self):
        self.assertEqual(self.store.load(), {})

    def test_02_put_and_get(self):
        receipt = self.receipt()
        self.store.put(receipt)
        self.assertEqual(self.store.get(receipt.idempotency_key), receipt)

    def test_03_put_creates_parent(self):
        self.store.put(self.receipt())
        self.assertTrue(self.path.exists())

    def test_04_all_lists_receipts(self):
        self.store.put(self.receipt("abc:one"))
        self.store.put(self.receipt("abc:two"))
        self.assertEqual(len(self.store.all()), 2)

    def test_05_identical_put_is_idempotent(self):
        receipt = self.receipt()
        self.assertEqual(self.store.put(receipt), receipt)
        self.assertEqual(self.store.put(receipt), receipt)

    def test_06_conflicting_put_rejected(self):
        self.store.put(self.receipt(ref="one"))
        with self.assertRaises(ReceiptConflictError):
            self.store.put(self.receipt(ref="two"))

    def test_07_invalid_json_rejected(self):
        self.path.write_text("{", encoding="utf-8")
        with self.assertRaises(ReceiptFormatError):
            self.store.load()

    def test_08_wrong_schema_rejected(self):
        self.path.write_text('{"schema_version":2,"receipts":{}}', encoding="utf-8")
        with self.assertRaises(ReceiptFormatError):
            self.store.load()

    def test_09_receipts_must_be_object(self):
        self.path.write_text('{"schema_version":1,"receipts":[]}', encoding="utf-8")
        with self.assertRaises(ReceiptFormatError):
            self.store.load()

    def test_10_key_mismatch_rejected(self):
        receipt = self.receipt("abc:real")
        payload = {"schema_version": 1, "receipts": {"abc:wrong": receipt.to_dict()}}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ReceiptFormatError):
            self.store.load()

    def test_11_output_ends_with_newline(self):
        self.store.put(self.receipt())
        self.assertTrue(self.path.read_bytes().endswith(b"\n"))

    def test_12_metadata_preserved(self):
        receipt = ToolReceipt.create(
            tool_name="x",
            idempotency_key="abc:meta",
            effect_ref="ref",
            metadata={"nested": {"a": 1}},
        )
        self.store.put(receipt)
        self.assertEqual(self.store.get("abc:meta").metadata["nested"]["a"], 1)
