"""《RE:从零开始的大模型研究日记》配套代码 06。"""
from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
import uuid
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
from journal import JournalError, JournalFormatError, RecoveryBlocked, TaskJournal
from recovery import recover_all_local, recover_local_task
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
    journal_path: Path
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
        journal_path=_resolve_local_path(os.getenv("TASK_JOURNAL_PATH", "data/task_journal.jsonl")),
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
        "  /tasks /task ID /replay ID      查看任务与只读重放\n"
        "  /recover ID                     只做不调用 API 的本地恢复\n"
        "  /retry ID CONFIRM               为远端未知任务创建新 attempt\n"
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
    journal = TaskJournal(root / "task_journal.jsonl")
    task_id, attempt = journal.create_task("离线恢复测试")
    call_id = "offline-primary"
    journal.append(task_id, attempt, "request_sent", {"call_id": call_id, "role": "primary", "provider": "cheap"})
    journal.append(task_id, attempt, "response_received", {"call_id": call_id, "role": "primary", "provider": "cheap", "answer": "离线答案"})
    recovered = recover_local_task(journal, ConversationStore(root / "recovered.json"), task_id)
    if recovered.answer != "离线答案" or journal.plan(task_id).status != "complete":
        raise RuntimeError("中断恢复与重放自检失败。")

    print("离线自检通过：记忆、路由、成本、任务流水账与本地恢复均正常。")
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



def run_journal_check(repair: bool = False) -> None:
    settings = load_settings(require_provider=False)
    journal = TaskJournal(settings.journal_path)
    if repair:
        backup = journal.repair_trailing_partial()
        if backup:
            print(f"已仅移除末尾未完成事件，原文件备份为：{backup}")
        else:
            print("没有发现可修复的末尾残片。")
    events = journal.load()
    print(f"任务流水账检查通过：{journal.path}，{len(events)} 个事件，{len(journal.task_ids())} 个任务。")
    for plan in journal.pending_plans():
        print(f"  {plan.task_id} attempt={plan.attempt} {plan.status}: {plan.reason}")


def run_replay(task_id: str) -> None:
    settings = load_settings(require_provider=False)
    journal = TaskJournal(settings.journal_path)
    for line in journal.replay_lines(task_id):
        print(line)
    plan = journal.plan(task_id)
    print(f"状态：{plan.status}。{plan.reason}")
    print("重放只读取本地流水账，没有发送 API 请求，也没有修改任何文件。")


def run_demo_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        journal = TaskJournal(root / "task_journal.jsonl")
        memory = ConversationStore(root / "conversation.json")
        task_id, attempt = journal.create_task("请解释为什么恢复不能盲目重试。")
        call_id = "demo-primary"
        journal.append(task_id, attempt, "request_sent", {"call_id": call_id, "role": "primary", "provider": "demo"})
        journal.append(task_id, attempt, "response_received", {"call_id": call_id, "role": "primary", "provider": "demo", "answer": "因为请求可能已经成功，盲目重试会重复付费或重复副作用。"})
        print(f"模拟崩溃前状态：{journal.plan(task_id).status}")
        result = recover_local_task(journal, memory, task_id)
        print(f"恢复后状态：{journal.plan(task_id).status}")
        print(f"恢复答案：{result.answer}")
        print("演示只使用临时目录和合成回答，没有联网、没有调用 API。")


def _usage_payload(call: CompletedCall) -> dict[str, object]:
    usage = call.result.usage
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cache_hit_tokens": usage.cache_hit_tokens,
        "cache_miss_tokens": usage.cache_miss_tokens,
    }


