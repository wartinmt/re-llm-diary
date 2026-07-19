"""Domain models for chapter 08 tool-side-effect experiments."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
import re
import uuid

_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class ModelValidationError(ValueError):
    """Raised when an action or receipt violates the chapter schema."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_action_id() -> str:
    return f"act_{uuid.uuid4().hex}"


def validate_idempotency_key(value: str) -> str:
    if not isinstance(value, str):
        raise ModelValidationError("idempotency_key must be a string")
    normalized = value.strip()
    if not _IDEMPOTENCY_PATTERN.fullmatch(normalized):
        raise ModelValidationError(
            "idempotency_key must be 3-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return normalized


def validate_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError("payload must be an object")
    clean = dict(value)
    for key in clean:
        if not isinstance(key, str) or not key.strip():
            raise ModelValidationError("payload keys must be non-empty strings")
    return clean


@dataclass(frozen=True)
class ToolReceipt:
    receipt_id: str
    tool_name: str
    idempotency_key: str
    effect_ref: str
    outcome: str
    created_at: str
    metadata: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        tool_name: str,
        idempotency_key: str,
        effect_ref: str,
        outcome: str = "applied",
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolReceipt":
        key = validate_idempotency_key(idempotency_key)
        if not tool_name or not isinstance(tool_name, str):
            raise ModelValidationError("tool_name must be a non-empty string")
        if not effect_ref or not isinstance(effect_ref, str):
            raise ModelValidationError("effect_ref must be a non-empty string")
        if outcome not in {"applied", "compensated"}:
            raise ModelValidationError("outcome must be 'applied' or 'compensated'")
        return cls(
            receipt_id=f"rcpt_{uuid.uuid4().hex}",
            tool_name=tool_name,
            idempotency_key=key,
            effect_ref=effect_ref,
            outcome=outcome,
            created_at=utc_now(),
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolReceipt":
        if not isinstance(value, Mapping):
            raise ModelValidationError("receipt must be an object")
        required = {
            "receipt_id",
            "tool_name",
            "idempotency_key",
            "effect_ref",
            "outcome",
            "created_at",
            "metadata",
        }
        missing = required - set(value)
        if missing:
            raise ModelValidationError(f"receipt missing fields: {', '.join(sorted(missing))}")
        validate_idempotency_key(str(value["idempotency_key"]))
        if value["outcome"] not in {"applied", "compensated"}:
            raise ModelValidationError("unsupported receipt outcome")
        if not isinstance(value["metadata"], Mapping):
            raise ModelValidationError("receipt metadata must be an object")
        return cls(
            receipt_id=str(value["receipt_id"]),
            tool_name=str(value["tool_name"]),
            idempotency_key=str(value["idempotency_key"]),
            effect_ref=str(value["effect_ref"]),
            outcome=str(value["outcome"]),
            created_at=str(value["created_at"]),
            metadata=dict(value["metadata"]),
        )


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    idempotency_key: str
    status: str
    receipt: ToolReceipt | None
    reused: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "reused": self.reused,
            "message": self.message,
        }
