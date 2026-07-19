"""Atomic local receipt store."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import ToolReceipt

SCHEMA_VERSION = 1


class ReceiptStoreError(RuntimeError):
    pass


class ReceiptFormatError(ReceiptStoreError):
    pass


class ReceiptConflictError(ReceiptStoreError):
    pass


@dataclass
class ReceiptStore:
    path: Path

    def load(self) -> dict[str, ToolReceipt]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReceiptFormatError(f"cannot read receipt store: {self.path}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ReceiptFormatError("unsupported receipt store schema")
        raw_receipts = payload.get("receipts")
        if not isinstance(raw_receipts, dict):
            raise ReceiptFormatError("receipts must be an object")
        clean: dict[str, ToolReceipt] = {}
        for key, value in raw_receipts.items():
            receipt = ToolReceipt.from_dict(value)
            if receipt.idempotency_key != key:
                raise ReceiptFormatError("receipt key does not match receipt payload")
            clean[key] = receipt
        return clean

    def get(self, idempotency_key: str) -> ToolReceipt | None:
        return self.load().get(idempotency_key)

    def put(self, receipt: ToolReceipt) -> ToolReceipt:
        receipts = self.load()
        existing = receipts.get(receipt.idempotency_key)
        if existing is not None:
            if existing == receipt:
                return existing
            raise ReceiptConflictError(
                f"idempotency key {receipt.idempotency_key!r} already has a different receipt"
            )
        receipts[receipt.idempotency_key] = receipt
        self._save(receipts)
        return receipt

    def all(self) -> list[ToolReceipt]:
        return list(self.load().values())

    def _save(self, receipts: dict[str, ToolReceipt]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "receipts": {key: receipt.to_dict() for key, receipt in receipts.items()},
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
