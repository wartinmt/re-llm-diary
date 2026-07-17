"""《RE:从零开始的大模型研究日记》配套代码 06。"""
from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Mapping

from dotenv import load_dotenv

from costs import CostBreakdown, TokenUsage, calculate_cost, format_cny
from memory import ConversationStore, MemoryErrorBase, MemoryFormatError
from metrics import MetricsFormatError, RoutingMetricsStore
from providers import (
    ModelResult,
    ProviderConfig,
    choose_default_provider,
    create_clients,
    load_provider_configs,
    request_answer,
)
from router import (
    POLICIES,
    VERIFY_MODES,
    RouteDecision,
    classify_task,
    plan_verification,
    route_prompt,
)
from verifier import (
    VerificationOutcome,
    apply_verification,
    build_verifier_messages,
    parse_verification,
)

SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。遇到不确定事实时明确说明。"


@dataclass(frozen=True)
class AppSettings:
    providers: dict[str, ProviderConfig]
    default_provider: str
    memory_path: Path
    metrics_path: Path
    max_tokens: int
    verifier_max_tokens: int
    initial_mode: str
    initial_policy: str
    verify_mode: str
    auto_fallback: bool
    turn_budget_cny: float


@dataclass(frozen=True)
class CompletedCall:
    provider_key: str
    task_type: str
    result: ModelResult
    cost: CostBreakdown
    elapsed_seconds: float
    accounting_warning: str | None = None


@dataclass
class LastRatedAnswer:
    provider_key: str
    task_type: str
    rated: bool = False


def chapter_dir() -> Path:
    return Path(__file__).resolve().parent


def _resolve_local_path(raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = chapter_dir() / path
    return path.resolve()


def _read_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效整数：{raw}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} 必须大于 0。")
    return value


def _read_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效数字：{raw}") from exc
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"{name} 必须是有限且大于 0 的数字。")
    return value


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 只能是 true 或 false。")


def load_settings(require_provider: bool = True) -> AppSettings:
    load_dotenv(chapter_dir() / ".env")
    providers = load_provider_configs(os.environ, require_any=require_provider)
    default_provider = (
        choose_default_provider(providers, os.getenv("DEFAULT_PROVIDER", "deepseek"))
        if providers else ""
    )
    initial_mode = os.getenv("ROUTER_MODE", "auto").strip().lower()
    if initial_mode not in {"auto", "manual"}:
        raise RuntimeError("ROUTER_MODE 只能是 auto 或 manual。")
    policy = os.getenv("ROUTER_POLICY", "balanced").strip().lower()
    if policy not in POLICIES:
        raise RuntimeError("ROUTER_POLICY 只能是 balanced、economy 或 trust。")
    verify_mode = os.getenv("VERIFY_MODE", "auto").strip().lower()
    if verify_mode not in VERIFY_MODES:
        raise RuntimeError("VERIFY_MODE 只能是 auto、on 或 off。")
    return AppSettings(
        providers=providers,
        default_provider=default_provider,
        memory_path=_resolve_local_path(os.getenv("MEMORY_PATH", "data/conversation.json")),
        metrics_path=_resolve_local_path(os.getenv("ROUTER_STATE_PATH", "data/router_state.json")),
        max_tokens=_read_positive_int("MAX_TOKENS", 512),
        verifier_max_tokens=_read_positive_int("VERIFIER_MAX_TOKENS", 512),
        initial_mode=initial_mode,
        initial_policy=policy,
        verify_mode=verify_mode,
        auto_fallback=_read_bool("AUTO_FALLBACK", True),
        turn_budget_cny=_read_positive_float("TURN_BUDGET_CNY", 0.05),
    )


def build_api_messages(history: list[dict[str, str]], prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *({"role": item["role"], "content": item["content"]} for item in history),
        {"role": "user", "content": prompt},
    ]


def _call_and_record(
    provider_key: str,
    role: str,
    task_type: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    configs: Mapping[str, ProviderConfig],
    clients: Mapping[str, Any],
    metrics: RoutingMetricsStore,
    request_fn: Callable[[Any, ProviderConfig, list[dict[str, str]], int], ModelResult] = request_answer,
) -> CompletedCall:
    config = configs[provider_key]
    started = time.perf_counter()
    try:
        result = request_fn(clients[provider_key], config, messages, max_tokens)
    except Exception:
        try:
            metrics.record_attempt(
                provider_key, task_type, role, False, time.perf_counter() - started
            )
        except OSError as accounting_exc:
            print(
                f"警告：请求失败，同时路由账本也未能保存：{accounting_exc}",
                file=sys.stderr,
            )
        raise
    elapsed = time.perf_counter() - started
    cost = calculate_cost(config.price, result.usage)
    accounting_warning: str | None = None
    try:
        metrics.record_attempt(
            provider_key, task_type, role, True, elapsed, result.usage, cost.total
        )
    except OSError as exc:
        accounting_warning = (
            f"模型回答成功，但路由账本未能保存：{exc}。"
            "本轮不会因此重试或再次调用模型。"
        )
    return CompletedCall(
        provider_key, task_type, result, cost, elapsed, accounting_warning
    )


