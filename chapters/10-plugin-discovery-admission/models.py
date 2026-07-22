from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PluginError(RuntimeError):
    pass


class ManifestError(PluginError):
    pass


class ScanError(PluginError):
    pass


class AdmissionError(PluginError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    entrypoint: str
    display_name: str
    risk: str
    description: str
    required_inputs: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    supports_query: bool = False
    supports_compensation: bool = False
    idempotent: bool = False

    def requires_explicit_admission(self) -> bool:
        return self.risk in {"local_write", "external_mutation", "high"}


@dataclass(frozen=True)
class ScanReport:
    plugin_dir: str
    manifest: PluginManifest | None
    fingerprint: str | None
    accepted_static: bool
    reasons: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdmissionRecord:
    name: str
    fingerprint: str
    status: str
    reason: str
    admitted_at: str


@dataclass(frozen=True)
class RunReceipt:
    receipt_id: str
    plugin_name: str
    plan_key: str
    output: dict[str, Any]
    reused: bool = False


@dataclass
class ClarificationState:
    plugin_name: str
    values: dict[str, str] = field(default_factory=dict)
