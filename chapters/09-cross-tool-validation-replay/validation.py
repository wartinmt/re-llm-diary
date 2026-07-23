"""后置验证：验证现实状态，而不是只相信工具返回值。"""
from __future__ import annotations

from pathlib import Path

from models import ValidationResult, WorkflowPlan, digest_text
from tools import IndexTool, ToolError, resolve_document_target


def validate_document(root: Path, plan: WorkflowPlan) -> ValidationResult:
    try:
        target = resolve_document_target(root, plan.document_path)
    except ToolError:
        return ValidationResult(
            False,
            {"path_within_root": False, "exists": False, "content_sha256": False},
            "文档路径越过工具根目录。",
        )
    exists = target.is_file()
    actual = digest_text(target.read_text(encoding="utf-8")) if exists else ""
    checks = {
        "path_within_root": True,
        "exists": exists,
        "content_sha256": actual == plan.content_sha256,
    }
    ok = all(checks.values())
    return ValidationResult(ok, checks, "文档符合计划。" if ok else "文档不存在或内容哈希不匹配。")


def validate_index(index: IndexTool, root: Path, plan: WorkflowPlan) -> ValidationResult:
    record = index.record(plan.title)
    try:
        target = resolve_document_target(root, plan.document_path)
    except ToolError:
        return ValidationResult(
            False,
            {
                "path_within_root": False,
                "record_exists": record is not None,
                "path_matches": False,
                "planned_hash_matches": False,
                "disk_hash_matches": False,
            },
            "索引中的文档路径越过工具根目录。",
        )
    actual = digest_text(target.read_text(encoding="utf-8")) if target.is_file() else ""
    checks = {
        "path_within_root": True,
        "record_exists": record is not None,
        "path_matches": bool(record) and record.get("path") == plan.document_path,
        "planned_hash_matches": bool(record) and record.get("sha256") == plan.content_sha256,
        "disk_hash_matches": bool(record) and record.get("sha256") == actual,
    }
    ok = all(checks.values())
    return ValidationResult(ok, checks, "索引与文档组合一致。" if ok else "索引与文档组合不一致。")
