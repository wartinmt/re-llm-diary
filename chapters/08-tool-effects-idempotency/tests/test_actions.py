from __future__ import annotations

import unittest
from pathlib import Path

from actions import (
    ActionCoordinatorError,
    CompensationNotSupportedError,
    ConfirmationRequiredError,
    RetryBlockedError,
    UnknownToolError,
)
from tools import SimulatedProcessCrash
from common import TempCoordinatorMixin


class ActionCoordinatorTests(TempCoordinatorMixin, unittest.TestCase):
    def create(self, key="abc:create"):
        return self.coordinator.execute(
            tool_name="local_note",
            payload={"title": "A", "body": "B"},
            idempotency_key=key,
        )

    def test_01_execute_completes(self):
        result = self.create()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.reused)

    def test_02_execute_persists_receipt(self):
        result = self.create()
        self.assertEqual(self.coordinator.receipts.get("abc:create"), result.receipt)

    def test_03_execute_records_expected_events(self):
        self.create()
        types = [e["event_type"] for e in self.coordinator.journal.find_by_key("abc:create")]
        self.assertEqual(
            types,
            ["action_planned", "effect_started", "effect_confirmed", "action_completed"],
        )

    def test_04_duplicate_key_reuses_receipt(self):
        first = self.create()
        second = self.coordinator.execute(
            tool_name="local_note",
            payload={"title": "X", "body": "Y"},
            idempotency_key="abc:create",
        )
        self.assertEqual(first.receipt, second.receipt)
        self.assertTrue(second.reused)

    def test_05_duplicate_does_not_create_second_file(self):
        self.create()
        self.create()
        notes = list((self.base / "tool_state" / "notes").glob("*.txt"))
        self.assertEqual(len(notes), 1)

    def test_06_unknown_tool_rejected(self):
        with self.assertRaises(UnknownToolError):
            self.coordinator.execute(
                tool_name="missing",
                payload={},
                idempotency_key="abc:missing-tool",
            )

    def test_07_input_failure_is_journaled(self):
        with self.assertRaises(Exception):
            self.coordinator.execute(
                tool_name="local_note",
                payload={"title": "A"},
                idempotency_key="abc:bad-input",
            )
        self.assertEqual(
            self.coordinator.journal.find_by_key("abc:bad-input")[-1]["event_type"],
            "effect_failed",
        )

    def test_08_unknown_effect_status(self):
        result = self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:unknown",
            simulate="lose_response",
        )
        self.assertEqual(result.status, "effect_unknown")

    def test_09_same_key_unknown_retry_blocked(self):
        self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:unknown2",
            simulate="lose_response",
        )
        with self.assertRaises(RetryBlockedError):
            self.coordinator.execute(
                tool_name="opaque_counter",
                payload={"amount": 1},
                idempotency_key="abc:unknown2",
            )

    def test_10_crash_is_recorded(self):
        with self.assertRaises(SimulatedProcessCrash):
            self.coordinator.execute(
                tool_name="local_note",
                payload={"title": "A", "body": "B"},
                idempotency_key="abc:crash",
                simulate="crash_after_effect",
            )
        self.assertEqual(
            self.coordinator.journal.find_by_key("abc:crash")[-1]["event_type"],
            "runtime_interrupted",
        )

    def test_11_replay_returns_action_events(self):
        result = self.create("abc:replay")
        self.assertEqual(len(self.coordinator.replay(result.action_id)), 4)

    def test_12_replay_missing_rejected(self):
        with self.assertRaises(ActionCoordinatorError):
            self.coordinator.replay("act_missing")

    def test_13_summaries_group_actions(self):
        self.create("abc:sum1")
        self.create("abc:sum2")
        self.assertEqual(len(self.coordinator.summaries()), 2)

    def test_14_compensation_requires_confirmation(self):
        self.create("abc:original")
        with self.assertRaises(ConfirmationRequiredError):
            self.coordinator.compensate(
                original_key="abc:original",
                compensation_key="abc:undo",
                confirm="yes",
            )

    def test_15_compensation_completes(self):
        original = self.create("abc:original2")
        result = self.coordinator.compensate(
            original_key="abc:original2",
            compensation_key="abc:undo2",
            confirm="CONFIRM",
        )
        self.assertEqual(result.status, "compensated")
        self.assertFalse(Path(original.receipt.effect_ref).exists())

    def test_16_compensation_keeps_original_receipt(self):
        self.create("abc:original3")
        self.coordinator.compensate(
            original_key="abc:original3",
            compensation_key="abc:undo3",
            confirm="CONFIRM",
        )
        self.assertIsNotNone(self.coordinator.receipts.get("abc:original3"))
        self.assertIsNotNone(self.coordinator.receipts.get("abc:undo3"))

    def test_17_compensation_duplicate_reuses(self):
        self.create("abc:original4")
        first = self.coordinator.compensate(
            original_key="abc:original4",
            compensation_key="abc:undo4",
            confirm="CONFIRM",
        )
        second = self.coordinator.compensate(
            original_key="abc:original4",
            compensation_key="abc:undo4",
            confirm="CONFIRM",
        )
        self.assertEqual(first.receipt, second.receipt)
        self.assertTrue(second.reused)

    def test_18_opaque_compensation_rejected(self):
        result = self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:opaque-ok",
        )
        self.assertIsNotNone(result.receipt)
        with self.assertRaises(CompensationNotSupportedError):
            self.coordinator.compensate(
                original_key="abc:opaque-ok",
                compensation_key="abc:opaque-undo",
                confirm="CONFIRM",
            )

    def test_19_compensation_needs_distinct_key(self):
        self.create("abc:same-comp")
        with self.assertRaises(ActionCoordinatorError):
            self.coordinator.compensate(
                original_key="abc:same-comp",
                compensation_key="abc:same-comp",
                confirm="CONFIRM",
            )

    def test_20_parent_link_on_manual_retry(self):
        original = self.coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="abc:parent-old",
            simulate="lose_response",
        )
        retried = self.coordinator.retry_unknown(
            old_key="abc:parent-old",
            new_key="abc:parent-new",
            confirm="CONFIRM",
            payload={"amount": 1},
        )
        events = self.coordinator.journal.find_by_key("abc:parent-new")
        self.assertEqual(events[0]["parent_action_id"], original.action_id)
        self.assertEqual(retried.status, "completed")