def _execute_prompt_turn(
    prompt: str,
    *,
    messages: list[dict[str, str]],
    memory: ConversationStore,
    journal: TaskJournal,
    metrics: RoutingMetricsStore,
    configs: Mapping[str, ProviderConfig],
    clients: Mapping[str, Any],
    settings: AppSettings,
    mode: str,
    active_provider: str,
    policy: str,
    verify_mode: str,
    budget_cny: float,
    existing_task_id: str | None = None,
    existing_attempt: int | None = None,
) -> tuple[list[dict[str, str]], LastRatedAnswer | None, RouteDecision | None]:
    if existing_task_id is None:
        task_id, attempt = journal.create_task(prompt)
    else:
        task_id = existing_task_id
        attempt = existing_attempt or journal.latest_attempt(task_id)
    api_messages = build_api_messages(messages, prompt)
    decision = route_prompt(prompt, api_messages, configs, metrics.snapshot(), policy, budget_cny, settings.max_tokens)
    if mode == "manual":
        decision = decision.with_selected(active_provider)
    journal.append(task_id, attempt, "route_selected", {
        "provider": decision.selected_provider,
        "task_type": decision.features.task_type,
        "policy": policy,
    })
    print_decision(decision, configs)

    candidates = [item.provider_key for item in decision.rankings] if mode == "auto" else [active_provider]
    if not settings.auto_fallback:
        candidates = candidates[:1]

    primary: CompletedCall | None = None
    failed_provider_keys: set[str] = set()
    for key in candidates:
        call_id = uuid.uuid4().hex[:12]
        journal.append(task_id, attempt, "request_sent", {
            "call_id": call_id, "role": "primary", "provider": key,
        })
        try:
            primary = _call_and_record(
                key, "primary", decision.features.task_type, api_messages,
                settings.max_tokens, configs, clients, metrics,
            )
        except Exception as exc:
            failed_provider_keys.add(key)
            journal.append(task_id, attempt, "request_outcome_unknown", {
                "call_id": call_id, "role": "primary", "provider": key,
                "error": str(exc),
            })
            print(
                f"{configs[key].display_name} 请求中断：{exc}。结果可能未知；"
                "为避免重复调用，本轮不会自动切换下一个模型。",
                file=sys.stderr,
            )
            return messages, None, decision
        _show_accounting_warning(primary)
        journal.append(task_id, attempt, "response_received", {
            "call_id": call_id, "role": "primary", "provider": key,
            "answer": primary.result.answer,
            "finish_reason": primary.result.finish_reason,
            "cost_cny": primary.cost.total,
            "usage": _usage_payload(primary),
        })
        break
    if primary is None:
        return messages, None, decision

    final_answer = primary.result.answer
    final_answer_provider = primary.provider_key
    actual_total = primary.cost.total
    print(f"主回答：{primary.provider_key}，{primary.elapsed_seconds:.2f}s，实际 {format_cny(primary.cost.total)}。")

    verifier_messages = build_verifier_messages(prompt, final_answer)
    plan = plan_verification(
        decision.with_selected(primary.provider_key), primary.provider_key,
        configs, metrics.snapshot(), verify_mode,
        max(0.0, budget_cny - actual_total), verifier_messages,
        settings.verifier_max_tokens, excluded_providers=failed_provider_keys,
    )
    if plan.enabled and plan.provider_key:
        verifier_call_id = uuid.uuid4().hex[:12]
        journal.append(task_id, attempt, "request_sent", {
            "call_id": verifier_call_id, "role": "verification", "provider": plan.provider_key,
        })
        print(f"启动验证：{plan.provider_key}；{plan.reason}。")
        try:
            verification = _call_and_record(
                plan.provider_key, "verification", decision.features.task_type,
                verifier_messages, settings.verifier_max_tokens,
                configs, clients, metrics,
            )
        except Exception as exc:
            journal.append(task_id, attempt, "request_outcome_unknown", {
                "call_id": verifier_call_id, "role": "verification",
                "provider": plan.provider_key, "error": str(exc),
            })
            print("验证结果未知；不会重试验证，保留已完整保存的主回答。", file=sys.stderr)
        else:
            _show_accounting_warning(verification)
            journal.append(task_id, attempt, "response_received", {
                "call_id": verifier_call_id, "role": "verification",
                "provider": plan.provider_key, "answer": verification.result.answer,
                "finish_reason": verification.result.finish_reason,
                "cost_cny": verification.cost.total, "usage": _usage_payload(verification),
            })
            actual_total += verification.cost.total
            outcome = parse_verification(verification.result.answer, verification.result.finish_reason)
            final_answer = apply_verification(final_answer, outcome)
            final_answer_provider = _answer_provider_after_verification(
                final_answer_provider, verification.provider_key, outcome
            )
            print(f"验证结果：{outcome.status.upper()}，{format_cny(verification.cost.total)}；{outcome.note}")
    else:
        print(f"本轮不验证：{plan.reason}。")

    journal.append(task_id, attempt, "final_answer_ready", {
        "answer": final_answer, "provider": final_answer_provider,
        "cost_cny": actual_total,
    })
    candidate_memory = [
        *messages,
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": final_answer},
    ]
    try:
        memory.save(candidate_memory)
    except OSError as exc:
        print(f"保存失败：{exc}。完整答案已在任务流水账中，可在下次启动时本地恢复。", file=sys.stderr)
        print(f"\n助手（尚未进入正式记忆）：{final_answer}")
        return messages, None, decision
    journal.append(task_id, attempt, "memory_committed", {"message_count": len(candidate_memory)})
    journal.append(task_id, attempt, "task_completed", {"answer_provider": final_answer_provider})
    print(f"\n助手：{final_answer}")
    print(f"任务 {task_id} 已完成。本轮本地计入成本：{format_cny(actual_total)} / 预算 {format_cny(budget_cny)}。")
    return candidate_memory, LastRatedAnswer(final_answer_provider, decision.features.task_type), decision

