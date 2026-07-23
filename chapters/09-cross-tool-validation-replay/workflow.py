"""证据驱动的跨工具执行、恢复、验证与逆序回滚。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from journal import EventJournal
from models import StepPlan, WorkflowPlan, WorkflowResult, digest_text
from receipts import ReceiptStore
from tools import DocumentTool, IndexTool, resolve_document_target
from validation import validate_document, validate_index


class SimulatedCrash(RuntimeError):
    pass


_WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


def validate_workflow_id(workflow_id: str) -> str:
    if not isinstance(workflow_id, str) or not _WORKFLOW_ID_PATTERN.fullmatch(
        workflow_id
    ):
        raise RuntimeError(
            "workflow_id 必须是 3-128 位字母、数字、点、下划线或连字符。"
        )
    return workflow_id


class PlanStore:
    def __init__(self, root: Path):
        self.root = root

    def path_for(self, workflow_id: str) -> Path:
        clean = validate_workflow_id(workflow_id)
        root = self.root.resolve()
        path = (root / f"{clean}.json").resolve()
        if path.parent != root:
            raise RuntimeError("执行计划路径越过计划目录。")
        return path

    def save(self, plan: WorkflowPlan) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(plan.workflow_id)
        encoded = json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("已存在的执行计划不可变更。")
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

    def load(self, workflow_id: str) -> WorkflowPlan:
        clean = validate_workflow_id(workflow_id)
        plan = WorkflowPlan.from_dict(
            json.loads(self.path_for(clean).read_text(encoding="utf-8"))
        )
        if plan.workflow_id != clean:
            raise RuntimeError("执行计划中的 workflow_id 与文件名不一致。")
        return plan


class CrossToolRuntime:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.documents_root = data_root / "documents"
        self.index_path = data_root / "index.json"
        self.journal = EventJournal(data_root / "workflow_journal.jsonl")
        self.plans = PlanStore(data_root / "plans")
        self.document_receipts = ReceiptStore(data_root / "document_receipts.json")
        self.index_receipts = ReceiptStore(data_root / "index_receipts.json")
        self.document_tool = DocumentTool(self.documents_root, self.document_receipts)
        self.index_tool = IndexTool(self.index_path, self.index_receipts)

    def create_plan(self, title: str, document_path: str, content: str, workflow_id: str | None = None) -> WorkflowPlan:
        workflow_id = validate_workflow_id(
            workflow_id or f"wf_{uuid4().hex[:12]}"
        )
        content_hash = digest_text(content)
        steps = (
            StepPlan("write_document", "document", f"{workflow_id}:write_document", (), {"path": document_path, "sha256": content_hash}),
            StepPlan("register_index", "index", f"{workflow_id}:register_index", ("write_document",), {"title": title, "path": document_path, "sha256": content_hash}),
        )
        plan = WorkflowPlan(workflow_id, title, document_path, content, content_hash, steps)
        self.plans.save(plan)
        if not self.journal.for_workflow(workflow_id):
            self.journal.append(workflow_id, "workflow_planned", {"plan_hash": plan.plan_hash(), "steps": [s.step_id for s in steps]})
        return plan

    def _events(self, workflow_id: str):
        return self.journal.for_workflow(workflow_id)

    def _receipt_for_step(self, workflow_id: str, step_id: str):
        for event in reversed(self._events(workflow_id)):
            if event["event_type"] in {"step_receipt_saved", "step_receipt_recovered"} and event["payload"].get("step_id") == step_id:
                return event["payload"]
        return None

    def _verified_plan(self, workflow_id: str) -> WorkflowPlan:
        clean = validate_workflow_id(workflow_id)
        plan = self.plans.load(clean)
        planned = [
            event
            for event in self._events(clean)
            if event["event_type"] == "workflow_planned"
        ]
        if len(planned) != 1:
            raise RuntimeError("工作流必须且只能有一个 workflow_planned 事件。")
        if planned[0]["payload"].get("plan_hash") != plan.plan_hash():
            raise RuntimeError("执行计划哈希与工作流流水账不匹配。")
        return plan

    def _recover_step_receipt(
        self, plan: WorkflowPlan, step_id: str
    ) -> dict | None:
        step = next(item for item in plan.steps if item.step_id == step_id)
        if step.tool_name == "document":
            receipt = self.document_tool.query(step.idempotency_key)
            if receipt is not None:
                self.document_tool.require_write_receipt(
                    receipt,
                    step.idempotency_key,
                    plan.document_path,
                    plan.content,
                )
        elif step.tool_name == "index":
            receipt = self.index_tool.query(step.idempotency_key)
            if receipt is not None:
                self.index_tool.require_register_receipt(
                    receipt,
                    step.idempotency_key,
                    plan.title,
                    plan.document_path,
                    plan.content_sha256,
                )
        else:
            raise RuntimeError(f"未知计划工具：{step.tool_name}")
        if receipt is None:
            return None
        payload = {
            "step_id": step.step_id,
            "receipt_id": receipt.receipt_id,
            "key": step.idempotency_key,
        }
        self.journal.append(plan.workflow_id, "step_receipt_recovered", payload)
        return payload

    def execute(self, workflow_id: str, *, wrong_index_hash: str | None = None, crash_after_document_tool: bool = False) -> WorkflowResult:
        plan = self._verified_plan(workflow_id)
        completed: list[str] = []

        # Step 1: document
        step = plan.steps[0]
        payload = self._receipt_for_step(workflow_id, step.step_id)
        if payload is None:
            self.journal.append(workflow_id, "step_intent_saved", {"step_id": step.step_id, "key": step.idempotency_key})
            receipt = self.document_tool.query(step.idempotency_key)
            recovered = receipt is not None
            if receipt is None:
                receipt = self.document_tool.write(step.idempotency_key, plan.document_path, plan.content)
            else:
                self.document_tool.require_write_receipt(
                    receipt,
                    step.idempotency_key,
                    plan.document_path,
                    plan.content,
                )
            if crash_after_document_tool:
                raise SimulatedCrash("模拟：工具已完成，但 Runtime 尚未保存回执。")
            self.journal.append(workflow_id, "step_receipt_recovered" if recovered else "step_receipt_saved", {"step_id": step.step_id, "receipt_id": receipt.receipt_id, "key": step.idempotency_key})
        validation = validate_document(self.documents_root, plan)
        self.journal.append(workflow_id, "step_validated" if validation.ok else "validation_failed", {"step_id": step.step_id, "checks": validation.checks, "reason": validation.reason})
        if not validation.ok:
            return WorkflowResult(workflow_id, "validation_failed", tuple(completed), validation.reason)
        completed.append(step.step_id)

        # Step 2: index
        step = plan.steps[1]
        payload = self._receipt_for_step(workflow_id, step.step_id)
        if payload is None:
            self.journal.append(workflow_id, "step_intent_saved", {"step_id": step.step_id, "key": step.idempotency_key})
            receipt = self.index_tool.query(step.idempotency_key)
            recovered = receipt is not None
            if receipt is None:
                receipt = self.index_tool.register(step.idempotency_key, plan.title, plan.document_path, wrong_index_hash or plan.content_sha256)
            else:
                self.index_tool.require_register_receipt(
                    receipt,
                    step.idempotency_key,
                    plan.title,
                    plan.document_path,
                    wrong_index_hash or plan.content_sha256,
                )
            self.journal.append(workflow_id, "step_receipt_recovered" if recovered else "step_receipt_saved", {"step_id": step.step_id, "receipt_id": receipt.receipt_id, "key": step.idempotency_key})
        validation = validate_index(self.index_tool, self.documents_root, plan)
        self.journal.append(workflow_id, "step_validated" if validation.ok else "validation_failed", {"step_id": step.step_id, "checks": validation.checks, "reason": validation.reason})
        if not validation.ok:
            return WorkflowResult(workflow_id, "validation_failed", tuple(completed), validation.reason)
        completed.append(step.step_id)

        if not any(e["event_type"] == "workflow_completed" for e in self._events(workflow_id)):
            self.journal.append(workflow_id, "workflow_completed", {"completed_steps": completed})
        return WorkflowResult(workflow_id, "complete", tuple(completed), "跨工具工作流已通过组合验证。")

    def rollback(self, workflow_id: str) -> WorkflowResult:
        plan = self._verified_plan(workflow_id)
        compensated: list[str] = []
        # 逆序：先索引，再文档。
        index_payload = self._receipt_for_step(workflow_id, "register_index")
        if index_payload is None:
            index_payload = self._recover_step_receipt(plan, "register_index")
        if index_payload is None and self.index_tool.record(plan.title) is not None:
            raise RuntimeError(
                "索引现实状态存在，但没有可信原动作回执；拒绝错误标记为已回滚。"
            )
        if index_payload:
            key = f"{workflow_id}:compensate:register_index"
            self.journal.append(workflow_id, "compensation_intent_saved", {"step_id": "register_index", "key": key})
            receipt = self.index_tool.remove(key, plan.title, index_payload["receipt_id"])
            self.journal.append(workflow_id, "compensation_receipt_saved", {"step_id": "register_index", "receipt_id": receipt.receipt_id})
            compensated.append("register_index")
        doc_payload = self._receipt_for_step(workflow_id, "write_document")
        if doc_payload is None:
            doc_payload = self._recover_step_receipt(plan, "write_document")
        document_target = resolve_document_target(
            self.documents_root, plan.document_path
        )
        if doc_payload is None and document_target.exists():
            raise RuntimeError(
                "文档现实状态存在，但没有可信原动作回执；拒绝错误标记为已回滚。"
            )
        if doc_payload:
            key = f"{workflow_id}:compensate:write_document"
            self.journal.append(workflow_id, "compensation_intent_saved", {"step_id": "write_document", "key": key})
            receipt = self.document_tool.delete(key, plan.document_path, doc_payload["receipt_id"])
            self.journal.append(workflow_id, "compensation_receipt_saved", {"step_id": "write_document", "receipt_id": receipt.receipt_id})
            compensated.append("write_document")
        self.journal.append(workflow_id, "workflow_rolled_back", {"compensated_steps": compensated})
        return WorkflowResult(workflow_id, "rolled_back", tuple(compensated), "已按依赖逆序执行补偿。")

    def replay(self, workflow_id: str) -> list[dict]:
        return self._events(workflow_id)
