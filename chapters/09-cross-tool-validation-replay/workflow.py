"""证据驱动的跨工具执行、恢复、验证与逆序回滚。"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from journal import EventJournal
from models import StepPlan, WorkflowPlan, WorkflowResult, digest_text
from receipts import ReceiptStore
from tools import DocumentTool, IndexTool
from validation import validate_document, validate_index


class SimulatedCrash(RuntimeError):
    pass


class PlanStore:
    def __init__(self, root: Path):
        self.root = root

    def path_for(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def save(self, plan: WorkflowPlan) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(plan.workflow_id)
        encoded = json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("已存在的执行计划不可变更。")
        path.write_text(encoded, encoding="utf-8")

    def load(self, workflow_id: str) -> WorkflowPlan:
        return WorkflowPlan.from_dict(json.loads(self.path_for(workflow_id).read_text(encoding="utf-8")))


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
        workflow_id = workflow_id or f"wf_{uuid4().hex[:12]}"
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

    def execute(self, workflow_id: str, *, wrong_index_hash: str | None = None, crash_after_document_tool: bool = False) -> WorkflowResult:
        plan = self.plans.load(workflow_id)
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
        plan = self.plans.load(workflow_id)
        compensated: list[str] = []
        # 逆序：先索引，再文档。
        index_payload = self._receipt_for_step(workflow_id, "register_index")
        if index_payload:
            key = f"{workflow_id}:compensate:register_index"
            self.journal.append(workflow_id, "compensation_intent_saved", {"step_id": "register_index", "key": key})
            receipt = self.index_tool.remove(key, plan.title, index_payload["receipt_id"])
            self.journal.append(workflow_id, "compensation_receipt_saved", {"step_id": "register_index", "receipt_id": receipt.receipt_id})
            compensated.append("register_index")
        doc_payload = self._receipt_for_step(workflow_id, "write_document")
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
