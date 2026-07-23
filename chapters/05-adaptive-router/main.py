"""《RE:从零开始的大模型研究日记》配套代码 05。"""
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

from memory import ConversationStore, MemoryFormatError
from providers import (
    ProviderConfig,
    choose_default_provider,
    create_clients,
    load_provider_configs,
    request_answer,
)
from router import (
    RouterError,
    RouterFormatError,
    RouterState,
    RouterStore,
    RouteDecision,
    VALID_POLICIES,
    choose_provider,
    classify_prompt,
    rate_pending,
    record_result,
    set_pending_rating,
)

SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。"


@dataclass(frozen=True)
class AppSettings:
    providers: dict[str, ProviderConfig]
    default_provider: str
    memory_path: Path
    router_path: Path
    max_tokens: int
    default_policy: str


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


def _resolve_local_path(env_name: str, default: str) -> Path:
    raw = os.getenv(env_name, default).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = chapter_dir() / path
    return path.resolve()


def load_settings(require_provider: bool = True) -> AppSettings:
    load_dotenv(chapter_dir() / ".env")
    providers = load_provider_configs(os.environ, require_any=require_provider)
    requested = os.getenv("DEFAULT_PROVIDER", "deepseek")
    default_provider = (
        choose_default_provider(providers, requested) if providers else ""
    )
    policy = os.getenv("ROUTER_POLICY", "balanced").strip().lower() or "balanced"
    if policy not in VALID_POLICIES:
        raise RuntimeError(
            f"ROUTER_POLICY 只支持 balanced、fast、quality，当前为：{policy}"
        )
    return AppSettings(
        providers=providers,
        default_provider=default_provider,
        memory_path=_resolve_local_path("MEMORY_PATH", "data/conversation.json"),
        router_path=_resolve_local_path("ROUTER_PATH", "data/router_state.json"),
        max_tokens=_read_positive_int("MAX_TOKENS", 512),
        default_policy=policy,
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
        except Exception as exc:
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
        "\n模型与路由：\n"
        "  /models                 显示已配置模型\n"
        "  /mode                   显示当前手动/自动模式与策略\n"
        "  /auto                   启用自动路由\n"
        "  /use deepseek           手动固定到 DeepSeek\n"
        "  /use glm                手动固定到 GLM\n"
        "  /policy balanced        平衡质量、可靠性和速度\n"
        "  /policy fast            提高速度权重\n"
        "  /policy quality         提高用户评分权重\n"
        "  /route 问题             预览路由，不调用 API\n"
        "  /why                    解释上一次路由选择\n"
        "  /router-stats           显示累计观测\n"
        "  /rate 1-5               为最近一次普通回答评分\n"
        "  /router-reset           经确认后清空路由观测\n"
        "  /compare 问题           临时比较所有模型，不写入对话记忆\n"
        "\n对话记忆：\n"
        "  /where                  显示本地文件位置\n"
        "  /history                显示消息数量\n"
        "  /save                   手动保存\n"
        "  /forget                 经确认后删除对话记忆\n"
        "  /help                   显示命令\n"
        "  /exit                   保存并退出\n"
    )


def print_unsaved_answer(display_name: str, answer: str) -> None:
    print(f"\n{display_name}（未保存）：{answer}")


def print_models(configs: Mapping[str, ProviderConfig], state: RouterState) -> None:
    print("\n已配置模型：")
    for key, config in configs.items():
        manual = "*" if state.mode == "manual" and state.manual_provider == key else " "
        print(f"  {manual} {key:<8} {config.display_name} / {config.model}")
    print("自动模式会根据本地路由状态选择；* 只表示手动模式当前模型。")


def print_mode(state: RouterState) -> None:
    if state.mode == "auto":
        print(f"当前模式：auto；策略：{state.policy}")
    else:
        print(f"当前模式：manual；模型：{state.manual_provider}；策略记录：{state.policy}")


