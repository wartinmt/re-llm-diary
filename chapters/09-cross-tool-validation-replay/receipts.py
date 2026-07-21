"""持久工具回执存储。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from models import ToolReceipt


class ReceiptStoreError(RuntimeError):
    pass


class ReceiptStore:
    def __init__(self, path: Path):
        self.path = path

    def _load_raw(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReceiptStoreError(f"无法读取回执文件：{self.path}") from exc
        if not isinstance(data, dict):
            raise ReceiptStoreError("回执文件顶层必须是 JSON 对象。")
        return data

    def get(self, idempotency_key: str) -> ToolReceipt | None:
        raw = self._load_raw().get(idempotency_key)
        return ToolReceipt.from_dict(raw) if raw else None

    def all(self) -> list[ToolReceipt]:
        return [ToolReceipt.from_dict(item) for item in self._load_raw().values()]

    def save(self, receipt: ToolReceipt) -> None:
        data = self._load_raw()
        existing = data.get(receipt.idempotency_key)
        if existing is not None and existing != receipt.to_dict():
            raise ReceiptStoreError("同一幂等键已经绑定到不同回执。")
        data[receipt.idempotency_key] = receipt.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
