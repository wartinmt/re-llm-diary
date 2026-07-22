from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import ManifestError, PluginManifest

ALLOWED_RISKS = {"read_only", "local_write", "external_mutation", "high"}
ALLOWED_CAPABILITIES = {"probe", "preview", "execute", "query", "compensate"}


def _expect_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"manifest 字段 {key!r} 必须是非空字符串。")
    return value.strip()


def _expect_strings(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ManifestError(f"manifest 字段 {key!r} 必须是字符串数组。")
    return tuple(item.strip() for item in value)


def load_manifest(path: Path) -> PluginManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"无法读取 manifest：{path}") from exc
    if not isinstance(payload, dict):
        raise ManifestError("manifest 顶层必须是对象。")
    name = _expect_string(payload, "name")
    version = _expect_string(payload, "version")
    entrypoint = _expect_string(payload, "entrypoint")
    display_name = _expect_string(payload, "display_name")
    risk = _expect_string(payload, "risk")
    description = _expect_string(payload, "description")
    if risk not in ALLOWED_RISKS:
        raise ManifestError(f"不支持的 risk：{risk}")
    capabilities = _expect_strings(payload, "capabilities")
    unknown = sorted(set(capabilities) - ALLOWED_CAPABILITIES)
    if unknown:
        raise ManifestError(f"不支持的 capability：{', '.join(unknown)}")
    required_inputs = _expect_strings(payload, "required_inputs")
    if len(set(required_inputs)) != len(required_inputs):
        raise ManifestError("required_inputs 不能重复。")
    if "/" in entrypoint or "\\" in entrypoint or entrypoint.startswith("."):
        raise ManifestError("entrypoint 只能是插件目录内的 Python 文件名。")
    if not entrypoint.endswith(".py"):
        raise ManifestError("entrypoint 必须以 .py 结尾。")
    manifest = PluginManifest(
        name=name,
        version=version,
        entrypoint=entrypoint,
        display_name=display_name,
        risk=risk,
        description=description,
        required_inputs=required_inputs,
        capabilities=capabilities,
        supports_query=bool(payload.get("supports_query", False)),
        supports_compensation=bool(payload.get("supports_compensation", False)),
        idempotent=bool(payload.get("idempotent", False)),
    )
    if manifest.supports_query and "query" not in capabilities:
        raise ManifestError("supports_query=true 时 capabilities 必须包含 query。")
    if manifest.supports_compensation and "compensate" not in capabilities:
        raise ManifestError("supports_compensation=true 时 capabilities 必须包含 compensate。")
    if manifest.risk != "read_only" and "execute" not in capabilities:
        raise ManifestError("会产生副作用的工具必须声明 execute。")
    return manifest
