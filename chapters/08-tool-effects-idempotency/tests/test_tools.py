from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import (
    CompensationError,
    EffectUnknownError,
    LocalNoteTool,
    OpaqueCounterTool,
    SimulatedProcessCrash,
    ToolError,
    ToolInputError,
)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.note = LocalNoteTool(self.root / "note")
        self.opaque = OpaqueCounterTool(self.root / "opaque")

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_note_creates_file(self):
        receipt = self.note.execute({"title": "A", "body": "B"}, "abc:note")
        self.assertTrue(Path(receipt.effect_ref).exists())

    def test_02_note_content(self):
        receipt = self.note.execute({"title": "A", "body": "B"}, "abc:content")
        self.assertEqual(Path(receipt.effect_ref).read_text(encoding="utf-8"), "A\n\nB\n")

    def test_03_note_same_key_reuses_service_receipt(self):
        first = self.note.execute({"title": "A", "body": "B"}, "abc:same")
        second = self.note.execute({"title": "X", "body": "Y"}, "abc:same")
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.note.notes_dir.glob("*.txt"))), 1)

    def test_04_note_lookup(self):
        receipt = self.note.execute({"title": "A", "body": "B"}, "abc:lookup")
        self.assertEqual(self.note.lookup("abc:lookup"), receipt)

    def test_05_note_lookup_missing(self):
        self.assertIsNone(self.note.lookup("abc:missing"))

    def test_06_note_missing_title_rejected(self):
        with self.assertRaises(ToolInputError):
            self.note.execute({"body": "B"}, "abc:no-title")

    def test_07_note_missing_body_rejected(self):
        with self.assertRaises(ToolInputError):
            self.note.execute({"title": "A"}, "abc:no-body")

    def test_08_crash_happens_after_durable_service_receipt(self):
        with self.assertRaises(SimulatedProcessCrash):
            self.note.execute(
                {"title": "A", "body": "B"},
                "abc:crash",
                simulate="crash_after_effect",
            )
        self.assertIsNotNone(self.note.lookup("abc:crash"))

    def test_09_compensation_deletes_file(self):
        original = self.note.execute({"title": "A", "body": "B"}, "abc:create")
        compensated = self.note.compensate(original, "abc:undo")
        self.assertFalse(Path(original.effect_ref).exists())
        self.assertEqual(compensated.outcome, "compensated")

    def test_10_compensation_is_idempotent(self):
        original = self.note.execute({"title": "A", "body": "B"}, "abc:create2")
        first = self.note.compensate(original, "abc:undo2")
        second = self.note.compensate(original, "abc:undo2")
        self.assertEqual(first, second)

    def test_11_wrong_tool_receipt_compensation_rejected(self):
        from models import ToolReceipt

        foreign = ToolReceipt.create(
            tool_name="other", idempotency_key="abc:foreign", effect_ref="ref"
        )
        with self.assertRaises(CompensationError):
            self.note.compensate(foreign, "abc:foreign-undo")

    def test_12_corrupt_service_state_rejected(self):
        self.note.service_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.note.service_state_path.write_text("{", encoding="utf-8")
        with self.assertRaises(ToolError):
            self.note.lookup("abc:corrupt")

    def test_13_opaque_increments(self):
        receipt = self.opaque.execute({"amount": 2}, "abc:opaque")
        self.assertEqual(receipt.metadata["value"], 2)

    def test_14_opaque_lose_response_after_effect(self):
        with self.assertRaises(EffectUnknownError):
            self.opaque.execute(
                {"amount": 1}, "abc:lost", simulate="lose_response"
            )
        self.assertEqual(self.opaque.counter_path.read_text().strip(), "1")

    def test_15_opaque_invalid_amount_rejected(self):
        with self.assertRaises(ToolInputError):
            self.opaque.execute({"amount": 0}, "abc:zero")

    def test_16_opaque_lookup_unsupported(self):
        with self.assertRaises(ToolError):
            self.opaque.lookup("abc:opaque")
