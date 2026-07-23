"""两个带持久回执的本地工具：文档工具与索引工具。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from models import ToolReceipt, digest_text
from receipts import ReceiptStore


class ToolError(RuntimeError):
    pass


def resolve_document_target(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ToolError("文档路径必须是非空字符串。")
    target = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if resolved_root not in target.parents:
        raise ToolError("文档路径越过工具根目录。")
    return target


def _atomic_json_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


class DocumentTool:
    name = "document"

    def __init__(self, root: Path, receipts: ReceiptStore):
        self.root = root
        self.receipts = receipts

    def query(self, key: str) -> ToolReceipt | None:
        return self.receipts.get(key)

    def require_write_receipt(
        self, receipt: ToolReceipt, key: str, relative_path: str, content: str
    ) -> ToolReceipt:
        target = resolve_document_target(self.root, relative_path)
        if (
            receipt.tool_name != self.name
            or receipt.idempotency_key != key
            or receipt.operation != "write"
            or receipt.outcome != "applied"
            or receipt.effect_ref != str(target)
            or receipt.metadata.get("relative_path") != relative_path
            or receipt.metadata.get("sha256") != digest_text(content)
        ):
            raise ToolError("同一幂等键已经绑定到不同的文档写入效果。")
        return receipt

    def write(self, key: str, relative_path: str, content: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return self.require_write_receipt(existing, key, relative_path, content)
        target = resolve_document_target(self.root, relative_path)
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
        target = resolve_document_target(self.root, relative_path)
        if existing:
            if (
                existing.tool_name != self.name
                or existing.idempotency_key != key
                or existing.operation != "delete"
                or existing.outcome != "compensated"
                or existing.effect_ref != str(target)
                or existing.metadata.get("relative_path") != relative_path
                or existing.metadata.get("original_receipt_id")
                != original_receipt_id
            ):
                raise ToolError("同一幂等键已经绑定到不同的文档删除效果。")
            return existing
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
        _atomic_json_write(self.path, data)

    def require_register_receipt(
        self,
        receipt: ToolReceipt,
        key: str,
        title: str,
        relative_path: str,
        content_sha256: str,
    ) -> ToolReceipt:
        if (
            receipt.tool_name != self.name
            or receipt.idempotency_key != key
            or receipt.operation != "register"
            or receipt.outcome != "applied"
            or receipt.effect_ref != f"{self.path}#{title}"
            or receipt.metadata.get("title") != title
            or receipt.metadata.get("relative_path") != relative_path
            or receipt.metadata.get("sha256") != content_sha256
        ):
            raise ToolError("同一幂等键已经绑定到不同的索引登记效果。")
        return receipt

    def register(self, key: str, title: str, relative_path: str, content_sha256: str) -> ToolReceipt:
        existing = self.query(key)
        if existing:
            return self.require_register_receipt(
                existing, key, title, relative_path, content_sha256
            )
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
            if (
                existing.tool_name != self.name
                or existing.idempotency_key != key
                or existing.operation != "remove"
                or existing.outcome != "compensated"
                or existing.effect_ref != f"{self.path}#{title}"
                or existing.metadata.get("title") != title
                or existing.metadata.get("original_receipt_id")
                != original_receipt_id
            ):
                raise ToolError("同一幂等键已经绑定到不同的索引删除效果。")
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
