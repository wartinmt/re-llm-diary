from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

from admission import evaluate_admission
from models import ClarificationState
from receipts import ReceiptStore
from registry import AdmissionStore
from runtime import PluginRuntime
from scanner import discover_plugins, scan_plugin

ROOT = Path(__file__).resolve().parent


def stores(data_dir: Path):
    return AdmissionStore(data_dir / "admissions.json"), ReceiptStore(data_dir / "receipts.json")


def demo_discovery() -> None:
    reports = discover_plugins(ROOT / "plugins")
    for report in reports:
        name = report.manifest.name if report.manifest else Path(report.plugin_dir).name
        print(f"{name}: {'static_ok' if report.accepted_static else 'rejected'}")
        for reason in report.reasons:
            print(f"  - {reason}")


def demo_admission() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"; store, _ = stores(data)
        safe = scan_plugin(ROOT / "plugins" / "safe_lookup")
        note = scan_plugin(ROOT / "plugins" / "local_note")
        bad = scan_plugin(ROOT / "plugins" / "bad_probe")
        print("safe_lookup:", evaluate_admission(safe, store))
        print("local_note without confirmation:", evaluate_admission(note, store))
        print("local_note with confirmation:", evaluate_admission(note, store, "CONFIRM"))
        print("bad_probe:", evaluate_admission(bad, store))


def demo_clarification() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); data = root / "data"; workspace = root / "workspace"
        store, receipts = stores(data)
        report = scan_plugin(ROOT / "plugins" / "local_note")
        evaluate_admission(report, store, "CONFIRM")
        runtime = PluginRuntime(store, receipts, workspace)
        state = ClarificationState("local_note")
        print(runtime.next_question(report, state))
        runtime.provide(state, "title", "本周回顾")
        print(runtime.next_question(report, state))
        runtime.provide(state, "directory", "notes")
        first = runtime.execute(report, state.values)
        second = runtime.execute(report, state.values)
        print("first receipt:", first.receipt_id, "reused=", first.reused)
        print("second receipt:", second.receipt_id, "reused=", second.reused)
        print("files:", len(list(workspace.rglob("*.md"))))


def demo_stale() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); copy = root / "plugin"; shutil.copytree(ROOT / "plugins" / "safe_lookup", copy)
        store, _ = stores(root / "data")
        first = scan_plugin(copy); evaluate_admission(first, store)
        print("before change:", store.status_for(first))
        source = copy / "plugin.py"; source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        second = scan_plugin(copy)
        print("after change:", store.status_for(second))


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); store, receipts = stores(root / "data")
        reports = {r.manifest.name if r.manifest else Path(r.plugin_dir).name: r for r in discover_plugins(ROOT / "plugins")}
        assert reports["safe_lookup"].accepted_static
        assert not reports["manifest_mismatch"].accepted_static
        assert evaluate_admission(reports["safe_lookup"], store) == "admitted"
        assert evaluate_admission(reports["local_note"], store) == "pending_confirmation"
        assert evaluate_admission(reports["local_note"], store, "CONFIRM") == "admitted"
        assert evaluate_admission(reports["bad_probe"], store) == "rejected"
        runtime = PluginRuntime(store, receipts, root / "workspace")
        state = ClarificationState("local_note")
        assert runtime.next_question(reports["local_note"], state) == "笔记标题是什么？"
        runtime.provide(state, "title", "测试")
        assert runtime.next_question(reports["local_note"], state) == "要保存到哪个目录？"
        runtime.provide(state, "directory", "notes")
        first = runtime.execute(reports["local_note"], state.values)
        second = runtime.execute(reports["local_note"], state.values)
        assert not first.reused and second.reused and first.receipt_id == second.receipt_id
    print("离线自检通过：发现、拒绝、准入、单步澄清、指纹保护与幂等执行均正常。")
    print("这一步没有访问网络，也没有调用模型或真实外部工具。")


def main() -> int:
    parser = argparse.ArgumentParser(description="第 10 章：插件发现与准入")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--demo-discovery", action="store_true")
    group.add_argument("--demo-admission", action="store_true")
    group.add_argument("--demo-clarification", action="store_true")
    group.add_argument("--demo-stale", action="store_true")
    args = parser.parse_args()
    if args.self_test: self_test()
    elif args.demo_discovery: demo_discovery()
    elif args.demo_admission: demo_admission()
    elif args.demo_clarification: demo_clarification()
    elif args.demo_stale: demo_stale()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