def _show_accounting_warning(call: CompletedCall) -> None:
    if call.accounting_warning:
        print(f"警告：{call.accounting_warning}", file=sys.stderr)




def _answer_provider_after_verification(
    primary_provider: str,
    verifier_provider: str,
    outcome: VerificationOutcome,
) -> str:
    if outcome.status == "revise" and outcome.revised_answer:
        return verifier_provider
    return primary_provider


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /auto                         自动路由\n"
        "  /use deepseek | /use glm     手动指定模型\n"
        "  /policy balanced|economy|trust\n"
        "  /verify auto|on|off          设置第二模型验证\n"
        "  /budget 0.05                 设置单轮人民币预算\n"
        "  /route 问题                  本地预览选择与预计成本\n"
        "  /why                         查看最近一次路由解释\n"
        "  /costs                       查看累计 Token 与成本\n"
        "  /good / /bad / /rate 1-5    评价最近一次主回答\n"
        "  /compare 问题                临时比较并计入真实成本\n"
        "  /where /history /save /forget\n"
        "  /help /exit\n"
    )


def print_decision(decision: RouteDecision, configs: Mapping[str, ProviderConfig]) -> None:
    print("\n=== 路由解释 ===")
    for line in decision.explanation_lines(configs):
        print(line)


def print_costs(metrics: RoutingMetricsStore, configs: Mapping[str, ProviderConfig]) -> None:
    snapshot = metrics.snapshot()
    print("\n本地累计用量（以 API 返回 usage 和当前配置价格计算）：")
    print("  模型       调用   输入Token  输出Token  命中率    主回答      验证        比较        合计")
    for key in configs:
        item = snapshot.for_provider(key)
        print(
            f"  {key:<10} {item.attempts:<6} {item.prompt_tokens:<10} {item.completion_tokens:<10} "
            f"{item.cache_hit_ratio:>6.1%}  {format_cny(item.primary_cost_cny):<11} "
            f"{format_cny(item.verification_cost_cny):<11} {format_cny(item.comparison_cost_cny):<11} "
            f"{format_cny(item.total_cost_cny)}"
        )
    print(f"  全部模型累计：{format_cny(snapshot.total_cost_cny)}")
    print("提示：失败请求是否计费以平台账单为准；本地只能记录返回了 usage 的成功响应。")


