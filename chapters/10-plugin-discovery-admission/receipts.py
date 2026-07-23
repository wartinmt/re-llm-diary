from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from models import RunReceipt


def stable_plan_key(
    plugin_name: str,
    values: dict[str, str],
    plugin_fingerprint: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "plugin": plugin_name,
            "plugin_fingerprint": plugin_fingerprint,
            "values": values,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReceiptStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, RunReceipt]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise RuntimeError("执行回执格式无效。")
        return {key: RunReceipt(**raw) for key, raw in payload.get("receipts", {}).items()}

    def save(self, receipts: dict[str, RunReceipt]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "receipts": {key: {"receipt_id": value.receipt_id, "plugin_name": value.plugin_name, "plan_key": value.plan_key, "output": value.output, "reused": False} for key, value in sorted(receipts.items())}}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def get(self, plan_key: str) -> RunReceipt | None:
        return self.load().get(plan_key)

    def put(self, receipt: RunReceipt) -> None:
        receipts = self.load()
        existing = receipts.get(receipt.plan_key)
        if existing is not None:
            if existing == receipt:
                return
            raise RuntimeError("同一计划键已经绑定到不同执行回执。")
        receipts[receipt.plan_key] = receipt
        self.save(receipts)
