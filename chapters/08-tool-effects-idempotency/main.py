"""《RE:从零开始的大模型研究日记》配套代码 08。"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from actions import ActionCoordinator, ActionCoordinatorError
from journal import ActionJournal, JournalError, JournalFormatError
from receipts import ReceiptFormatError, ReceiptStore
from tools import LocalNoteTool, OpaqueCounterTool, SimulatedProcessCrash


def chapter_dir() -> Path:
    return Path(__file__).resolve().parent


def build_coordinator(base: Path | None = None) -> ActionCoordinator:
    root = base or chapter_dir() / "data"
    return ActionCoordinator(
        journal=ActionJournal(root / "action_journal.jsonl"),
        receipts=ReceiptStore(root / "receipts.json"),
        tools={
            "local_note": LocalNoteTool(root / "tool_state"),
            "opaque_counter": OpaqueCounterTool(root / "tool_state"),
        },
    )


def print_result(result) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        coordinator = build_coordinator(base)
        first = coordinator.execute(
            tool_name="local_note",
            payload={"title": "第一次", "body": "同一动作只应发生一次。"},
            idempotency_key="demo:self-test:one",
        )
        second = coordinator.execute(
            tool_name="local_note",
            payload={"title": "被忽略", "body": "不会再次写文件。"},
            idempotency_key="demo:self-test:one",
        )
        assert first.receipt == second.receipt and second.reused
        assert len(list((base / "tool_state" / "notes").glob("*.txt"))) == 1

        try:
            coordinator.execute(
                tool_name="local_note",
                payload={"title": "崩溃", "body": "工具已完成，Runtime 尚未记账。"},
                idempotency_key="demo:self-test:crash",
                simulate="crash_after_effect",
            )
        except SimulatedProcessCrash:
            pass
        else:
            raise AssertionError("crash simulation did not interrupt")
        recovered = build_coordinator(base).recover("demo:self-test:crash")
        assert recovered.status == "completed" and recovered.receipt is not None

        unknown = coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="demo:self-test:opaque",
            simulate="lose_response",
        )
        assert unknown.status == "effect_unknown"

        compensation = coordinator.compensate(
            original_key="demo:self-test:one",
            compensation_key="demo:self-test:undo",
            confirm="CONFIRM",
        )
        assert compensation.status == "compensated"
        assert first.receipt is not None
        assert not Path(first.receipt.effect_ref).exists()
        assert len(coordinator.receipts.all()) == 3
        coordinator.journal.read_all()

    print("离线自检通过：动作流水账、幂等回执、未知结果与补偿均正常。")
    print("这一步没有访问网络，没有调用模型，也没有操作真实外部服务。")


def run_demo_idempotency() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        coordinator = build_coordinator(Path(tmp))
        key = "demo:idempotency:note"
        first = coordinator.execute(
            tool_name="local_note",
            payload={"title": "只写一次", "body": "第一次调用创建文件。"},
            idempotency_key=key,
        )
        second = coordinator.execute(
            tool_name="local_note",
            payload={"title": "不会覆盖", "body": "第二次复用回执。"},
            idempotency_key=key,
        )
        note_count = len(list((Path(tmp) / "tool_state" / "notes").glob("*.txt")))
        print(f"第一次 reused={first.reused}，第二次 reused={second.reused}")
        print(f"回执相同：{first.receipt == second.receipt}")
        print(f"实际文件数量：{note_count}")


def run_demo_receipt_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        coordinator = build_coordinator(base)
        key = "demo:receipt:recovery"
        try:
            coordinator.execute(
                tool_name="local_note",
                payload={"title": "工具已经做完", "body": "Runtime 在保存本地回执前退出。"},
                idempotency_key=key,
                simulate="crash_after_effect",
            )
        except SimulatedProcessCrash as exc:
            print(f"模拟中断：{exc}")
        recovered = build_coordinator(base).recover(key)
        print_result(recovered)
        note_count = len(list((base / "tool_state" / "notes").glob("*.txt")))
        print(f"恢复后文件数量仍为：{note_count}")


def run_demo_unknown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        coordinator = build_coordinator(base)
        result = coordinator.execute(
            tool_name="opaque_counter",
            payload={"amount": 1},
            idempotency_key="demo:opaque:unknown",
            simulate="lose_response",
        )
        print_result(result)
        print("Runtime 不会自动重试，因为它无法证明副作用没有发生。")
        print(f"黑盒计数器当前值：{(base / 'tool_state' / 'opaque_counter.txt').read_text().strip()}")


def run_demo_compensation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        coordinator = build_coordinator(base)
        original = coordinator.execute(
            tool_name="local_note",
            payload={"title": "需要撤销", "body": "补偿不是抹掉历史。"},
            idempotency_key="demo:compensation:create",
        )
        compensated = coordinator.compensate(
            original_key="demo:compensation:create",
            compensation_key="demo:compensation:delete",
            confirm="CONFIRM",
        )
        print_result(original)
        print_result(compensated)
        print(f"流水账事件数：{len(coordinator.journal.read_all())}")
        print(f"回执数：{len(coordinator.receipts.all())}")


def run_check_actions() -> None:
    coordinator = build_coordinator()
    events = coordinator.journal.read_all()
    print("动作流水账检查通过。")
    print(f"位置：{coordinator.journal.path}")
    print(f"事件数量：{len(events)}")
    print(f"动作数量：{len(coordinator.summaries())}")


def run_check_receipts() -> None:
    coordinator = build_coordinator()
    receipts = coordinator.receipts.all()
    print("回执存储检查通过。")
    print(f"位置：{coordinator.receipts.path}")
    print(f"回执数量：{len(receipts)}")


def run_repair_actions() -> None:
    coordinator = build_coordinator()
    backup = coordinator.journal.repair_trailing_fragment()
    print(f"末尾残片已移除，原文件备份为：{backup}")


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /create KEY 标题 | 正文             创建本地笔记\n"
        "  /create-crash KEY 标题 | 正文       模拟工具完成后 Runtime 中断\n"
        "  /opaque KEY                         模拟不可查询的黑盒副作用\n"
        "  /recover KEY                        只查询回执并本地恢复\n"
        "  /retry OLD NEW CONFIRM              明确授权黑盒未知动作的新尝试\n"
        "  /compensate OLD NEW CONFIRM         用新动作补偿已确认副作用\n"
        "  /actions                            列出动作\n"
        "  /replay ACTION_ID                   只读重放动作事件\n"
        "  /receipts                           列出回执\n"
        "  /where                              显示本地文件位置\n"
        "  /exit                               退出\n"
    )


def parse_note_command(user_input: str, prefix: str) -> tuple[str, str, str]:
    rest = user_input[len(prefix) :].strip()
    parts = rest.split(maxsplit=1)
    if len(parts) != 2 or "|" not in parts[1]:
        raise ValueError(f"用法：{prefix} KEY 标题 | 正文")
    key = parts[0]
    title, body = (item.strip() for item in parts[1].split("|", maxsplit=1))
    if not title or not body:
        raise ValueError("标题和正文都不能为空")
    return key, title, body


def run_chat() -> None:
    coordinator = build_coordinator()
    print("工具副作用、幂等与补偿实验台")
    print("所有工具都只操作本章 data/ 目录。输入 /help 查看命令。")
    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return
        if not user_input:
            continue
        command = user_input.lower()
        try:
            if command in {"/exit", "exit", "quit"}:
                print("已退出。")
                return
            if command == "/help":
                print_help()
            elif command.startswith("/create-crash "):
                key, title, body = parse_note_command(user_input, "/create-crash")
                try:
                    coordinator.execute(
                        tool_name="local_note",
                        payload={"title": title, "body": body},
                        idempotency_key=key,
                        simulate="crash_after_effect",
                    )
                except SimulatedProcessCrash as exc:
                    print(f"模拟中断：{exc}")
                    print(f"重新启动后使用 /recover {key}，不要再次 /create。")
            elif command.startswith("/create "):
                key, title, body = parse_note_command(user_input, "/create")
                print_result(
                    coordinator.execute(
                        tool_name="local_note",
                        payload={"title": title, "body": body},
                        idempotency_key=key,
                    )
                )
            elif command.startswith("/opaque "):
                key = user_input.split(maxsplit=1)[1]
                print_result(
                    coordinator.execute(
                        tool_name="opaque_counter",
                        payload={"amount": 1},
                        idempotency_key=key,
                        simulate="lose_response",
                    )
                )
            elif command.startswith("/recover "):
                key = user_input.split(maxsplit=1)[1]
                print_result(coordinator.recover(key))
            elif command.startswith("/retry "):
                parts = user_input.split()
                if len(parts) != 4:
                    raise ValueError("用法：/retry OLD_KEY NEW_KEY CONFIRM")
                old_events = coordinator.journal.find_by_key(parts[1])
                if not old_events:
                    raise ValueError("找不到旧动作")
                print_result(
                    coordinator.retry_unknown(
                        old_key=parts[1],
                        new_key=parts[2],
                        confirm=parts[3],
                        payload={"amount": 1},
                    )
                )
            elif command.startswith("/compensate "):
                parts = user_input.split()
                if len(parts) != 4:
                    raise ValueError("用法：/compensate OLD_KEY NEW_KEY CONFIRM")
                print_result(
                    coordinator.compensate(
                        original_key=parts[1],
                        compensation_key=parts[2],
                        confirm=parts[3],
                    )
                )
            elif command == "/actions":
                print(json.dumps(coordinator.summaries(), ensure_ascii=False, indent=2))
            elif command.startswith("/replay "):
                action_id = user_input.split(maxsplit=1)[1]
                print(json.dumps(coordinator.replay(action_id), ensure_ascii=False, indent=2))
            elif command == "/receipts":
                print(
                    json.dumps(
                        [receipt.to_dict() for receipt in coordinator.receipts.all()],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            elif command == "/where":
                print(f"动作流水账：{coordinator.journal.path}")
                print(f"Runtime 回执：{coordinator.receipts.path}")
                print(f"工具状态：{chapter_dir() / 'data' / 'tool_state'}")
            else:
                print("未知命令。输入 /help 查看说明。")
        except (ValueError, ActionCoordinatorError, JournalError, ReceiptFormatError) as exc:
            print(f"操作失败：{exc}")
        except Exception as exc:
            print(f"未预期错误：{exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapter 08 tool side-effect lab")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--demo-idempotency", action="store_true")
    parser.add_argument("--demo-receipt-recovery", action="store_true")
    parser.add_argument("--demo-unknown", action="store_true")
    parser.add_argument("--demo-compensation", action="store_true")
    parser.add_argument("--check-actions", action="store_true")
    parser.add_argument("--check-receipts", action="store_true")
    parser.add_argument("--repair-actions", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_test()
        elif args.demo_idempotency:
            run_demo_idempotency()
        elif args.demo_receipt_recovery:
            run_demo_receipt_recovery()
        elif args.demo_unknown:
            run_demo_unknown()
        elif args.demo_compensation:
            run_demo_compensation()
        elif args.check_actions:
            run_check_actions()
        elif args.check_receipts:
            run_check_receipts()
        elif args.repair_actions:
            run_repair_actions()
        else:
            run_chat()
    except (JournalFormatError, ReceiptFormatError, ActionCoordinatorError, JournalError) as exc:
        raise SystemExit(f"Error: {exc}") from None


if __name__ == "__main__":
    main()
