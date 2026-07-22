from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from models import AdmissionError, ScanReport
from registry import AdmissionStore


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = str(path.stat().st_size)
    return result


def run_method(report: ScanReport, method: str, workspace: Path, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    if not report.manifest:
        raise AdmissionError("缺少有效 manifest。")
    source = Path(report.plugin_dir) / report.manifest.entrypoint
    runner = Path(__file__).resolve().parent / "plugin_runner.py"
    allowed_env = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed_env}
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(runner), "--source", str(source), "--method", method, "--workspace", str(workspace), "--payload", json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
        raise AdmissionError(f"{method} 失败：{message}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AdmissionError(f"{method} 没有返回 JSON。") from exc
    if not isinstance(result, dict):
        raise AdmissionError(f"{method} 返回值必须是对象。")
    return result


def evaluate_admission(report: ScanReport, store: AdmissionStore, confirmation: str | None = None) -> str:
    if not report.accepted_static or not report.manifest or not report.fingerprint:
        reason = "; ".join(report.reasons) or "静态检查未通过。"
        if report.manifest and report.fingerprint:
            store.record(report.manifest.name, report.fingerprint, "rejected", reason)
        return "rejected"
    manifest = report.manifest
    with tempfile.TemporaryDirectory(prefix="re-llm-ch10-admit-") as tmp:
        workspace = Path(tmp)
        before = snapshot(workspace)
        run_method(report, "probe", workspace)
        after_probe = snapshot(workspace)
        if after_probe != before:
            store.record(manifest.name, report.fingerprint, "rejected", "probe 产生了文件副作用。")
            return "rejected"
        run_method(report, "preview", workspace, {key: f"sample-{key}" for key in manifest.required_inputs})
        after_preview = snapshot(workspace)
        if after_preview != before:
            store.record(manifest.name, report.fingerprint, "rejected", "preview 产生了文件副作用。")
            return "rejected"
    if manifest.requires_explicit_admission() and confirmation != "CONFIRM":
        store.record(manifest.name, report.fingerprint, "pending_confirmation", "副作用工具需要显式准入。")
        return "pending_confirmation"
    store.record(manifest.name, report.fingerprint, "admitted", "静态检查、probe 与 preview 均通过。")
    return "admitted"
