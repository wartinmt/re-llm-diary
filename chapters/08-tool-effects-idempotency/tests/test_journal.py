from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from journal import ActionJournal, JournalError, JournalFormatError, TrailingFragmentError


class JournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "actions.jsonl"
        self.journal = ActionJournal(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def append(self, event_type="action_planned", action_id="act_a", key="abc:key"):
        return self.journal.append(
            action_id=action_id,
            idempotency_key=key,
            event_type=event_type,
            tool_name="local_note",
            payload={"n": 1},
        )

    def test_01_missing_file_is_empty(self):
        self.assertEqual(self.journal.read_all(), [])

    def test_02_append_creates_parent(self):
        self.append()
        self.assertTrue(self.path.exists())

    def test_03_sequence_increments(self):
        self.append()
        second = self.append("effect_started")
        self.assertEqual(second["seq"], 2)

    def test_04_hash_chain_links(self):
        first = self.append()
        second = self.append("effect_started")
        self.assertEqual(second["previous_hash"], first["event_hash"])

    def test_05_read_round_trip(self):
        event = self.append()
        self.assertEqual(self.journal.read_all()[0], event)

    def test_06_by_action_filters(self):
        self.append(action_id="act_a")
        self.append(action_id="act_b", key="abc:two")
        self.assertEqual(len(self.journal.by_action("act_a")), 1)

    def test_07_find_by_key_filters(self):
        self.append(key="abc:one")
        self.append(action_id="act_b", key="abc:two")
        self.assertEqual(self.journal.find_by_key("abc:two")[0]["action_id"], "act_b")

    def test_08_action_summaries(self):
        self.append()
        self.append("action_completed")
        summary = self.journal.action_summaries()[0]
        self.assertEqual(summary["event_type"], "action_completed")
        self.assertEqual(summary["event_count"], 2)

    def test_09_trailing_fragment_detected(self):
        self.append()
        with self.path.open("ab") as handle:
            handle.write(b'{"seq":2')
        with self.assertRaises(TrailingFragmentError):
            self.journal.read_all()

    def test_10_repair_trailing_fragment(self):
        first = self.append()
        with self.path.open("ab") as handle:
            handle.write(b'{"seq":2')
        backup = self.journal.repair_trailing_fragment()
        self.assertTrue(backup.exists())
        self.assertEqual(self.journal.read_all(), [first])

    def test_11_repair_clean_file_rejected(self):
        self.append()
        with self.assertRaises(JournalError):
            self.journal.repair_trailing_fragment()

    def test_12_middle_json_damage_rejected(self):
        self.append()
        self.append("effect_started")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        lines[0] = "not-json"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(JournalFormatError):
            self.journal.read_all()

    def test_13_hash_tampering_rejected(self):
        self.append()
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["payload"]["n"] = 2
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaises(JournalFormatError):
            self.journal.read_all()

    def test_14_sequence_tampering_rejected(self):
        self.append()
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["seq"] = 9
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaises(JournalFormatError):
            self.journal.read_all()
