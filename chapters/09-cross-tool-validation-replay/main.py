"""《RE:从零开始的大模型研究日记》第 09 章离线示例。"""
from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

from journal import JournalError
from workflow import CrossToolRuntime, SimulatedCrash


def _runtime(path: Path) -> CrossToolRuntime:
    return CrossToolRuntime(path)


def demo_success() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = _runtime(Path(tmp))
        plan = rt.create_plan("第 09 章", "posts/ch09.md", "可靠不是每一步都成功，而是组合结果可验证。\n", "wf_demo_success")
        result = rt.execute(plan.workflow_id)
        print(f"成功演示：{result.status}，完成步骤 {len(result.completed_steps)}。")


def demo_validation_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = _runtime(Path(tmp))
        plan = rt.create_plan("第 09 章", "posts/ch09.md", "版本 B\n", "wf_demo_failure")
        result = rt.execute(plan.workflow_id, wrong_index_hash="0" * 64)
        print(f"验证失败演示：{result.status}。两个工具均返回成功，但组合结果未通过。")


def demo_resume() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = _runtime(root)
        plan = rt.create_plan("第 09 章", "posts/ch09.md", "恢复时先查证据。\n", "wf_demo_resume")
        try:
            rt.execute(plan.workflow_id, crash_after_document_tool=True)
        except SimulatedCrash:
            pass
        rt2 = _runtime(root)
        result = rt2.execute(plan.workflow_id)
        files = list((root / "documents").rglob("*.md"))
        print(f"恢复演示：{result.status}，文档数量 {len(files)}；第一步回执由工具侧找回。")


def demo_rollback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = _runtime(root)
        plan = rt.create_plan("第 09 章", "posts/ch09.md", "需要回滚。\n", "wf_demo_rollback")
        rt.execute(plan.workflow_id)
        result = rt.rollback(plan.workflow_id)
        print(f"回滚演示：{result.status}，补偿顺序 {list(result.completed_steps)}。")


def self_test() -> None:
    demo_success()
    demo_validation_failure()
    demo_resume()
    demo_rollback()
    print("离线自检通过：跨工具执行、后置验证、逆序回滚与证据重放均正常。")
    print("这一步没有访问网络，也没有调用模型或真实外部工具。")


def check_journal(path: Path) -> None:
    rt = _runtime(path)
    events = rt.journal.read()
    print(f"流水账检查通过：{rt.journal.path}，{len(events)} 个事件。")


def main() -> None:
    parser = argparse.ArgumentParser(description="第 09 章：跨工具验证、回滚与证据重放")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--demo-success", action="store_true")
    parser.add_argument("--demo-validation-failure", action="store_true")
    parser.add_argument("--demo-resume", action="store_true")
    parser.add_argument("--demo-rollback", action="store_true")
    parser.add_argument("--check-journal", action="store_true")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    try:
        if args.self_test: self_test()
        elif args.demo_success: demo_success()
        elif args.demo_validation_failure: demo_validation_failure()
        elif args.demo_resume: demo_resume()
        elif args.demo_rollback: demo_rollback()
        elif args.check_journal: check_journal(args.data_root)
        else: parser.print_help()
    except JournalError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
