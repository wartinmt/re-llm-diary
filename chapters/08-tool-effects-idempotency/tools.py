"""Local tools used to demonstrate side effects without touching real services."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from models import ToolReceipt, validate_idempotency_key


class ToolError(RuntimeError):
    pass


class ToolInputError(ToolError):
    pass


class SimulatedProcessCrash(ToolError):
    """The effect happened, but the runtime stopped before it persisted its receipt."""


class EffectUnknownError(ToolError):
    """A non-queryable tool may have applied the effect, but no proof is available."""


class CompensationError(ToolError):
    pass


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


@dataclass
class LocalNoteTool:
    root: Path

    name: str = "local_note"
    queryable: bool = True
    compensatable: bool = True

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def service_state_path(self) -> Path:
        return self.root / "local_note_service.json"

    def _load_service_state(self) -> dict[str, dict[str, Any]]:
        if not self.service_state_path.exists():
            return {}
        try:
            payload = json.loads(self.service_state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ToolError("local note service state is unreadable") from exc
        if not isinstance(payload, dict):
            raise ToolError("local note service state must be an object")
        return payload

    def _save_service_state(self, state: Mapping[str, Any]) -> None:
        _atomic_json_write(self.service_state_path, state)

    @staticmethod
    def _filename_for_key(key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"note-{digest}.txt"

    def execute(
        self,
        payload: Mapping[str, Any],
        idempotency_key: str,
        *,
        simulate: str | None = None,
    ) -> ToolReceipt:
        key = validate_idempotency_key(idempotency_key)
        title = payload.get("title")
        body = payload.get("body")
        if not isinstance(title, str) or not title.strip():
            raise ToolInputError("title must be a non-empty string")
        if not isinstance(body, str) or not body.strip():
            raise ToolInputError("body must be a non-empty string")

        state = self._load_service_state()
        existing = state.get(key)
        if existing is not None:
            return ToolReceipt.from_dict(existing)

        self.notes_dir.mkdir(parents=True, exist_ok=True)
        note_path = self.notes_dir / self._filename_for_key(key)
        note_path.write_text(f"{title.strip()}\n\n{body.strip()}\n", encoding="utf-8")
        receipt = ToolReceipt.create(
            tool_name=self.name,
            idempotency_key=key,
            effect_ref=str(note_path),
            metadata={"title": title.strip(), "path": str(note_path)},
        )
        state[key] = receipt.to_dict()
        self._save_service_state(state)
        if simulate == "crash_after_effect":
            raise SimulatedProcessCrash(
                "simulated process crash after tool effect and durable tool receipt"
            )
        return receipt

    def lookup(self, idempotency_key: str) -> ToolReceipt | None:
        key = validate_idempotency_key(idempotency_key)
        raw = self._load_service_state().get(key)
        return ToolReceipt.from_dict(raw) if raw else None

    def compensate(
        self,
        original: ToolReceipt,
        compensation_key: str,
    ) -> ToolReceipt:
        key = validate_idempotency_key(compensation_key)
        if original.tool_name != self.name:
            raise CompensationError("receipt belongs to a different tool")
        state = self._load_service_state()
        existing = state.get(key)
        if existing is not None:
            return ToolReceipt.from_dict(existing)
        note_path = Path(original.effect_ref)
        existed = note_path.exists()
        note_path.unlink(missing_ok=True)
        receipt = ToolReceipt.create(
            tool_name=self.name,
            idempotency_key=key,
            effect_ref=str(note_path),
            outcome="compensated",
            metadata={
                "compensates_receipt_id": original.receipt_id,
                "file_existed_before_compensation": existed,
            },
        )
        state[key] = receipt.to_dict()
        self._save_service_state(state)
        return receipt


@dataclass
class OpaqueCounterTool:
    root: Path

    name: str = "opaque_counter"
    queryable: bool = False
    compensatable: bool = False

    @property
    def counter_path(self) -> Path:
        return self.root / "opaque_counter.txt"

    def execute(
        self,
        payload: Mapping[str, Any],
        idempotency_key: str,
        *,
        simulate: str | None = None,
    ) -> ToolReceipt:
        validate_idempotency_key(idempotency_key)
        amount = payload.get("amount", 1)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ToolInputError("amount must be a positive integer")
        current = 0
        if self.counter_path.exists():
            try:
                current = int(self.counter_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError) as exc:
                raise ToolError("opaque counter state is unreadable") from exc
        new_value = current + amount
        self.counter_path.parent.mkdir(parents=True, exist_ok=True)
        self.counter_path.write_text(f"{new_value}\n", encoding="utf-8")
        if simulate == "lose_response":
            raise EffectUnknownError(
                "opaque tool applied a side effect but returned no queryable receipt"
            )
        return ToolReceipt.create(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            effect_ref=f"counter:{new_value}",
            metadata={"value": new_value},
        )

    def lookup(self, idempotency_key: str) -> ToolReceipt | None:
        raise ToolError("opaque counter does not support lookup")
