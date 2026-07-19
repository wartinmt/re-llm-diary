from __future__ import annotations

import tempfile
from pathlib import Path

from actions import ActionCoordinator
from journal import ActionJournal
from receipts import ReceiptStore
from tools import LocalNoteTool, OpaqueCounterTool


class TempCoordinatorMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.coordinator = ActionCoordinator(
            journal=ActionJournal(self.base / "action_journal.jsonl"),
            receipts=ReceiptStore(self.base / "receipts.json"),
            tools={
                "local_note": LocalNoteTool(self.base / "tool_state"),
                "opaque_counter": OpaqueCounterTool(self.base / "tool_state"),
            },
        )

    def tearDown(self):
        self._tmp.cleanup()
