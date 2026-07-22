from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from manifest import load_manifest
from models import ManifestError, ScanReport

DANGEROUS_IMPORTS = {"subprocess", "socket", "requests", "urllib", "http", "ftplib", "paramiko"}
DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__", "os.system", "os.popen"}


def fingerprint_files(manifest_path: Path, source_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (manifest_path, source_path):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def scan_plugin(plugin_dir: Path) -> ScanReport:
    manifest_path = plugin_dir / "plugin.json"
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        return ScanReport(str(plugin_dir), None, None, False, (str(exc),))
    source_path = plugin_dir / manifest.entrypoint
    if not source_path.is_file():
        return ScanReport(str(plugin_dir), manifest, None, False, (f"入口文件不存在：{source_path.name}",))
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return ScanReport(str(plugin_dir), manifest, None, False, (f"无法解析入口源码：{exc}",))
    methods: set[str] = set()
    imports: set[str] = set()
    reasons: list[str] = []
    found_class = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ToolPlugin":
            found_class = True
            methods.update(item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
        elif isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            call = _call_name(node)
            if call in DANGEROUS_CALLS:
                reasons.append(f"发现禁止调用：{call}")
    if not found_class:
        reasons.append("入口源码缺少 ToolPlugin 类。")
    required_methods = set(manifest.capabilities)
    missing = sorted(required_methods - methods)
    if missing:
        reasons.append(f"声明的方法未实现：{', '.join(missing)}")
    if manifest.supports_query and "query" not in methods:
        reasons.append("manifest 声明支持 query，但源码没有 query。")
    if manifest.supports_compensation and "compensate" not in methods:
        reasons.append("manifest 声明支持 compensate，但源码没有 compensate。")
    bad_imports = sorted(imports & DANGEROUS_IMPORTS)
    if bad_imports:
        reasons.append(f"发现禁止导入：{', '.join(bad_imports)}")
    if manifest.risk == "read_only" and ("execute" in methods or "compensate" in methods):
        reasons.append("read_only 工具不应实现 execute 或 compensate。")
    try:
        fp = fingerprint_files(manifest_path, source_path)
    except OSError as exc:
        return ScanReport(str(plugin_dir), manifest, None, False, (f"无法计算指纹：{exc}",), tuple(sorted(methods)), tuple(sorted(imports)))
    return ScanReport(str(plugin_dir), manifest, fp, not reasons, tuple(reasons), tuple(sorted(methods)), tuple(sorted(imports)))


def discover_plugins(root: Path) -> list[ScanReport]:
    if not root.exists():
        return []
    reports = [scan_plugin(path) for path in sorted(root.iterdir()) if path.is_dir()]
    return reports
