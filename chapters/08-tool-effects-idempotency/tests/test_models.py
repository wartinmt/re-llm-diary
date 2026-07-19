from __future__ import annotations

import unittest

from models import (
    ActionResult,
    ModelValidationError,
    ToolReceipt,
    new_action_id,
    utc_now,
    validate_idempotency_key,
    validate_payload,
)


class ModelTests(unittest.TestCase):
    def test_01_valid_key(self):
        self.assertEqual(validate_idempotency_key("order:123-abc"), "order:123-abc")

    def test_02_key_is_trimmed(self):
        self.assertEqual(validate_idempotency_key("  abc:def  "), "abc:def")

    def test_03_short_key_rejected(self):
        with self.assertRaises(ModelValidationError):
            validate_idempotency_key("ab")

    def test_04_space_in_key_rejected(self):
        with self.assertRaises(ModelValidationError):
            validate_idempotency_key("abc def")

    def test_05_non_string_key_rejected(self):
        with self.assertRaises(ModelValidationError):
            validate_idempotency_key(123)  # type: ignore[arg-type]

    def test_06_payload_copy(self):
        raw = {"a": 1}
        clean = validate_payload(raw)
        clean["a"] = 2
        self.assertEqual(raw["a"], 1)

    def test_07_payload_non_mapping_rejected(self):
        with self.assertRaises(ModelValidationError):
            validate_payload([])  # type: ignore[arg-type]

    def test_08_empty_payload_key_rejected(self):
        with self.assertRaises(ModelValidationError):
            validate_payload({"": 1})

    def test_09_receipt_round_trip(self):
        receipt = ToolReceipt.create(
            tool_name="local_note",
            idempotency_key="abc:receipt",
            effect_ref="/tmp/note.txt",
            metadata={"x": 1},
        )
        self.assertEqual(ToolReceipt.from_dict(receipt.to_dict()), receipt)

    def test_10_invalid_receipt_outcome_rejected(self):
        with self.assertRaises(ModelValidationError):
            ToolReceipt.create(
                tool_name="x",
                idempotency_key="abc:bad",
                effect_ref="ref",
                outcome="maybe",
            )

    def test_11_action_result_serializes_receipt(self):
        receipt = ToolReceipt.create(
            tool_name="x", idempotency_key="abc:result", effect_ref="ref"
        )
        result = ActionResult("act_1", "abc:result", "completed", receipt, True, "ok")
        payload = result.to_dict()
        self.assertEqual(payload["receipt"]["receipt_id"], receipt.receipt_id)
        self.assertTrue(payload["reused"])

    def test_12_generated_values_have_expected_shape(self):
        self.assertTrue(new_action_id().startswith("act_"))
        self.assertIn("+00:00", utc_now())
