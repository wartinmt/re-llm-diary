from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from models import AdmissionRecord, ScanReport


class AdmissionStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, AdmissionRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("records"), dict):
            raise RuntimeError("准入记录格式无效。")
        out: dict[str, AdmissionRecord] = {}
        for name, raw in payload["records"].items():
            if not isinstance(raw, dict):
                raise RuntimeError("准入记录条目无效。")
            out[name] = AdmissionRecord(**raw)
        return out

    def save(self, records: dict[str, AdmissionRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "records": {name: asdict(record) for name, record in sorted(records.items())}}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def record(self, name: str, fingerprint: str, status: str, reason: str) -> AdmissionRecord:
        records = self.load()
        record = AdmissionRecord(name, fingerprint, status, reason, datetime.now(timezone.utc).isoformat())
        records[name] = record
        self.save(records)
        return record

    def status_for(self, report: ScanReport) -> str:
        if not report.manifest or not report.fingerprint or not report.accepted_static:
            return "rejected"
        record = self.load().get(report.manifest.name)
        if not record:
            return "unreviewed"
        if record.fingerprint != report.fingerprint:
            return "stale"
        return record.status