def run_self_test() -> None:
    from costs import PriceTable
    from metrics import RoutingSnapshot
    from verifier import VerificationOutcome

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory = ConversationStore(root / "conversation.json")
        history = [{"role": "user", "content": "代号是海盐。"}, {"role": "assistant", "content": "收到。"}]
        memory.save(history)
        if memory.load() != history:
            raise RuntimeError("记忆自检失败。")

        configs = {
            "cheap": ProviderConfig(
                "cheap", "Cheap", "x", "https://example.invalid", "a",
                {"quick": .96, "analysis": .52, "code": .58, "creative": .60, "general": .80},
                .90, PriceTable(.02, 1, 2),
            ),
            "strong": ProviderConfig(
                "strong", "Strong", "y", "https://example.invalid", "b",
                {"quick": .50, "analysis": .99, "code": .94, "creative": .90, "general": .74},
                .60, PriceTable(2, 8, 28),
            ),
        }
        metrics = RoutingMetricsStore(root / "router_state.json")
        snapshot = metrics.load()
        quick_prompt = "请用一句话解释缓存。"
        quick_messages = build_api_messages([], quick_prompt)
        quick = route_prompt(quick_prompt, quick_messages, configs, snapshot, "economy", .05, 512)
        deep_prompt = "请审查这个架构的状态污染风险并给出验证方案。"
        deep_messages = build_api_messages([], deep_prompt)
        deep = route_prompt(deep_prompt, deep_messages, configs, snapshot, "trust", .05, 512)
        if quick.selected_provider != "cheap" or deep.selected_provider != "strong":
            raise RuntimeError("价格策略路由自检失败。")

        fake_usage = TokenUsage(1000, 200, 250, 750)
        cost = calculate_cost(configs["cheap"].price, fake_usage)
        metrics.record_attempt("cheap", "quick", "primary", True, .2, fake_usage, cost.total)
        if RoutingMetricsStore(root / "router_state.json").load().total_cost_cny <= 0:
            raise RuntimeError("成本持久化自检失败。")

        verifier_messages = build_verifier_messages(deep_prompt, "候选答案")
        plan = plan_verification(
            deep, "strong", configs, snapshot, "on", .05,
            verifier_messages, 256,
        )
        if not plan.enabled or plan.provider_key != "cheap":
            raise RuntimeError("验证计划自检失败。")
        parsed = parse_verification("REVISE\n遗漏回滚。\n---REVISED---\n补充回滚后的答案。")
        if parsed.status != "revise" or apply_verification("旧答案", parsed) != "补充回滚后的答案。":
            raise RuntimeError("验证协议自检失败。")
        uncertain = apply_verification("答案", VerificationOutcome("uncertain", "缺少来源"))
        if "验证提示" not in uncertain:
            raise RuntimeError("不确定提示自检失败。")
    print("离线自检通过：记忆、价格计算、策略路由、预算与验证协议均正常。")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_config_check() -> None:
    settings = load_settings(require_provider=True)
    print("配置检查通过。")
    print(f"初始模式：{settings.initial_mode}")
    print(f"策略：{settings.initial_policy}")
    print(f"验证：{settings.verify_mode}")
    print(f"单轮预算：{format_cny(settings.turn_budget_cny)}")
    print(f"最大输出：{settings.max_tokens} Token；验证最大输出：{settings.verifier_max_tokens} Token")
    print(f"记忆文件：{settings.memory_path}")
    print(f"路由与成本记录：{settings.metrics_path}")
    for key, config in settings.providers.items():
        price = config.price
        print(
            f"  {key}: {config.model} / 百万 Token 价格 "
            f"命中 {price.cache_hit_input_per_million:g}、未命中 {price.cache_miss_input_per_million:g}、输出 {price.output_per_million:g} 元"
        )
    if len(settings.providers) < 2:
        print("提示：只有一个模型时无法进行第二模型验证。")
    print("这一步没有发送 API 请求，也不会显示 API Key。")


def run_memory_check() -> None:
    settings = load_settings(require_provider=False)
    messages = ConversationStore(settings.memory_path).load()
    print(f"记忆文件检查通过：{settings.memory_path}，{len(messages)} 条消息。")


def run_router_check() -> None:
    settings = load_settings(require_provider=False)
    snapshot = RoutingMetricsStore(settings.metrics_path).load()
    print(
        f"路由与成本记录检查通过：{settings.metrics_path}，"
        f"{len(snapshot.providers)} 个模型，累计 {format_cny(snapshot.total_cost_cny)}。"
    )


def _rate(metrics: RoutingMetricsStore, last: LastRatedAnswer | None, rating: int) -> None:
    if last is None:
        print("还没有可评分的成功主回答。")
        return
    if last.rated:
        print("最近一次回答已经评分，不能重复计入。")
        return
    try:
        metrics.record_rating(last.provider_key, last.task_type, rating)
    except OSError as exc:
        print(f"评分没有保存：{exc}", file=sys.stderr)
        return
    last.rated = True
    print(f"已记录 {rating}/5 分。")


