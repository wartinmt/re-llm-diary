"""《RE:从零开始的大模型研究日记》配套代码 03。"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from memory import ConversationStore, MemoryErrorBase, MemoryFormatError

BASE_URL: Final = "https://api.deepseek.com"
DEFAULT_MODEL: Final = "deepseek-v4-flash"
SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。"


def chapter_dir() -> Path:
    return Path(__file__).resolve().parent


def load_settings(require_key: bool = True) -> tuple[str, str, Path]:
    load_dotenv(chapter_dir() / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    placeholder = "把你的_API_Key_填在这里"
    if require_key and (not api_key or api_key == placeholder):
        raise RuntimeError(
            "没有找到可用的 DEEPSEEK_API_KEY。请复制 .env.example 为 .env，"
            "再填写自己的 Key。"
        )
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    raw_path = os.getenv("MEMORY_PATH", "data/conversation.json").strip()
    memory_path = Path(raw_path)
    if not memory_path.is_absolute():
        memory_path = chapter_dir() / memory_path
    return api_key, model, memory_path.resolve()


def create_client() -> tuple[OpenAI, str, ConversationStore]:
    api_key, model, memory_path = load_settings(require_key=True)
    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=60.0, max_retries=2)
    return client, model, ConversationStore(memory_path)


def request_answer(
    client: OpenAI, model: str, messages: list[dict[str, str]]
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        stream=False,
        max_tokens=512,
        extra_body={"thinking": {"type": "disabled"}},
    )
    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("模型返回了空内容，请稍后重试。")
    return answer.strip()


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /where    显示记忆文件位置\n"
        "  /history  显示已保存的消息数量\n"
        "  /save     手动保存当前对话\n"
        "  /forget   经确认后删除当前记忆\n"
        "  /help     显示命令说明\n"
        "  /exit     保存并退出\n"
    )


def print_unsaved_answer(display_name: str, answer: str) -> None:
    print(f"\n{display_name}（未保存）：{answer}")


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conversation.json"
        store = ConversationStore(path)
        assert store.load() == []
        sample = [
            {"role": "user", "content": "我的代号是海盐。"},
            {"role": "assistant", "content": "收到。"},
        ]
        store.save(sample)
        assert store.load() == sample
        assert not list(path.parent.glob("*.tmp"))

        original = path.read_text(encoding="utf-8")
        path.write_text("{broken", encoding="utf-8")
        try:
            store.load()
        except MemoryFormatError:
            pass
        else:
            raise RuntimeError("损坏存档测试失败。")
        assert path.read_text(encoding="utf-8") == "{broken"

        path.write_text(original, encoding="utf-8")
        assert store.forget() is True
        assert store.load() == []
    print("离线自检通过：保存、恢复、损坏保护与删除均正常。")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_config_check() -> None:
    api_key, model, memory_path = load_settings(require_key=True)
    print("配置检查通过。")
    print("API Key：已读取（不会显示内容）")
    print(f"模型：{model}")
    print(f"记忆文件：{memory_path}")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_memory_check() -> None:
    _, _, memory_path = load_settings(require_key=False)
    store = ConversationStore(memory_path)
    messages = store.load()
    print("记忆文件检查通过。")
    print(f"位置：{memory_path}")
    print(f"消息数量：{len(messages)}")


def run_chat() -> None:
    client, model, store = create_client()
    messages = store.load()
    print("DeepSeek 持久对话客户端")
    print(f"当前模型：{model}")
    print(f"已恢复 {len(messages)} 条历史消息。")
    print("输入 /help 查看命令。")

    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            store.save(messages)
            print("\n已保存并退出。")
            return
        if not user_input:
            continue
        command = user_input.lower()
        if command in {"/exit", "exit", "quit"}:
            store.save(messages)
            print("已保存并退出。")
            return
        if command == "/help":
            print_help(); continue
        if command == "/where":
            print(f"记忆文件：{store.path}"); continue
        if command == "/history":
            print(f"当前保存 {len(messages)} 条消息。"); continue
        if command == "/save":
            store.save(messages)
            print("当前对话已保存。"); continue
        if command == "/forget":
            confirm = input("输入 DELETE 确认删除当前记忆：").strip()
            if confirm != "DELETE":
                print("已取消。")
                continue
            store.forget()
            messages = []
            print("当前记忆已删除。")
            continue

        candidate = [*messages, {"role": "user", "content": user_input}]
        try:
            answer = request_answer(client, model, candidate)
        except OpenAIError as exc:
            print(f"\n请求失败：{exc}", file=sys.stderr)
            print("失败内容没有写入记忆。", file=sys.stderr)
            continue
        except RuntimeError as exc:
            print(f"\n运行失败：{exc}", file=sys.stderr)
            continue

        candidate.append({"role": "assistant", "content": answer})
        try:
            store.save(candidate)
        except OSError as exc:
            print(f"\n保存失败：{exc}", file=sys.stderr)
            print("本轮不会进入当前记忆，请先解决磁盘或权限问题。", file=sys.stderr)
            print_unsaved_answer("DeepSeek", answer)
            continue
        messages = candidate
        print(f"\nDeepSeek：{answer}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="观察跨程序重启的本地对话记忆。")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true", help="离线检查存储逻辑。")
    group.add_argument("--check-config", action="store_true", help="检查 .env，不发请求。")
    group.add_argument("--check-memory", action="store_true", help="检查记忆文件，不发请求。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test: run_self_test()
    elif args.check_config: run_config_check()
    elif args.check_memory: run_memory_check()
    else: run_chat()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, MemoryErrorBase) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
