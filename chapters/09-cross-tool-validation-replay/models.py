"""第 09 章的数据模型。只使用 Python 标准库。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StepPlan:
    step_id: str
    tool_name: str
    idempotency_key: str
    depends_on: tuple[str, ...]
    expected: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        return data


@dataclass(frozen=True)
class WorkflowPlan:
    workflow_id: str
    title: str
    document_path: str
    content: str
    content_sha256: str
    steps: tuple[StepPlan, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "title": self.title,
            "document_path": self.document_path,
            "content": self.content,
            "content_sha256": self.content_sha256,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowPlan":
        steps = tuple(
            StepPlan(
                step_id=item["step_id"],
                tool_name=item["tool_name"],
                idempotency_key=item["idempotency_key"],
                depends_on=tuple(item.get("depends_on", [])),
                expected=dict(item.get("expected", {})),
            )
            for item in data["steps"]
        )
        return cls(
            workflow_id=data["workflow_id"],
            title=data["title"],
            document_path=data["document_path"],
            content=data["content"],
            content_sha256=data["content_sha256"],
            steps=steps,
        )

    def plan_hash(self) -> str:
        return digest_text(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class ToolReceipt:
    receipt_id: str
    tool_name: str
    idempotency_key: str
    operation: str
    effect_ref: str
    outcome: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolReceipt":
        return cls(
            receipt_id=data["receipt_id"],
            tool_name=data["tool_name"],
            idempotency_key=data["idempotency_key"],
            operation=data["operation"],
            effect_ref=data["effect_ref"],
            outcome=data["outcome"],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    checks: dict[str, bool]
    reason: str


@dataclass(frozen=True)
class WorkflowResult:
    workflow_id: str
    status: str
    completed_steps: tuple[str, ...]
    message: str
