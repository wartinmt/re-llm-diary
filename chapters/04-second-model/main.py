"""《RE:从零开始的大模型研究日记》配套代码 04。"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from memory import ConversationStore, MemoryErrorBase, MemoryFormatError
from providers import (
    ProviderConfig,
    choose_default_provider,
    create_clients,
    load_provider_configs,
    request_answer,
)

SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。"


@dataclass(frozen=True)
class AppSettings:
    providers: dict[str, ProviderConfig]
    default_provider: str
    memory_path: Path
    max_tokens: int


@dataclass(frozen=True)
class ComparisonResult:
    provider_key: str
    display_name: str
    model: str
    answer: str | None
    error: str | None
    elapsed_seconds: float


def chapter_dir() -> Path:
    return Path(__file__).resolve().parent


def _read_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效整数：{raw}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} 必须大于 0。")
    return value


def load_settings(require_provider: bool = True) -> AppSettings:
    load_dotenv(chapter_dir() / ".env")
    providers = load_provider_configs(os.environ, require_any=require_provider)
    requested = os.getenv("DEFAULT_PROVIDER", "deepseek")
    default_provider = (
        choose_default_provider(providers, requested) if providers else ""
    )
    raw_path = os.getenv("MEMORY_PATH", "data/conversation.json").strip()
    memory_path = Path(raw_path)
    if not memory_path.is_absolute():
        memory_path = chapter_dir() / memory_path
    return AppSettings(
        providers=providers,
        default_provider=default_provider,
        memory_path=memory_path.resolve(),
        max_tokens=_read_positive_int("MAX_TOKENS", 512),
    )


def build_api_messages(
    history: list[dict[str, str]], prompt: str
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *({"role": item["role"], "content": item["content"]} for item in history),
        {"role": "user", "content": prompt},
    ]


def compare_providers(
    provider_keys: list[str],
    configs: Mapping[str, ProviderConfig],
    clients: Mapping[str, OpenAI],
    history: list[dict[str, str]],
    prompt: str,
    max_tokens: int,
    request_fn: Callable[[OpenAI, ProviderConfig, list[dict[str, str]], int], str] = request_answer,
) -> list[ComparisonResult]:
    api_messages = build_api_messages(history, prompt)
    results: list[ComparisonResult] = []
    for key in provider_keys:
        config = configs[key]
        started = time.perf_counter()
        try:
            answer = request_fn(clients[key], config, api_messages, max_tokens)
        except Exception as exc:  # 单个模型失败不应阻止另一个模型显示结果。
            results.append(
                ComparisonResult(
                    provider_key=key,
                    display_name=config.display_name,
                    model=config.model,
                    answer=None,
                    error=str(exc),
                    elapsed_seconds=time.perf_counter() - started,
                )
            )
        else:
            results.append(
                ComparisonResult(
                    provider_key=key,
                    display_name=config.display_name,
                    model=config.model,
                    answer=answer,
                    error=None,
                    elapsed_seconds=time.perf_counter() - started,
                )
            )
    return results


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /models             显示已配置模型\n"
        "  /active             显示当前模型\n"
        "  /use deepseek       切换到 DeepSeek\n"
        "  /use glm            切换到 GLM\n"
        "  /compare 问题       用相同上下文比较所有已配置模型\n"
        "  /where              显示记忆文件位置\n"
        "  /history            显示保存的消息数量\n"
        "  /save               手动保存当前对话\n"
        "  /forget             经确认后删除当前记忆\n"
        "  /help               显示命令说明\n"
        "  /exit               保存并退出\n"
    )


def print_models(
    configs: Mapping[str, ProviderConfig], active_provider: str
) -> None:
    print("\n已配置模型：")
    for key, config in configs.items():
        marker = "*" if key == active_provider else " "
        print(f"  {marker} {key:<8} {config.display_name} / {config.model}")
    print("* 表示当前普通对话使用的模型。")


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp) / "conversation.json")
        history = [
            {"role": "user", "content": "我的代号是海盐。"},
            {"role": "assistant", "content": "收到。"},
        ]
        store.save(history)
        if store.load() != history:
            raise RuntimeError("记忆保存与恢复自检失败。")

        configs = {
            "deepseek": ProviderConfig(
                key="deepseek",
                display_name="DeepSeek",
                api_key="secret-a",
                base_url="https://example.invalid/a",
                model="model-a",
                extra_body={"thinking": {"type": "disabled"}},
            ),
            "glm": ProviderConfig(
                key="glm",
                display_name="GLM",
                api_key="secret-b",
                base_url="https://example.invalid/b",
                model="model-b",
            ),
        }
        fake_clients: dict[str, object] = {"deepseek": object(), "glm": object()}
        original = [dict(item) for item in history]

        def fake_request(client, config, messages, max_tokens):
            del client, max_tokens
            if messages[-1]["content"] != "同一个问题":
                raise RuntimeError("比较提示没有进入请求。")
            return f"{config.display_name} 的离线回答"

        results = compare_providers(
            ["deepseek", "glm"],
            configs,
            fake_clients,  # type: ignore[arg-type]
            history,
            "同一个问题",
            256,
            request_fn=fake_request,
        )
        if history != original:
            raise RuntimeError("比较模式错误地修改了正式记忆。")
        if [result.answer for result in results] != [
            "DeepSeek 的离线回答",
            "GLM 的离线回答",
        ]:
            raise RuntimeError("双模型比较自检失败。")
        if choose_default_provider(configs, "missing") != "deepseek":
            raise RuntimeError("默认模型回退自检失败。")

    print("离线自检通过：记忆、模型选择与临时比较均正常。")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_config_check() -> None:
    settings = load_settings(require_provider=True)
    print("配置检查通过。")
    print(f"默认模型：{settings.default_provider}")
    print(f"最大输出：{settings.max_tokens} Token")
    print(f"记忆文件：{settings.memory_path}")
    print("已配置提供方（不会显示 API Key）：")
    for key, config in settings.providers.items():
        print(f"  {key}: {config.display_name} / {config.model}")
    if len(settings.providers) < 2:
        print("提示：当前只有一个模型可用，/compare 需要至少两个模型。")
    print("这一步没有发送 API 请求。")


def run_memory_check() -> None:
    settings = load_settings(require_provider=False)
    messages = ConversationStore(settings.memory_path).load()
    print("记忆文件检查通过。")
    print(f"位置：{settings.memory_path}")
    print(f"消息数量：{len(messages)}")


def run_chat() -> None:
    settings = load_settings(require_provider=True)
    configs = settings.providers
    clients = create_clients(configs)
    store = ConversationStore(settings.memory_path)
    messages = store.load()
    active_provider = settings.default_provider

    print("双模型持久对话客户端")
    print(f"已恢复 {len(messages)} 条历史消息。")
    print_models(configs, active_provider)
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
            print_help()
            continue
        if command == "/models":
            print_models(configs, active_provider)
            continue
        if command == "/active":
            config = configs[active_provider]
            print(f"当前模型：{active_provider} / {config.model}")
            continue
        if command.startswith("/use"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2:
                print("用法：/use deepseek 或 /use glm")
                continue
            requested = parts[1].strip().lower()
            if requested not in configs:
                print(f"模型 {requested!r} 未配置。输入 /models 查看可用项。")
                continue
            active_provider = requested
            config = configs[active_provider]
            print(f"已切换到 {config.display_name} / {config.model}。")
            continue
        if command.startswith("/compare"):
            if len(configs) < 2:
                print("比较需要至少两个已配置模型。")
                continue
            prompt = user_input[len("/compare"):].strip()
            if not prompt:
                prompt = input("要比较的问题：").strip()
            if not prompt:
                print("比较已取消。")
                continue
            results = compare_providers(
                list(configs),
                configs,
                clients,
                messages,
                prompt,
                settings.max_tokens,
            )
            print("\n=== 临时比较（不会写入记忆） ===")
            for result in results:
                print(f"\n[{result.display_name} / {result.model} / {result.elapsed_seconds:.2f}s]")
                if result.error:
                    print(f"请求失败：{result.error}")
                else:
                    print(result.answer)
            print("\n比较结束。正式对话与记忆均未改变。")
            continue
        if command == "/where":
            print(f"记忆文件：{store.path}")
            continue
        if command == "/history":
            print(f"当前保存 {len(messages)} 条消息。")
            continue
        if command == "/save":
            store.save(messages)
            print("当前对话已保存。")
            continue
        if command == "/forget":
            confirm = input("输入 DELETE 确认删除当前记忆：").strip()
            if confirm != "DELETE":
                print("已取消。")
                continue
            store.forget()
            messages = []
            print("当前记忆已删除。")
            continue

        config = configs[active_provider]
        candidate = [*messages, {"role": "user", "content": user_input}]
        api_messages = build_api_messages(messages, user_input)
        try:
            answer = request_answer(
                clients[active_provider], config, api_messages, settings.max_tokens
            )
        except OpenAIError as exc:
            print(f"\n{config.display_name} 请求失败：{exc}", file=sys.stderr)
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
            print("本轮不会进入当前记忆。", file=sys.stderr)
            continue
        messages = candidate
        print(f"\n{config.display_name}：{answer}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="手动切换并比较两个模型。")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true", help="离线检查核心逻辑。")
    group.add_argument("--check-config", action="store_true", help="检查模型配置，不发请求。")
    group.add_argument("--check-memory", action="store_true", help="检查记忆文件，不发请求。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
    elif args.check_config:
        run_config_check()
    elif args.check_memory:
        run_memory_check()
    else:
        run_chat()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, MemoryErrorBase) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
