"""Append-only task journal with a SHA-256 hash chain."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64


class JournalError(RuntimeError):
    """Base class for task journal errors."""


class JournalFormatError(JournalError):
    """The journal exists but cannot be trusted."""


class RecoveryBlocked(JournalError):
    """Automatic recovery would risk repeating an external request."""


@dataclass(frozen=True)
class JournalEvent:
    schema_version: int
    seq: int
    timestamp: str
    task_id: str
    attempt: int
    kind: str
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str

    def unsigned(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "task_id": self.task_id,
            "attempt": self.attempt,
            "kind": self.kind,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }


@dataclass(frozen=True)
class RecoveryPlan:
    task_id: str
    attempt: int
    status: str
    can_resume_without_api: bool
    reason: str


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _event_hash(unsigned: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise JournalFormatError("事件 payload 必须是 JSON 对象。")
    return payload


class TaskJournal:
    def __init__(self, path: Path):
        self.path = path
        self._events: list[JournalEvent] | None = None

    def load(self) -> list[JournalEvent]:
        if self._events is not None:
            return list(self._events)
        if not self.path.exists():
            self._events = []
            return []
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise JournalFormatError(f"无法读取任务流水账：{self.path}") from exc
        if raw and not raw.endswith(b"\n"):
            raise JournalFormatError(
                "任务流水账末尾存在未完成事件。原文件没有被覆盖；"
                "可先备份，再运行 --repair-journal。"
            )
        events: list[JournalEvent] = []
        expected_hash = ZERO_HASH
        for line_number, raw_line in enumerate(raw.splitlines(), start=1):
            if not raw_line.strip():
                raise JournalFormatError(f"第 {line_number} 行是空事件。")
            try:
                item = json.loads(raw_line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise JournalFormatError(f"第 {line_number} 行不是有效 JSON。") from exc
            if not isinstance(item, dict):
                raise JournalFormatError(f"第 {line_number} 行必须是对象。")
            try:
                event = JournalEvent(
                    schema_version=int(item["schema_version"]),
                    seq=int(item["seq"]),
                    timestamp=str(item["timestamp"]),
                    task_id=str(item["task_id"]),
                    attempt=int(item["attempt"]),
                    kind=str(item["kind"]),
                    payload=_validate_payload(item["payload"]),
                    prev_hash=str(item["prev_hash"]),
                    event_hash=str(item["event_hash"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise JournalFormatError(f"第 {line_number} 行字段不完整。") from exc
            if event.schema_version != SCHEMA_VERSION:
                raise JournalFormatError(
                    f"不支持的流水账版本：{event.schema_version!r}。"
                )
            if event.seq != line_number:
                raise JournalFormatError(
                    f"第 {line_number} 行 seq 应为 {line_number}，实际为 {event.seq}。"
                )
            if event.attempt <= 0 or not event.task_id or not event.kind:
                raise JournalFormatError(f"第 {line_number} 行的任务字段无效。")
            if event.prev_hash != expected_hash:
                raise JournalFormatError(f"第 {line_number} 行哈希链断裂。")
            calculated = _event_hash(event.unsigned())
            if calculated != event.event_hash:
                raise JournalFormatError(f"第 {line_number} 行内容哈希不匹配。")
            expected_hash = event.event_hash
            events.append(event)
        self._events = events
        return list(events)

    def append(
        self, task_id: str, attempt: int, kind: str, payload: dict[str, Any] | None = None
    ) -> JournalEvent:
        events = self.load()
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "seq": len(events) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "attempt": attempt,
            "kind": kind,
            "payload": dict(payload or {}),
            "prev_hash": events[-1].event_hash if events else ZERO_HASH,
        }
        event = JournalEvent(**unsigned, event_hash=_event_hash(unsigned))
        encoded = json.dumps(
            {**unsigned, "event_hash": event.event_hash},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self._events = None
            raise
        events.append(event)
        self._events = events
        return event

    def create_task(self, prompt: str) -> tuple[str, int]:
        if not prompt.strip():
            raise JournalError("任务内容不能为空。")
        task_id = uuid.uuid4().hex[:12]
        attempt = 1
        self.append(task_id, attempt, "task_created", {"prompt": prompt})
        return task_id, attempt

    def task_events(self, task_id: str, attempt: int | None = None) -> list[JournalEvent]:
        result = [event for event in self.load() if event.task_id == task_id]
        if attempt is not None:
            result = [event for event in result if event.attempt == attempt]
        return result

    def task_ids(self) -> list[str]:
        seen: list[str] = []
        for event in self.load():
            if event.task_id not in seen:
                seen.append(event.task_id)
        return seen

    def latest_attempt(self, task_id: str) -> int:
        events = self.task_events(task_id)
        if not events:
            raise JournalError(f"找不到任务：{task_id}")
        return max(event.attempt for event in events)

    def prompt_for(self, task_id: str) -> str:
        for event in self.task_events(task_id):
            if event.kind in {"task_created", "attempt_started"}:
                prompt = event.payload.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    return prompt
        raise JournalFormatError(f"任务 {task_id} 没有可恢复的 prompt。")

    def plan(self, task_id: str, attempt: int | None = None) -> RecoveryPlan:
        if attempt is None:
            attempt = self.latest_attempt(task_id)
        events = self.task_events(task_id, attempt)
        if not events:
            raise JournalError(f"找不到任务 {task_id} 的 attempt {attempt}。")
        kinds = [event.kind for event in events]
        if "task_completed" in kinds:
            return RecoveryPlan(task_id, attempt, "complete", True, "任务已经完成。")
        if "task_abandoned" in kinds:
            return RecoveryPlan(task_id, attempt, "abandoned", True, "该 attempt 已明确放弃。")

        sent: dict[str, JournalEvent] = {}
        closed: set[str] = set()
        for event in events:
            call_id = event.payload.get("call_id")
            if not isinstance(call_id, str):
                continue
            if event.kind == "request_sent":
                sent[call_id] = event
            elif event.kind in {"response_received", "request_failed_known"}:
                closed.add(call_id)
        open_calls = [call_id for call_id in sent if call_id not in closed]

        if "memory_committed" in kinds:
            return RecoveryPlan(
                task_id, attempt, "finish_only", True,
                "正式记忆已经保存，只需补写完成事件。",
            )
        if "final_answer_ready" in kinds:
            return RecoveryPlan(
                task_id, attempt, "local_commit", True,
                "完整最终答案已写入流水账，可以只做本地记忆提交。",
            )
        if open_calls:
            return RecoveryPlan(
                task_id, attempt, "remote_unknown", False,
                "请求已经发出，但没有可信的完成回执；自动重试可能造成重复调用。",
            )
        primary_responses = [
            event for event in events
            if event.kind == "response_received" and event.payload.get("role") == "primary"
        ]
        if primary_responses:
            return RecoveryPlan(
                task_id, attempt, "local_finalize", True,
                "主回答已经完整落盘，可以跳过可选验证并在本地完成。",
            )
        if "task_created" in kinds or "attempt_started" in kinds:
            return RecoveryPlan(
                task_id, attempt, "safe_to_send", False,
                "还没有请求发送记录；可以由用户决定是否继续发送。",
            )
        return RecoveryPlan(task_id, attempt, "inspect", False, "状态无法自动归类，需要人工检查。")

    def pending_plans(self) -> list[RecoveryPlan]:
        plans: list[RecoveryPlan] = []
        for task_id in self.task_ids():
            plan = self.plan(task_id)
            if plan.status not in {"complete", "abandoned"}:
                plans.append(plan)
        return plans

    def authorize_retry(self, task_id: str, confirmation: str) -> tuple[int, str]:
        if confirmation != "CONFIRM":
            raise RecoveryBlocked("重试必须显式输入 CONFIRM。")
        current = self.latest_attempt(task_id)
        plan = self.plan(task_id, current)
        if plan.status != "remote_unknown":
            raise RecoveryBlocked("只有远端结果未知的任务才需要创建新 attempt。")
        prompt = self.prompt_for(task_id)
        self.append(task_id, current, "retry_authorized", {"reason": "user_confirmed"})
        self.append(task_id, current, "task_abandoned", {"reason": "superseded_by_retry"})
        new_attempt = current + 1
        self.append(task_id, new_attempt, "attempt_started", {"prompt": prompt})
        return new_attempt, prompt

    def repair_trailing_partial(self) -> Path | None:
        if not self.path.exists():
            self._events = []
            return None
        raw = self.path.read_bytes()
        if not raw or raw.endswith(b"\n"):
            self._events = None
            self.load()
            return None
        last_newline = raw.rfind(b"\n")
        clean = raw[: last_newline + 1] if last_newline >= 0 else b""
        backup = self.path.with_suffix(self.path.suffix + ".partial.bak")
        counter = 1
        while backup.exists():
            backup = self.path.with_suffix(self.path.suffix + f".partial.{counter}.bak")
            counter += 1
        backup.write_bytes(raw)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(clean)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        self._events = None
        self.load()
        return backup

    def replay_lines(self, task_id: str) -> list[str]:
        lines: list[str] = []
        for event in self.task_events(task_id):
            detail = ""
            if event.kind == "request_sent":
                detail = f" {event.payload.get('role')}->{event.payload.get('provider')}"
            elif event.kind == "response_received":
                detail = f" {event.payload.get('role')}<-{event.payload.get('provider')}"
            lines.append(
                f"#{event.seq:04d} attempt={event.attempt} {event.kind}{detail} "
                f"hash={event.event_hash[:10]}"
            )
        if not lines:
            raise JournalError(f"找不到任务：{task_id}")
        return lines
