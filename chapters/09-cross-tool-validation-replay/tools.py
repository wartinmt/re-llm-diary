"""两个带持久回执的本地工具：文档工具与索引工具。"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from models import ToolReceipt, digest_text
from receipts import ReceiptStore


class ToolError(RuntimeError):
    pass


class DocumentTool:
    name = "document"

    def __init__(self, root: Path, receipts: ReceiptStore):
        self.root = root
        self.receipts = receipts

    def query(self, key: str) -> ToolReceipt | None:
        return self.receipts.get(key)

    def write(self, key: str, relative_path: str, content: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return existing
        target = (self.root / relative_path).resolve()
        if self.root.resolve() not in target.parents:
            raise ToolError("文档路径越过工具根目录。")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        receipt = ToolReceipt(
            receipt_id=f"rcpt_{uuid4().hex}", tool_name=self.name, idempotency_key=key,
            operation="write", effect_ref=str(target), outcome="applied",
            metadata={"relative_path": relative_path, "sha256": digest_text(content)},
        )
        self.receipts.save(receipt)
        return receipt

    def delete(self, key: str, relative_path: str, original_receipt_id: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return existing
        target = (self.root / relative_path).resolve()
        if self.root.resolve() not in target.parents:
            raise ToolError("文档路径越过工具根目录。")
        existed = target.exists()
        target.unlink(missing_ok=True)
        receipt = ToolReceipt(
            receipt_id=f"rcpt_{uuid4().hex}", tool_name=self.name, idempotency_key=key,
            operation="delete", effect_ref=str(target), outcome="compensated",
            metadata={"relative_path": relative_path, "existed": existed, "original_receipt_id": original_receipt_id},
        )
        self.receipts.save(receipt)
        return receipt


class IndexTool:
    name = "index"

    def __init__(self, path: Path, receipts: ReceiptStore):
        self.path = path
        self.receipts = receipts

    def query(self, key: str) -> ToolReceipt | None:
        return self.receipts.get(key)

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ToolError("索引文件损坏。") from exc
        if not isinstance(data, dict):
            raise ToolError("索引顶层必须是对象。")
        return data

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def register(self, key: str, title: str, relative_path: str, content_sha256: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return existing
        data = self._load()
        data[title] = {"path": relative_path, "sha256": content_sha256}
        self._save(data)
        receipt = ToolReceipt(
            receipt_id=f"rcpt_{uuid4().hex}", tool_name=self.name, idempotency_key=key,
            operation="register", effect_ref=f"{self.path}#{title}", outcome="applied",
            metadata={"title": title, "relative_path": relative_path, "sha256": content_sha256},
        )
        self.receipts.save(receipt)
        return receipt

    def remove(self, key: str, title: str, original_receipt_id: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return existing
        data = self._load()
        existed = title in data
        data.pop(title, None)
        self._save(data)
        receipt = ToolReceipt(
            receipt_id=f"rcpt_{uuid4().hex}", tool_name=self.name, idempotency_key=key,
            operation="remove", effect_ref=f"{self.path}#{title}", outcome="compensated",
            metadata={"title": title, "existed": existed, "original_receipt_id": original_receipt_id},
        )
        self.receipts.save(receipt)
        return receipt

    def record(self, title: str) -> dict | None:
        return self._load().get(title)
