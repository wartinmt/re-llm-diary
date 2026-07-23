from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from models import AdmissionError, ScanReport
from registry import AdmissionStore
from scanner import fingerprint_files


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = f"symlink:{os.readlink(path)}"
        elif path.is_dir():
            result[relative + "/"] = "directory"
        elif path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def require_current_fingerprint(report: ScanReport) -> None:
    if not report.manifest:
        raise AdmissionError("缺少有效 manifest。")
    plugin_dir = Path(report.plugin_dir)
    manifest_path = plugin_dir / "plugin.json"
    source = plugin_dir / report.manifest.entrypoint
    if (
        not report.fingerprint
        or plugin_dir.is_symlink()
        or manifest_path.is_symlink()
        or source.is_symlink()
    ):
        raise AdmissionError("插件路径或扫描指纹无效，请重新发现和检查。")
    try:
        current_fingerprint = fingerprint_files(manifest_path, source)
    except OSError as exc:
        raise AdmissionError("无法在执行前重新计算插件指纹。") from exc
    if current_fingerprint != report.fingerprint:
        raise AdmissionError("manifest 或入口源码已变化，请重新检查和准入。")


def run_method(report: ScanReport, method: str, workspace: Path, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    require_current_fingerprint(report)
    assert report.manifest is not None
    plugin_dir = Path(report.plugin_dir)
    source = plugin_dir / report.manifest.entrypoint
    runner = Path(__file__).resolve().parent / "plugin_runner.py"
    workspace.mkdir(parents=True, exist_ok=True)
    allowed_env = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed_env}
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(workspace)
    env["USERPROFILE"] = str(workspace)
    env["TMP"] = str(workspace)
    env["TEMP"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(runner), "--source", str(source), "--method", method, "--workspace", str(workspace), "--payload", json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=env,
        cwd=workspace,
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