def print_decision(decision: RouteDecision, configs: Mapping[str, ProviderConfig]) -> None:
    chosen = configs[decision.chosen_provider]
    print(
        f"路由结果：{chosen.display_name} / {chosen.model}\n"
        f"任务分类：{decision.bucket}\n"
        f"依据：{'；'.join(decision.signals)}\n"
        f"策略：{decision.policy}"
    )
    for key, score in sorted(decision.scores.items()):
        name = configs[key].display_name
        print(
            f"  {name:<10} total={score.total:.3f} "
            f"quality={score.quality:.3f} reliability={score.reliability:.3f} "
            f"speed={score.speed:.3f} exploration={score.exploration:.3f}"
        )


def print_last_decision(state: RouterState, configs: Mapping[str, ProviderConfig]) -> None:
    payload = state.last_decision
    if not payload:
        print("还没有路由记录。可先使用 /route 或发送一条普通消息。")
        return
    chosen_key = payload.get("chosen_provider", "")
    chosen_name = configs.get(chosen_key).display_name if chosen_key in configs else chosen_key
    print(f"上一次选择：{chosen_name}")
    print(f"任务分类：{payload.get('bucket')}")
    print(f"策略：{payload.get('policy')}")
    print(f"说明：{payload.get('reason')}")
    scores = payload.get("scores", {})
    if isinstance(scores, dict):
        for key, values in sorted(scores.items()):
            if isinstance(values, dict):
                name = configs.get(key).display_name if key in configs else key
                print(
                    f"  {name:<10} total={values.get('total')} "
                    f"quality={values.get('quality')} reliability={values.get('reliability')} "
                    f"speed={values.get('speed')} exploration={values.get('exploration')}"
                )


def print_router_stats(state: RouterState, configs: Mapping[str, ProviderConfig]) -> None:
    print("\n路由累计观测（不包含提示词和回答正文）：")
    for key in sorted(configs):
        stats = state.provider(key).overall
        name = configs[key].display_name
        latency = stats.average_latency()
        latency_text = "暂无" if latency is None else f"{latency:.2f}s"
        rating = "暂无" if stats.ratings_count == 0 else f"{stats.ratings_sum / stats.ratings_count:.2f}/5"
        print(
            f"  {name:<10} 尝试={stats.attempts} 成功={stats.successes} "
            f"平均响应={latency_text} 用户评分={rating}"
        )


def choose_for_turn(
    prompt: str,
    settings: AppSettings,
    state: RouterState,
) -> tuple[str, RouteDecision | None, str]:
    if state.mode == "manual":
        provider = state.manual_provider
        if provider not in settings.providers:
            provider = settings.default_provider
            state.manual_provider = provider
        bucket = classify_prompt(prompt).bucket
        return provider, None, bucket
    decision = choose_provider(
        prompt,
        settings.providers,
        state,
        settings.default_provider,
    )
    state.last_decision = decision.sanitized_dict()
    return decision.chosen_provider, decision, decision.bucket


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        messages = [
            {"role": "user", "content": "我的代号是海盐。"},
            {"role": "assistant", "content": "收到。"},
        ]
        conversation = ConversationStore(root / "conversation.json")
        conversation.save(messages)
        if conversation.load() != messages:
            raise RuntimeError("对话记忆自检失败。")

        router_store = RouterStore(root / "router_state.json")
        state = RouterState(policy="quality")
        configs = {
            "deepseek": ProviderConfig("deepseek", "DeepSeek", "a", "https://a.invalid", "a"),
            "glm": ProviderConfig("glm", "GLM", "b", "https://b.invalid", "b"),
        }
        first = choose_provider("请分析这个设计的风险", configs, state, "deepseek")
        if first.chosen_provider != "deepseek":
            raise RuntimeError("无数据时没有使用默认模型。")
        record_result(state, "deepseek", "analysis", True, 5.0)
        set_pending_rating(state, "deepseek", "analysis")
        rate_pending(state, 2)
        record_result(state, "glm", "analysis", True, 2.0)
        set_pending_rating(state, "glm", "analysis")
        rate_pending(state, 5)
        second = choose_provider("请分析这个设计的风险", configs, state, "deepseek")
        if second.chosen_provider != "glm":
            raise RuntimeError("评分与观测没有改变质量策略的选择。")
        state.last_decision = second.sanitized_dict()
        router_store.save(state)
        restored = router_store.load()
        if restored.last_decision != state.last_decision:
            raise RuntimeError("路由状态恢复失败。")
        serialized = router_store.path.read_text(encoding="utf-8")
        if "请分析这个设计的风险" in serialized:
            raise RuntimeError("路由状态错误地保存了提示词正文。")

    print("离线自检通过：分类、评分、路由更新、持久化与隐私边界均正常。")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_config_check() -> None:
    settings = load_settings(require_provider=True)
    print("配置检查通过。")
    print(f"默认模型：{settings.default_provider}")
    print(f"默认策略：{settings.default_policy}")
    print(f"对话记忆：{settings.memory_path}")
    print(f"路由状态：{settings.router_path}")
    print("已配置提供方（不会显示 API Key）：")
    for key, config in settings.providers.items():
        print(f"  {key}: {config.display_name} / {config.model}")
    if len(settings.providers) < 2:
        print("提示：只有一个模型时自动路由仍可运行，但无法产生模型间选择。")
    print("这一步没有发送 API 请求。")


