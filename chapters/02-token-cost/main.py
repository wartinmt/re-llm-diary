"""《RE:从零开始的大模型研究日记》配套代码 02。

在连续对话客户端中观察 Token、上下文缓存与估算成本。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

BASE_URL: Final = "https://api.deepseek.com"
DEFAULT_MODEL: Final = "deepseek-v4-flash"
SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。"
ONE_MILLION: Final = Decimal("1000000")


@dataclass(frozen=True)
class PriceTable:
    """每 100 万 Token 的美元价格。"""

    cache_hit_input: Decimal
    cache_miss_input: Decimal
    output: Decimal

    @classmethod
    def from_env(cls) -> "PriceTable":
        return cls(
            cache_hit_input=read_decimal_env(
                "DEEPSEEK_PRICE_CACHE_HIT_USD_PER_M", "0.0028"
            ),
            cache_miss_input=read_decimal_env(
                "DEEPSEEK_PRICE_CACHE_MISS_USD_PER_M", "0.14"
            ),
            output=read_decimal_env("DEEPSEEK_PRICE_OUTPUT_USD_PER_M", "0.28"),
        )


@dataclass(frozen=True)
class UsageSnapshot:
    """一次 API 请求返回的 Token 用量。"""

    prompt_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    completion_tokens: int
    total_tokens: int

    def estimated_cost(self, prices: PriceTable) -> Decimal:
        return (
            Decimal(self.cache_hit_tokens) * prices.cache_hit_input
            + Decimal(self.cache_miss_tokens) * prices.cache_miss_input
            + Decimal(self.completion_tokens) * prices.output
        ) / ONE_MILLION


@dataclass
class SessionStats:
    """当前程序运行期间的累计用量。"""

    requests: int = 0
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")

    def add(self, usage: UsageSnapshot, cost: Decimal) -> None:
        self.requests += 1
        self.prompt_tokens += usage.prompt_tokens
        self.cache_hit_tokens += usage.cache_hit_tokens
        self.cache_miss_tokens += usage.cache_miss_tokens
        self.completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens
        self.estimated_cost_usd += cost

    def clear(self) -> None:
        self.requests = 0
        self.prompt_tokens = 0
        self.cache_hit_tokens = 0
        self.cache_miss_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.estimated_cost_usd = Decimal("0")


def read_decimal_env(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default).strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise RuntimeError(f"{name} 不是有效数字：{raw}") from exc
    if not value.is_finite():
        raise RuntimeError(f"{name} 必须是有限数字。")
    if value < 0:
        raise RuntimeError(f"{name} 不能小于 0。")
    return value


def read_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效整数：{raw}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} 必须大于 0。")
    return value


def load_settings(require_key: bool = True) -> tuple[str, str, PriceTable, int]:
    """读取与 main.py 同目录下的 .env。"""

    load_dotenv(Path(__file__).with_name(".env"))

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if require_key and not api_key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请复制 .env.example 为 .env，"
            "然后把自己的 DeepSeek API Key 填进去。"
        )

    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    max_tokens = read_positive_int_env("DEEPSEEK_MAX_TOKENS", 512)
    prices = PriceTable.from_env()
    return api_key, model, prices, max_tokens


def create_client() -> tuple[OpenAI, str, PriceTable, int]:
    api_key, model, prices, max_tokens = load_settings(require_key=True)
    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=60.0,
        max_retries=2,
    )
    return client, model, prices, max_tokens


def format_usd(value: Decimal) -> str:
    """极小金额也要保持可见。"""

    if value == 0:
        return "$0"
    if value < Decimal("0.000001"):
        return f"${value:.10f}"
    return f"${value:.8f}"


def print_prices(prices: PriceTable) -> None:
    print(
        "\n当前估算价格（美元 / 100 万 Token）：\n"
        f"  输入，缓存命中：{prices.cache_hit_input}\n"
        f"  输入，缓存未命中：{prices.cache_miss_input}\n"
        f"  输出：{prices.output}\n"
        "价格来自本地 .env。正式使用前请核对 DeepSeek 官方定价页。"
    )


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /stats       查看本次运行的累计 Token 与估算成本\n"
        "  /prices      查看当前用于估算的价格\n"
        "  /reset       只清空对话上下文，累计统计保留\n"
        "  /clearstats  只清空累计统计，对话上下文保留\n"
        "  /help        显示命令说明\n"
        "  /exit        退出程序\n"
    )


def print_round_usage(usage: UsageSnapshot, cost: Decimal) -> None:
    hit_rate = (
        Decimal(usage.cache_hit_tokens) / Decimal(usage.prompt_tokens) * 100
        if usage.prompt_tokens
        else Decimal("0")
    )
    print(
        "\n--- 本轮用量 ---\n"
        f"输入 Token：{usage.prompt_tokens} "
        f"（缓存命中 {usage.cache_hit_tokens}，未命中 {usage.cache_miss_tokens}）\n"
        f"缓存命中率：{hit_rate:.1f}%\n"
        f"输出 Token：{usage.completion_tokens}\n"
        f"总 Token：{usage.total_tokens}\n"
        f"估算成本：{format_usd(cost)}"
    )


def print_session_stats(stats: SessionStats) -> None:
    print(
        "\n=== 本次运行累计 ===\n"
        f"成功请求：{stats.requests}\n"
        f"输入 Token：{stats.prompt_tokens} "
        f"（缓存命中 {stats.cache_hit_tokens}，未命中 {stats.cache_miss_tokens}）\n"
        f"输出 Token：{stats.completion_tokens}\n"
        f"总 Token：{stats.total_tokens}\n"
        f"估算成本：{format_usd(stats.estimated_cost_usd)}"
    )


def normalize_usage(usage: object | None) -> UsageSnapshot:
    """兼容 SDK 字段缺失，并避免低估输入成本。"""

    if usage is None:
        raise RuntimeError("API 没有返回 usage，无法统计 Token。")

    def nonnegative_int(name: str, default: int = 0) -> int:
        raw = getattr(usage, name, default)
        try:
            value = int(raw or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(f"usage.{name} 不是有效整数。") from exc
        if value < 0:
            raise RuntimeError(f"usage.{name} 不能小于 0。")
        return value

    prompt = nonnegative_int("prompt_tokens")
    completion = nonnegative_int("completion_tokens")
    total = nonnegative_int("total_tokens", prompt + completion)
    hit = nonnegative_int("prompt_cache_hit_tokens")
    miss = nonnegative_int("prompt_cache_miss_tokens")

    # 如果 SDK 没有暴露完整缓存拆分，把无法解释的输入保守地视为未命中。
    explained = hit + miss
    if explained < prompt:
        miss += prompt - explained
    elif explained > prompt:
        overflow = explained - prompt
        miss = max(0, miss - overflow)
        if hit + miss > prompt:
            hit = max(0, prompt - miss)

    if total < prompt + completion:
        total = prompt + completion

    return UsageSnapshot(
        prompt_tokens=prompt,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        completion_tokens=completion,
        total_tokens=total,
    )


def request_answer(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, UsageSnapshot]:
    """发送完整上下文，并返回回答与实际 Token 用量。"""

    response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        stream=False,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )

    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("模型返回了空内容，请稍后重试。")

    return answer.strip(), normalize_usage(response.usage)


def run_self_test() -> None:
    """完全不访问网络，检查成本计算和累计逻辑。"""

    prices = PriceTable(
        cache_hit_input=Decimal("0.0028"),
        cache_miss_input=Decimal("0.14"),
        output=Decimal("0.28"),
    )
    usage = UsageSnapshot(
        prompt_tokens=1100,
        cache_hit_tokens=1000,
        cache_miss_tokens=100,
        completion_tokens=200,
        total_tokens=1300,
    )
    expected = Decimal("0.0000728")
    actual = usage.estimated_cost(prices)

    stats = SessionStats()
    stats.add(usage, actual)

    assert actual == expected, (actual, expected)
    assert stats.requests == 1
    assert stats.total_tokens == 1300
    assert stats.estimated_cost_usd == expected

    print("自检通过。")
    print("示例成本应为：$0.0000728")
    print(f"程序计算结果：{format_usd(actual)}")
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_config_check() -> None:
    """不发请求，只检查本地配置能否被读取。"""

    api_key, model, prices, max_tokens = load_settings(require_key=True)
    masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) >= 10 else "已读取"
    print("配置检查通过。")
    print(f"API Key：{masked}")
    print(f"模型：{model}")
    print(f"单次最大输出：{max_tokens} Token")
    print_prices(prices)
    print("这一步没有访问网络，也没有消耗 API 余额。")


def run_chat() -> None:
    client, model, prices, max_tokens = create_client()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    stats = SessionStats()

    print("DeepSeek Token 与成本观察器")
    print(f"当前模型：{model}")
    print(f"单次最大输出：{max_tokens} Token")
    print("输入 /help 查看命令。建议连续问三轮，再输入 /stats。")
    print_prices(prices)

    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return

        if not user_input:
            continue

        command = user_input.lower()
        if command in {"/exit", "exit", "quit"}:
            print("已退出。")
            return
        if command == "/help":
            print_help()
            continue
        if command == "/stats":
            print_session_stats(stats)
            continue
        if command == "/prices":
            print_prices(prices)
            continue
        if command == "/reset":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("对话上下文已清空；累计统计仍然保留。")
            continue
        if command == "/clearstats":
            stats.clear()
            print("累计统计已清空；对话上下文仍然保留。")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            answer, usage = request_answer(client, model, messages, max_tokens)
        except OpenAIError as exc:
            messages.pop()
            print(f"\n请求失败：{exc}", file=sys.stderr)
            print(
                "请检查 API Key、账户余额、网络和模型名称后重试。",
                file=sys.stderr,
            )
            continue
        except RuntimeError as exc:
            messages.pop()
            print(f"\n运行失败：{exc}", file=sys.stderr)
            continue

        cost = usage.estimated_cost(prices)
        stats.add(usage, cost)

        print(f"\nDeepSeek：{answer}")
        print_round_usage(usage, cost)
        messages.append({"role": "assistant", "content": answer})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="观察 DeepSeek 连续对话中的 Token、缓存与估算成本。"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--self-test",
        action="store_true",
        help="不联网，检查本地成本计算逻辑。",
    )
    group.add_argument(
        "--check-config",
        action="store_true",
        help="不发 API 请求，只检查 .env 配置。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
    elif args.check_config:
        run_config_check()
    else:
        run_chat()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
