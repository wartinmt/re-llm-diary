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
        if self.service_state_path.is_symlink():
            raise ToolError("local note service state must not be a symbolic link")
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
        if self.service_state_path.is_symlink():
            raise ToolError("local note service state must not be a symbolic link")
        _atomic_json_write(self.service_state_path, state)

    def _safe_note_path(self, key: str, *, create_directory: bool) -> Path:
        if self.root.is_symlink():
            raise ToolError("local note root must not be a symbolic link")
        root = self.root.resolve()
        notes = self.notes_dir
        if notes.is_symlink():
            raise ToolError("local note directory must not be a symbolic link")
        if create_directory:
            notes.mkdir(parents=True, exist_ok=True)
        resolved_notes = notes.resolve()
        if resolved_notes.parent != root:
            raise ToolError("local note directory escapes the tool root")
        target = resolved_notes / self._filename_for_key(key)
        if target.is_symlink() or target.resolve(strict=False).parent != resolved_notes:
            raise ToolError("local note path escapes the note directory")
        return target

    def _validate_existing_note(
        self,
        receipt: ToolReceipt,
        *,
        key: str,
        title: str,
        body: str,
        note_path: Path,
    ) -> None:
        if (
            receipt.tool_name != self.name
            or receipt.idempotency_key != key
            or receipt.outcome != "applied"
            or receipt.metadata.get("title") != title
            or receipt.metadata.get("body_sha256")
            != hashlib.sha256(body.encode("utf-8")).hexdigest()
            or receipt.metadata.get("content_sha256")
            != hashlib.sha256(
                f"{title}\n\n{body}\n".encode("utf-8")
            ).hexdigest()
            or Path(receipt.effect_ref).resolve(strict=False) != note_path
        ):
            raise ToolInputError(
                "idempotency key is already bound to a different local note request"
            )

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
        clean_title = title.strip()
        clean_body = body.strip()
        note_path = self._safe_note_path(key, create_directory=True)

        state = self._load_service_state()
        existing = state.get(key)
        if existing is not None:
            receipt = ToolReceipt.from_dict(existing)
            self._validate_existing_note(
                receipt,
                key=key,
                title=clean_title,
                body=clean_body,
                note_path=note_path,
            )
            return receipt

        content = f"{clean_title}\n\n{clean_body}\n"
        with note_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        receipt = ToolReceipt.create(
            tool_name=self.name,
            idempotency_key=key,
            effect_ref=str(note_path),
            metadata={
                "title": clean_title,
                "body_sha256": hashlib.sha256(clean_body.encode("utf-8")).hexdigest(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "path": str(note_path),
            },
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
        if not raw:
            return None
        receipt = ToolReceipt.from_dict(raw)
        note_path = self._safe_note_path(key, create_directory=False)
        if (
            receipt.tool_name != self.name
            or receipt.idempotency_key != key
            or receipt.outcome != "applied"
            or Path(receipt.effect_ref).resolve(strict=False) != note_path
        ):
            raise ToolError("local note service receipt binding is invalid")
        if not note_path.is_file():
            raise ToolError(
                "local note receipt exists but the real file is missing"
            )
        expected_hash = receipt.metadata.get("content_sha256")
        if (
            expected_hash is not None
            and hashlib.sha256(note_path.read_bytes()).hexdigest() != expected_hash
        ):
            raise ToolError("local note content no longer matches its service receipt")
        return receipt

    def compensate(
        self,
        original: ToolReceipt,
        compensation_key: str,
    ) -> ToolReceipt:
        key = validate_idempotency_key(compensation_key)
        if original.tool_name != self.name:
            raise CompensationError("receipt belongs to a different tool")
        note_path = self._safe_note_path(original.idempotency_key, create_directory=False)
        if Path(original.effect_ref).resolve(strict=False) != note_path:
            raise CompensationError("original receipt points outside its deterministic note path")
        state = self._load_service_state()
        existing = state.get(key)
        if existing is not None:
            receipt = ToolReceipt.from_dict(existing)
            if (
                receipt.tool_name != self.name
                or receipt.outcome != "compensated"
                or receipt.metadata.get("compensates_receipt_id") != original.receipt_id
                or Path(receipt.effect_ref).resolve(strict=False) != note_path
            ):
                raise CompensationError(
                    "compensation key is already bound to a different effect"
                )
            return receipt
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
        if self.root.is_symlink() or self.counter_path.is_symlink():
            raise ToolError("opaque counter state must not use symbolic links")
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