def run_router_check() -> None:
    settings = load_settings(require_provider=False)
    state = RouterStore(settings.router_path).load()
    print("路由状态检查通过。")
    print(f"模式：{state.mode}")
    print(f"策略：{state.policy}")
    print(f"已记录提供方：{len(state.providers)}")
    print(f"位置：{settings.router_path}")


def run_chat() -> None:
    settings = load_settings(require_provider=True)
    configs = settings.providers
    clients = create_clients(configs)
    conversation_store = ConversationStore(settings.memory_path)
    router_store = RouterStore(settings.router_path)
    messages = conversation_store.load()
    state = router_store.load()
    if state.policy not in VALID_POLICIES:
        state.policy = settings.default_policy
    if not state.manual_provider:
        state.manual_provider = settings.default_provider

    print("可解释的自适应路由客户端")
    print(f"已恢复 {len(messages)} 条对话消息。")
    print_models(configs, state)
    print_mode(state)
    print("输入 /help 查看命令。")

    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            conversation_store.save(messages)
            router_store.save(state)
            print("\n已保存并退出。")
            return
        if not user_input:
            continue

        command = user_input.lower()
        if command in {"/exit", "exit", "quit"}:
            conversation_store.save(messages)
            router_store.save(state)
            print("已保存并退出。")
            return
        if command == "/help":
            print_help()
            continue
        if command == "/models":
            print_models(configs, state)
            continue
        if command == "/mode":
            print_mode(state)
            continue
        if command == "/auto":
            state.mode = "auto"
            router_store.save(state)
            print(f"已启用自动路由；当前策略：{state.policy}。")
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
            state.mode = "manual"
            state.manual_provider = requested
            router_store.save(state)
            print(f"已进入手动模式：{configs[requested].display_name} / {configs[requested].model}。")
            continue
        if command.startswith("/policy"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[1].strip().lower() not in VALID_POLICIES:
                print("用法：/policy balanced、/policy fast 或 /policy quality")
                continue
            state.policy = parts[1].strip().lower()
            router_store.save(state)
            print(f"路由策略已改为：{state.policy}。")
            continue
        if command.startswith("/route"):
            prompt = user_input[len("/route"):].strip()
            if not prompt:
                prompt = input("要预览的问题：").strip()
            if not prompt:
                print("预览已取消。")
                continue
            decision = choose_provider(prompt, configs, state, settings.default_provider)
            state.last_decision = decision.sanitized_dict()
            router_store.save(state)
            print_decision(decision, configs)
            print("这是本地预览，没有调用 API，也没有保存问题正文。")
            continue
        if command == "/why":
            print_last_decision(state, configs)
            continue
        if command == "/router-stats":
            print_router_stats(state, configs)
            continue
        if command.startswith("/rate"):
            parts = user_input.split(maxsplit=1)
            try:
                rating = int(parts[1]) if len(parts) == 2 else 0
                provider_key, bucket = rate_pending(state, rating)
            except (ValueError, RouterError) as exc:
                print(f"评分失败：{exc}")
                continue
            router_store.save(state)
            print(f"已记录：{configs[provider_key].display_name} / {bucket} / {rating} 分。")
            continue
        if command == "/router-reset":
            confirm = input("输入 RESET 确认清空路由观测（不会删除对话）：").strip()
            if confirm != "RESET":
                print("已取消。")
                continue
            state = RouterState(policy=settings.default_policy, manual_provider=settings.default_provider)
            router_store.save(state)
            print("路由观测已清空；对话记忆没有改变。")
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
            bucket = classify_prompt(prompt).bucket
            results = compare_providers(
                list(configs), configs, clients, messages, prompt, settings.max_tokens
            )
            print("\n=== 临时比较（不会写入对话记忆） ===")
            for result in results:
                record_result(
                    state,
                    result.provider_key,
                    bucket,
                    result.error is None,
                    result.elapsed_seconds,
                )
                print(f"\n[{result.display_name} / {result.model} / {result.elapsed_seconds:.2f}s]")
                print(f"请求失败：{result.error}" if result.error else result.answer)
            router_store.save(state)
            print("\n比较结束；响应时间和成功/失败已进入路由观测，回答正文未写入记忆。")
            continue
        if command == "/where":
            print(f"对话记忆：{conversation_store.path}")
            print(f"路由状态：{router_store.path}")
            continue
        if command == "/history":
            print(f"当前保存 {len(messages)} 条对话消息。")
            continue
        if command == "/save":
            conversation_store.save(messages)
            router_store.save(state)
            print("对话与路由状态均已保存。")
            continue
        if command == "/forget":
            confirm = input("输入 DELETE 确认删除当前对话记忆：").strip()
            if confirm != "DELETE":
                print("已取消。")
                continue
            conversation_store.forget()
            messages = []
            print("对话记忆已删除；路由统计仍然保留。")
            continue

        provider_key, decision, bucket = choose_for_turn(user_input, settings, state)
        config = configs[provider_key]
        if decision is not None:
            print(f"路由：{config.display_name} / {config.model}（{bucket}，{state.policy}）")
        else:
            print(f"手动：{config.display_name} / {config.model}")

        api_messages = build_api_messages(messages, user_input)
        started = time.perf_counter()
        try:
            answer = request_answer(
                clients[provider_key], config, api_messages, settings.max_tokens
            )
        except (OpenAIError, RuntimeError) as exc:
            elapsed = time.perf_counter() - started
            record_result(state, provider_key, bucket, False, elapsed)
            state.pending_rating = None
            router_store.save(state)
            print(f"\n{config.display_name} 请求失败：{exc}", file=sys.stderr)
            print("失败内容没有写入对话记忆；失败记录已进入路由统计。", file=sys.stderr)
            continue

        elapsed = time.perf_counter() - started
        candidate = [
            *messages,
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": answer},
        ]
        try:
            conversation_store.save(candidate)
        except OSError as exc:
            print(f"\n保存失败：{exc}", file=sys.stderr)
            print("本轮不会进入当前对话记忆。", file=sys.stderr)
            print_unsaved_answer(config.display_name, answer)
            continue

        messages = candidate
        record_result(state, provider_key, bucket, True, elapsed)
        set_pending_rating(state, provider_key, bucket)
        router_store.save(state)
        print(f"\n{config.display_name}：{answer}")
        print(f"响应时间：{elapsed:.2f}s。可输入 /rate 1-5 为本轮评分。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在两个 OpenAI 兼容模型之间进行透明、可解释的本地路由。"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true", help="离线检查核心逻辑。")
    group.add_argument("--check-config", action="store_true", help="只检查配置，不请求 API。")
    group.add_argument("--check-router", action="store_true", help="检查本地路由状态文件。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
    elif args.check_config:
        run_config_check()
    elif args.check_router:
        run_router_check()
    else:
        run_chat()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, MemoryFormatError, RouterFormatError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