def run_chat() -> None:
    settings = load_settings(require_provider=True)
    configs = settings.providers
    clients = create_clients(configs)
    memory = ConversationStore(settings.memory_path)
    messages = memory.load()
    metrics = RoutingMetricsStore(settings.metrics_path)
    metrics.load()

    mode = settings.initial_mode
    active_provider = settings.default_provider
    policy = settings.initial_policy
    verify_mode = settings.verify_mode
    budget_cny = settings.turn_budget_cny
    last_decision: RouteDecision | None = None
    last_answer: LastRatedAnswer | None = None

    print("成本与验证路由客户端")
    print(f"已恢复 {len(messages)} 条消息。模式 {mode}，策略 {policy}，验证 {verify_mode}。")
    print(f"单轮预算 {format_cny(budget_cny)}。输入 /help 查看命令。")

    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            memory.save(messages)
            print("\n已保存并退出。")
            return
        if not user_input:
            continue
        lower = user_input.lower()
        if lower in {"/exit", "exit", "quit"}:
            memory.save(messages)
            print("已保存并退出。")
            return
        if lower == "/help":
            print_help(); continue
        if lower == "/auto":
            mode = "auto"; print("已进入自动路由模式。"); continue
        if lower.startswith("/use "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in configs:
                print(f"模型 {requested!r} 未配置。"); continue
            mode = "manual"; active_provider = requested
            print(f"已进入手动模式：{configs[requested].display_name} / {configs[requested].model}。"); continue
        if lower.startswith("/policy "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in POLICIES:
                print("策略只能是 balanced、economy 或 trust。"); continue
            policy = requested; print(f"策略已改为 {policy}。"); continue
        if lower.startswith("/verify "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in VERIFY_MODES:
                print("验证模式只能是 auto、on 或 off。"); continue
            verify_mode = requested; print(f"验证模式已改为 {verify_mode}。"); continue
        if lower.startswith("/budget "):
            raw = user_input.split(maxsplit=1)[1]
            try:
                value = float(raw)
            except ValueError:
                print("预算必须是人民币数字，例如 /budget 0.05。"); continue
            if not math.isfinite(value) or value <= 0:
                print("预算必须是有限且大于 0 的数字。"); continue
            budget_cny = value; print(f"单轮预算已改为 {format_cny(value)}。"); continue
        if lower == "/mode":
            print(f"模式 {mode}；手动模型 {active_provider}；策略 {policy}；验证 {verify_mode}；预算 {format_cny(budget_cny)}。"); continue
        if lower == "/why":
            if last_decision is None: print("还没有路由记录。")
            else: print_decision(last_decision, configs)
            continue
        if lower == "/costs":
            print_costs(metrics, configs); continue
        if lower == "/history":
            print(f"当前正式记忆 {len(messages)} 条消息。"); continue
        if lower == "/where":
            print(f"记忆：{memory.path}\n路由与成本：{metrics.path}"); continue
        if lower == "/save":
            memory.save(messages); print("当前对话已保存。"); continue
        if lower == "/forget":
            confirm = input("输入 DELETE 确认删除正式对话记忆：").strip()
            if confirm == "DELETE":
                memory.forget(); messages = []; print("正式对话记忆已删除；成本记录保留。")
            else: print("已取消。")
            continue
        if lower == "/good": _rate(metrics, last_answer, 5); continue
        if lower == "/bad": _rate(metrics, last_answer, 1); continue
        if lower.startswith("/rate "):
            try: rating = int(lower.split(maxsplit=1)[1])
            except ValueError: print("用法：/rate 1-5"); continue
            if not 1 <= rating <= 5: print("评分必须是 1 到 5。"); continue
            _rate(metrics, last_answer, rating); continue

        if lower.startswith("/route"):
            prompt = user_input[len("/route"):].strip()
            if not prompt:
                prompt = input("要预览的问题：").strip()
            if not prompt:
                print("预览已取消。"); continue
            api_messages = build_api_messages(messages, prompt)
            decision = route_prompt(prompt, api_messages, configs, metrics.snapshot(), policy, budget_cny, settings.max_tokens)
            last_decision = decision
            print_decision(decision, configs)
            selected = active_provider if mode == "manual" else decision.selected_provider
            if mode == "manual": print(f"手动模式会覆盖选择，实际主模型：{selected}")
            fake_answer = "用于估算验证长度的候选答案。"
            verifier_messages = build_verifier_messages(prompt, fake_answer)
            primary_estimate = next(item.estimated_cost_cny for item in decision.rankings if item.provider_key == selected)
            plan = plan_verification(
                decision.with_selected(selected), selected, configs, metrics.snapshot(), verify_mode,
                max(0.0, budget_cny - primary_estimate), verifier_messages, settings.verifier_max_tokens,
            )
            if plan.enabled:
                print(f"预计会由 {plan.provider_key} 验证，预计 {format_cny(plan.estimated_cost_cny)}；原因：{plan.reason}")
            else:
                print(f"预计不验证：{plan.reason}")
            print("这是纯本地预览，没有发送 API 请求。")
            continue

        if lower.startswith("/compare"):
            prompt = user_input[len("/compare"):].strip()
            if not prompt:
                prompt = input("要比较的问题：").strip()
            if not prompt:
                print("比较已取消。"); continue
            task_type = classify_task(prompt).task_type
            api_messages = build_api_messages(messages, prompt)
            print("\n=== 临时比较（不写入正式记忆，但会记录真实成本） ===")
            for key in configs:
                try:
                    call = _call_and_record(key, "comparison", task_type, api_messages, settings.max_tokens, configs, clients, metrics)
                except Exception as exc:
                    print(f"\n[{key}] 请求失败：{exc}")
                    continue
                print(f"\n[{key} / {call.elapsed_seconds:.2f}s / {format_cny(call.cost.total)}]\n{call.result.answer}")
            continue

        prompt = user_input
        api_messages = build_api_messages(messages, prompt)
        decision = route_prompt(prompt, api_messages, configs, metrics.snapshot(), policy, budget_cny, settings.max_tokens)
        if mode == "manual":
            decision = decision.with_selected(active_provider)
        last_decision = decision
        print_decision(decision, configs)

        if mode == "auto":
            candidates = [item.provider_key for item in decision.rankings]
        else:
            candidates = [active_provider]
        if not settings.auto_fallback:
            candidates = candidates[:1]

        primary: CompletedCall | None = None
        failed_provider_keys: set[str] = set()
        for key in candidates:
            try:
                primary = _call_and_record(
                    key, "primary", decision.features.task_type, api_messages,
                    settings.max_tokens, configs, clients, metrics,
                )
            except Exception as exc:
                failed_provider_keys.add(key)
                print(f"{configs[key].display_name} 请求失败：{exc}", file=sys.stderr)
                continue
            _show_accounting_warning(primary)
            break
        if primary is None:
            print("所有候选都失败；本轮没有写入正式记忆。", file=sys.stderr)
            continue

        final_answer = primary.result.answer
        final_answer_provider = primary.provider_key
        actual_total = primary.cost.total
        print(f"主回答：{primary.provider_key}，{primary.elapsed_seconds:.2f}s，实际 {format_cny(primary.cost.total)}。")

        verifier_messages = build_verifier_messages(prompt, final_answer)
        plan = plan_verification(
            decision.with_selected(primary.provider_key), primary.provider_key,
            configs, metrics.snapshot(), verify_mode,
            max(0.0, budget_cny - actual_total), verifier_messages,
            settings.verifier_max_tokens,
            excluded_providers=failed_provider_keys,
        )
        if plan.enabled and plan.provider_key:
            print(f"启动验证：{plan.provider_key}；{plan.reason}。")
            try:
                verification = _call_and_record(
                    plan.provider_key, "verification", decision.features.task_type,
                    verifier_messages, settings.verifier_max_tokens,
                    configs, clients, metrics,
                )
            except Exception as exc:
                print(f"验证请求失败：{exc}。保留主回答。", file=sys.stderr)
            else:
                _show_accounting_warning(verification)
                actual_total += verification.cost.total
                outcome = parse_verification(
                    verification.result.answer, verification.result.finish_reason
                )
                final_answer = apply_verification(final_answer, outcome)
                final_answer_provider = _answer_provider_after_verification(
                    final_answer_provider, verification.provider_key, outcome
                )
                print(
                    f"验证结果：{outcome.status.upper()}，{format_cny(verification.cost.total)}；"
                    f"{outcome.note}"
                )
        else:
            print(f"本轮不验证：{plan.reason}。")

        candidate_memory = [*messages, {"role": "user", "content": prompt}, {"role": "assistant", "content": final_answer}]
        try:
            memory.save(candidate_memory)
        except OSError as exc:
            print(f"保存失败：{exc}。本轮不会进入当前记忆。", file=sys.stderr)
            print(f"\n助手（未保存）：{final_answer}")
            print(f"本轮本地计入成本：{format_cny(actual_total)} / 预算 {format_cny(budget_cny)}。")
            continue
        messages = candidate_memory
        last_answer = LastRatedAnswer(final_answer_provider, decision.features.task_type)
        print(f"\n助手：{final_answer}")
        print(f"本轮本地计入成本：{format_cny(actual_total)} / 预算 {format_cny(budget_cny)}。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chapter 06 cost-aware routing client")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true", help="run offline self-test")
    group.add_argument("--check-config", action="store_true", help="validate .env without API calls")
    group.add_argument("--check-memory", action="store_true", help="validate conversation memory")
    group.add_argument("--check-router", action="store_true", help="validate routing/cost state")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.self_test: run_self_test()
        elif args.check_config: run_config_check()
        elif args.check_memory: run_memory_check()
        elif args.check_router: run_router_check()
        else: run_chat()
    except (RuntimeError, MemoryErrorBase, MemoryFormatError, MetricsFormatError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