def run_chat() -> None:
    settings = load_settings(require_provider=True)
    configs = settings.providers
    clients = create_clients(configs)
    memory = ConversationStore(settings.memory_path)
    messages = memory.load()
    metrics = RoutingMetricsStore(settings.metrics_path)
    metrics.load()
    journal = TaskJournal(settings.journal_path)
    journal.load()

    recovered = recover_all_local(journal, memory)
    if recovered:
        messages = memory.load()
        print(f"启动时完成 {len(recovered)} 个纯本地恢复；没有发送 API 请求。")
    for plan in journal.pending_plans():
        print(f"待处理任务 {plan.task_id}: {plan.status}。{plan.reason}")

    mode = settings.initial_mode
    active_provider = settings.default_provider
    policy = settings.initial_policy
    verify_mode = settings.verify_mode
    budget_cny = settings.turn_budget_cny
    last_decision: RouteDecision | None = None
    last_answer: LastRatedAnswer | None = None

    print("可恢复的成本与验证路由客户端")
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
            memory.save(messages); print("已保存并退出。"); return
        if lower == "/help": print_help(); continue
        if lower == "/auto": mode = "auto"; print("已进入自动路由模式。"); continue
        if lower.startswith("/use "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in configs: print(f"模型 {requested!r} 未配置。"); continue
            mode = "manual"; active_provider = requested
            print(f"已进入手动模式：{configs[requested].display_name} / {configs[requested].model}。"); continue
        if lower.startswith("/policy "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in POLICIES: print("策略只能是 balanced、economy 或 trust。"); continue
            policy = requested; print(f"策略已改为 {policy}。"); continue
        if lower.startswith("/verify "):
            requested = lower.split(maxsplit=1)[1]
            if requested not in VERIFY_MODES: print("验证模式只能是 auto、on 或 off。"); continue
            verify_mode = requested; print(f"验证模式已改为 {verify_mode}。"); continue
        if lower.startswith("/budget "):
            raw = user_input.split(maxsplit=1)[1]
            try: value = float(raw)
            except ValueError: print("预算必须是人民币数字，例如 /budget 0.05。"); continue
            if not math.isfinite(value) or value <= 0: print("预算必须是有限且大于 0 的数字。"); continue
            budget_cny = value; print(f"单轮预算已改为 {format_cny(value)}。"); continue
        if lower == "/mode":
            print(f"模式 {mode}；手动模型 {active_provider}；策略 {policy}；验证 {verify_mode}；预算 {format_cny(budget_cny)}。"); continue
        if lower == "/why":
            if last_decision is None: print("还没有路由记录。")
            else: print_decision(last_decision, configs)
            continue
        if lower == "/costs": print_costs(metrics, configs); continue
        if lower == "/history": print(f"当前正式记忆 {len(messages)} 条消息。"); continue
        if lower == "/where":
            print(f"记忆：{memory.path}\n路由与成本：{metrics.path}\n任务流水账：{journal.path}"); continue
        if lower == "/save": memory.save(messages); print("当前对话已保存。"); continue
        if lower == "/tasks":
            if not journal.task_ids(): print("还没有任务记录。"); continue
            for task_id in journal.task_ids():
                plan = journal.plan(task_id)
                print(f"{task_id} attempt={plan.attempt} {plan.status} - {plan.reason}")
            continue
        if lower.startswith("/task ") or lower.startswith("/replay "):
            task_id = user_input.split(maxsplit=1)[1].strip()
            for line in journal.replay_lines(task_id): print(line)
            plan = journal.plan(task_id); print(f"状态：{plan.status}。{plan.reason}")
            print("这是只读重放，没有发送 API 请求。"); continue
        if lower.startswith("/recover "):
            task_id = user_input.split(maxsplit=1)[1].strip()
            result = recover_local_task(journal, memory, task_id)
            messages = memory.load()
            print(f"任务 {task_id} 已完成本地恢复；修改正式记忆：{result.changed_memory}。"); continue
        if lower.startswith("/retry "):
            parts = user_input.split()
            if len(parts) != 3:
                print("用法：/retry TASK_ID CONFIRM"); continue
            task_id, confirmation = parts[1], parts[2]
            attempt, prompt = journal.authorize_retry(task_id, confirmation)
            messages, last_answer, last_decision = _execute_prompt_turn(
                prompt, messages=messages, memory=memory, journal=journal,
                metrics=metrics, configs=configs, clients=clients, settings=settings,
                mode=mode, active_provider=active_provider, policy=policy,
                verify_mode=verify_mode, budget_cny=budget_cny,
                existing_task_id=task_id, existing_attempt=attempt,
            )
            continue
        if lower == "/forget":
            confirm = input("输入 DELETE 确认删除正式对话记忆：").strip()
            if confirm == "DELETE": memory.forget(); messages = []; print("正式对话记忆已删除；流水账和成本记录保留。")
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
            prompt = user_input[len("/route"):].strip() or input("要预览的问题：").strip()
            if not prompt: print("预览已取消。"); continue
            api_messages = build_api_messages(messages, prompt)
            decision = route_prompt(prompt, api_messages, configs, metrics.snapshot(), policy, budget_cny, settings.max_tokens)
            last_decision = decision; print_decision(decision, configs)
            print("这是纯本地预览，没有创建任务、发送 API 或修改流水账。"); continue

        if lower.startswith("/compare"):
            prompt = user_input[len("/compare"):].strip() or input("要比较的问题：").strip()
            if not prompt: print("比较已取消。"); continue
            task_type = classify_task(prompt).task_type
            api_messages = build_api_messages(messages, prompt)
            print("\n=== 临时比较（不写入正式记忆，但会记录真实成本） ===")
            for key in configs:
                try:
                    call = _call_and_record(key, "comparison", task_type, api_messages, settings.max_tokens, configs, clients, metrics)
                except Exception as exc: print(f"\n[{key}] 请求失败：{exc}"); continue
                print(f"\n[{key} / {call.elapsed_seconds:.2f}s / {format_cny(call.cost.total)}]\n{call.result.answer}")
            continue

        messages, last_answer, last_decision = _execute_prompt_turn(
            user_input, messages=messages, memory=memory, journal=journal,
            metrics=metrics, configs=configs, clients=clients, settings=settings,
            mode=mode, active_provider=active_provider, policy=policy,
            verify_mode=verify_mode, budget_cny=budget_cny,
        )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chapter 07 interruption recovery client")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-test", action="store_true", help="run offline self-test")
    group.add_argument("--check-config", action="store_true", help="validate .env without API calls")
    group.add_argument("--check-memory", action="store_true", help="validate conversation memory")
    group.add_argument("--check-router", action="store_true", help="validate routing/cost state")
    group.add_argument("--check-journal", action="store_true", help="validate task journal")
    group.add_argument("--repair-journal", action="store_true", help="repair only a trailing partial event")
    group.add_argument("--replay", metavar="TASK_ID", help="read-only replay for one task")
    group.add_argument("--demo-recovery", action="store_true", help="offline interruption/recovery demo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.self_test: run_self_test()
        elif args.check_config: run_config_check()
        elif args.check_memory: run_memory_check()
        elif args.check_router: run_router_check()
        elif args.check_journal: run_journal_check()
        elif args.repair_journal: run_journal_check(repair=True)
        elif args.replay: run_replay(args.replay)
        elif args.demo_recovery: run_demo_recovery()
        else: run_chat()
    except (
        RuntimeError, MemoryErrorBase, MemoryFormatError, MetricsFormatError,
        JournalError, JournalFormatError, RecoveryBlocked, OSError,
    ) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
