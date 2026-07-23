"""Append-only hash-chained action journal."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from models import utc_now


class JournalError(RuntimeError):
    pass


class JournalFormatError(JournalError):
    pass


class TrailingFragmentError(JournalFormatError):
    pass


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_hash(event_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(event_without_hash).encode("utf-8")).hexdigest()


@dataclass
class ActionJournal:
    path: Path

    def append(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        event_type: str,
        tool_name: str,
        payload: Mapping[str, Any] | None = None,
        parent_action_id: str | None = None,
    ) -> dict[str, Any]:
        events = self.read_all()
        previous_hash = events[-1]["event_hash"] if events else "0" * 64
        event_without_hash = {
            "seq": len(events) + 1,
            "timestamp": utc_now(),
            "action_id": action_id,
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "event_type": event_type,
            "parent_action_id": parent_action_id,
            "payload": dict(payload or {}),
            "previous_hash": previous_hash,
        }
        event = {**event_without_hash, "event_hash": _event_hash(event_without_hash)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise TrailingFragmentError(
                "action journal ends with an incomplete line; run the explicit repair command after backing up data"
            )
        events: list[dict[str, Any]] = []
        previous_hash = "0" * 64
        for line_number, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalFormatError(f"invalid JSON at journal line {line_number}") from exc
            self._validate_event(event, line_number, previous_hash)
            events.append(event)
            previous_hash = event["event_hash"]
        return events

    @staticmethod
    def _validate_event(event: Any, line_number: int, expected_previous_hash: str) -> None:
        if not isinstance(event, dict):
            raise JournalFormatError(f"journal line {line_number} is not an object")
        required = {
            "seq",
            "timestamp",
            "action_id",
            "idempotency_key",
            "tool_name",
            "event_type",
            "parent_action_id",
            "payload",
            "previous_hash",
            "event_hash",
        }
        missing = required - set(event)
        if missing:
            raise JournalFormatError(
                f"journal line {line_number} missing fields: {', '.join(sorted(missing))}"
            )
        if event["seq"] != line_number:
            raise JournalFormatError(
                f"journal sequence broken at line {line_number}: got {event['seq']!r}"
            )
        if event["previous_hash"] != expected_previous_hash:
            raise JournalFormatError(f"journal hash chain broken at line {line_number}")
        without_hash = dict(event)
        actual_hash = without_hash.pop("event_hash")
        expected_hash = _event_hash(without_hash)
        if actual_hash != expected_hash:
            raise JournalFormatError(f"journal content hash mismatch at line {line_number}")
        if not isinstance(event["payload"], dict):
            raise JournalFormatError(f"journal payload must be an object at line {line_number}")

    def by_action(self, action_id: str) -> list[dict[str, Any]]:
        return [event for event in self.read_all() if event["action_id"] == action_id]

    def find_by_key(self, idempotency_key: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.read_all()
            if event["idempotency_key"] == idempotency_key
        ]

    def action_summaries(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in self.read_all():
            grouped.setdefault(event["action_id"], []).append(event)
        summaries = []
        for action_id, events in grouped.items():
            last = events[-1]
            summaries.append(
                {
                    "action_id": action_id,
                    "idempotency_key": last["idempotency_key"],
                    "tool_name": last["tool_name"],
                    "event_type": last["event_type"],
                    "event_count": len(events),
                    "parent_action_id": last["parent_action_id"],
                }
            )
        return summaries

    def repair_trailing_fragment(self) -> Path:
        if not self.path.exists():
            raise JournalError("action journal does not exist")
        raw = self.path.read_bytes()
        if not raw or raw.endswith(b"\n"):
            raise JournalError("action journal has no trailing fragment")
        last_newline = raw.rfind(b"\n")
        if last_newline < 0:
            raise JournalError("journal contains no complete event; refusing automatic repair")
        complete = raw[: last_newline + 1]
        backup = self.path.with_suffix(self.path.suffix + ".partial.bak")
        counter = 1
        while backup.exists():
            backup = self.path.with_suffix(self.path.suffix + f".partial.{counter}.bak")
            counter += 1
        shutil.copy2(self.path, backup)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".repair.tmp", dir=self.path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(complete)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        self.read_all()
        return backup
