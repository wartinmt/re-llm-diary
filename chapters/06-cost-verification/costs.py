"""Token usage estimation and price calculation.

All prices are expressed in CNY per one million tokens. Estimation is only a
routing hint. Actual accounting uses the provider response's usage fields.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PriceTable:
    cache_hit_input_per_million: float
    cache_miss_input_per_million: float
    output_per_million: float
    currency: str = "CNY"

    def __post_init__(self) -> None:
        values = (
            self.cache_hit_input_per_million,
            self.cache_miss_input_per_million,
            self.output_per_million,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("模型价格必须是有限的非负数。")


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    def __post_init__(self) -> None:
        values = (
            self.prompt_tokens,
            self.completion_tokens,
            self.cache_hit_tokens,
            self.cache_miss_tokens,
        )
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("Token 用量必须是非负整数。")
        if self.cache_hit_tokens + self.cache_miss_tokens > self.prompt_tokens:
            raise ValueError("缓存命中与未命中 Token 不能超过输入 Token。")

    @property
    def uncategorized_prompt_tokens(self) -> int:
        return self.prompt_tokens - self.cache_hit_tokens - self.cache_miss_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def with_uncategorized_as_miss(self) -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cache_hit_tokens=self.cache_hit_tokens,
            cache_miss_tokens=self.cache_miss_tokens + self.uncategorized_prompt_tokens,
        )


@dataclass(frozen=True)
class CostBreakdown:
    cache_hit_input: float
    cache_miss_input: float
    output: float
    total: float
    currency: str = "CNY"


def calculate_cost(price: PriceTable, usage: TokenUsage) -> CostBreakdown:
    normalized = usage.with_uncategorized_as_miss()
    divisor = 1_000_000.0
    cache_hit = normalized.cache_hit_tokens * price.cache_hit_input_per_million / divisor
    cache_miss = normalized.cache_miss_tokens * price.cache_miss_input_per_million / divisor
    output = normalized.completion_tokens * price.output_per_million / divisor
    return CostBreakdown(
        cache_hit_input=cache_hit,
        cache_miss_input=cache_miss,
        output=output,
        total=cache_hit + cache_miss + output,
        currency=price.currency,
    )


def estimate_text_tokens(text: str) -> int:
    """A deliberately simple offline approximation for routing previews.

    Chinese characters are often close to one token each, while Latin text is
    usually denser. The estimate is not used for billing.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, math.ceil(cjk * 1.05 + other / 3.6))


def estimate_message_tokens(messages: Iterable[Mapping[str, str]]) -> int:
    total = 0
    for message in messages:
        total += 4  # small role/message framing allowance
        total += estimate_text_tokens(str(message.get("content", "")))
    return max(1, total + 2)


def estimate_usage(
    messages: list[dict[str, str]],
    task_type: str,
    complexity: float,
    max_tokens: int,
    observed_cache_hit_ratio: float = 0.0,
    observed_average_output: float | None = None,
) -> TokenUsage:
    prompt = estimate_message_tokens(messages)
    ratio = min(1.0, max(0.0, observed_cache_hit_ratio))
    hit = int(prompt * ratio)
    miss = prompt - hit

    if observed_average_output is not None and observed_average_output > 0:
        expected_output = int(observed_average_output)
    else:
        base = {
            "quick": 90,
            "analysis": 420,
            "code": 500,
            "creative": 360,
            "general": 240,
        }.get(task_type, 240)
        expected_output = int(base * (0.72 + 0.72 * complexity))
    expected_output = max(24, min(max_tokens, expected_output))
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=expected_output,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
    )


def format_cny(value: float) -> str:
    if value >= 0.01:
        return f"¥{value:.4f}"
    if value >= 0.0001:
        return f"¥{value:.6f}"
    return f"¥{value:.8f}"
