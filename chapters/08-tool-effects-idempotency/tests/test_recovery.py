from __future__ import annotations

import unittest
from pathlib import Path

from actions import ActionCoordinatorError, ConfirmationRequiredError, RetryBlockedError
from tools import SimulatedProcessCrash, ToolError
from common import TempCoordinatorMixin


class RecoveryTests(TempCoordinatorMixin, unittest.TestCase):
    def test_01_recover_tool_receipt_after_crash(self):
        with self.assertRaises(SimulatedProcessCrash):
            self.coordinator.execute(
                tool_name="local_note",
                payload={"title": "A", "body": "B"},
                idempotency_key="abc:recover",
                simulate="crash_after_effect",
            )
        result = self.coordinator.recover("abc:recover")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.reused)

    def test_02_recover_does_not_repeat_note(self):
        with self.assertRaises(SimulatedProcessCrash):
            self.coordinator.execute(
                tool_name="local_note",
                payload={"title": "A", "body": "B"},
                idempotency_key="abc:recover2",
                simulate="crash_after_effect",
            )
        self.coordinator.recover("abc:recover2")
        self.assertEqual(len(list((self.base / "tool_state" / "notes").glob("*.txt"))), 1)

    def test_03_recover_existing_runtime_receipt(self):
        self.coordinator.execute(
            tool_name="local_note",
            payload={"title": "A", "body": "B"},
            idempotency_key="abc:already",
        )
        result = self.coordinator.recover("abc:already")
        self.assertEqual(result.message, "runtime receipt already existed")

    def test_04_recover_missing_action_rejected(self):
        with self.assertRaises(ActionCoordinatorError):
            self.coordinator.recover("abc:not-found")

    def test_05_recover_opaque_stays_unknown(self):
        self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:opaque-lost",
            simulate="lose_response",
        )
        result = self.coordinator.recover("abc:opaque-lost")
        self.assertEqual(result.status, "effect_unknown")

    def test_06_retry_unknown_requires_confirmation(self):
        self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:old",
            simulate="lose_response",
        )
        with self.assertRaises(ConfirmationRequiredError):
            self.coordinator.retry_unknown(
                old_key="abc:old",
                new_key="abc:new",
                confirm="NO",
                payload={"amount": 1},
            )

    def test_07_retry_unknown_requires_new_key(self):
        self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:old2",
            simulate="lose_response",
        )
        with self.assertRaises(RetryBlockedError):
            self.coordinator.retry_unknown(
                old_key="abc:old2",
                new_key="abc:old2",
                confirm="CONFIRM",
                payload={"amount": 1},
            )

    def test_08_retry_completed_action_rejected(self):
        self.coordinator.execute(
            tool_name="local_note",
            payload={"title": "A", "body": "B"},
            idempotency_key="abc:done",
        )
        with self.assertRaises(RetryBlockedError):
            self.coordinator.retry_unknown(
                old_key="abc:done",
                new_key="abc:done-new",
                confirm="CONFIRM",
                payload={"title": "A", "body": "B"},
            )

    def test_09_recovery_rejects_receipt_when_real_file_is_missing(self):
        with self.assertRaises(SimulatedProcessCrash):
            self.coordinator.execute(
                tool_name="local_note",
                payload={"title": "A", "body": "B"},
                idempotency_key="abc:missing-reality",
                simulate="crash_after_effect",
            )
        receipt = self.coordinator.tools["local_note"]._load_service_state()[
            "abc:missing-reality"
        ]
        Path(receipt["effect_ref"]).unlink()
        with self.assertRaises(ToolError):
            self.coordinator.recover("abc:missing-reality")
