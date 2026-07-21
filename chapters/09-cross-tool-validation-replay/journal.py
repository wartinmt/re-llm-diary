"""追加式跨工具工作流流水账。"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any


class JournalError(RuntimeError):
    pass


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class EventJournal:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        expected_seq = 1
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise JournalError(f"无法读取流水账：{self.path}") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                raise JournalError(f"第 {line_number} 行为空。")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalError(f"第 {line_number} 行不是完整 JSON。") from exc
            if event.get("seq") != expected_seq:
                raise JournalError(f"第 {line_number} 行 seq 断裂。")
            if event.get("prev_hash") != previous:
                raise JournalError(f"第 {line_number} 行 prev_hash 不匹配。")
            claimed = event.get("event_hash")
            body = dict(event)
            body.pop("event_hash", None)
            actual = sha256(_canonical(body)).hexdigest()
            if claimed != actual:
                raise JournalError(f"第 {line_number} 行内容哈希不匹配。")
            events.append(event)
            previous = claimed
            expected_seq += 1
        return events

    def append(self, workflow_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        events = self.read()
        previous = events[-1]["event_hash"] if events else "0" * 64
        body = {
            "seq": len(events) + 1,
            "workflow_id": workflow_id,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": previous,
        }
        body["event_hash"] = sha256(_canonical(body)).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def for_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [event for event in self.read() if event["workflow_id"] == workflow_id]
