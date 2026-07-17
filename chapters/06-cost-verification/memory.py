"""Reliable local conversation storage using only the Python standard library."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ALLOWED_ROLES = {"user", "assistant"}


class MemoryErrorBase(RuntimeError):
    """Base class for chapter storage errors."""


class MemoryFormatError(MemoryErrorBase):
    """The archive exists but is not in a supported format."""


@dataclass
class ConversationStore:
    path: Path

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MemoryFormatError(
                f"无法读取记忆文件：{self.path}\n"
                "原文件没有被覆盖。可先将它改名备份，再重新启动。"
            ) from exc
        return self._validate(payload)

    def save(self, messages: list[dict[str, str]]) -> None:
        clean = self._validate_messages(messages)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "messages": clean,
        }
        self._atomic_write(payload)

    def forget(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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

    def _validate(self, payload: Any) -> list[dict[str, str]]:
        if not isinstance(payload, dict):
            raise MemoryFormatError("记忆文件顶层必须是 JSON 对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise MemoryFormatError(
                f"不支持的记忆格式版本：{payload.get('schema_version')!r}"
            )
        return self._validate_messages(payload.get("messages"))

    @staticmethod
    def _validate_messages(messages: Any) -> list[dict[str, str]]:
        if not isinstance(messages, list):
            raise MemoryFormatError("messages 必须是数组。")
        clean: list[dict[str, str]] = []
        for index, item in enumerate(messages):
            if not isinstance(item, dict):
                raise MemoryFormatError(f"第 {index + 1} 条消息不是对象。")
            role = item.get("role")
            content = item.get("content")
            if role not in ALLOWED_ROLES:
                raise MemoryFormatError(f"第 {index + 1} 条消息的 role 不受支持。")
            if not isinstance(content, str) or not content.strip():
                raise MemoryFormatError(f"第 {index + 1} 条消息的 content 无效。")
            clean.append({"role": role, "content": content})
        return clean
