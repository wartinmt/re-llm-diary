from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from admission import run_method
from models import ClarificationState, RunReceipt, ScanReport
from receipts import ReceiptStore, stable_plan_key
from registry import AdmissionStore


class PluginRuntime:
    def __init__(self, admission_store: AdmissionStore, receipt_store: ReceiptStore, workspace: Path):
        self.admission_store = admission_store
        self.receipt_store = receipt_store
        self.workspace = workspace

    def next_question(self, report: ScanReport, state: ClarificationState) -> str | None:
        if not report.manifest:
            return None
        for key in report.manifest.required_inputs:
            if not state.values.get(key, "").strip():
                labels = {"title": "笔记标题是什么？", "directory": "要保存到哪个目录？", "query": "要查询什么内容？"}
                return labels.get(key, f"请提供 {key}。")
        return None

    def provide(self, state: ClarificationState, key: str, value: str) -> None:
        state.values[key] = value.strip()

    def execute(self, report: ScanReport, values: dict[str, str]) -> RunReceipt:
        if not report.manifest or not report.fingerprint:
            raise RuntimeError("插件扫描结果无效。")
        status = self.admission_store.status_for(report)
        if status != "admitted":
            raise RuntimeError(f"插件当前不可执行：{status}")
        missing = [key for key in report.manifest.required_inputs if not values.get(key, "").strip()]
        if missing:
            raise RuntimeError(f"缺少输入：{missing[0]}")
        plan_key = stable_plan_key(report.manifest.name, values)
        existing = self.receipt_store.get(plan_key)
        if existing:
            return RunReceipt(existing.receipt_id, existing.plugin_name, existing.plan_key, existing.output, True)
        method = "preview" if report.manifest.risk == "read_only" else "execute"
        output = run_method(report, method, self.workspace, values)
        receipt_id = "rcpt_" + hashlib.sha256((report.manifest.name + plan_key).encode("utf-8")).hexdigest()[:16]
        receipt = RunReceipt(receipt_id, report.manifest.name, plan_key, output, False)
        self.receipt_store.put(receipt)
        return receipt
