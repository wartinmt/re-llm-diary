"""Persistent routing observations, token usage, costs, and ratings."""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costs import TokenUsage

SCHEMA_VERSION = 2
TASK_TYPES = {"quick", "analysis", "code", "creative", "general"}
CALL_ROLES = {"primary", "verification", "comparison"}


class MetricsFormatError(RuntimeError):
    """The routing state exists but is unsafe or unsupported."""


@dataclass
class ProviderMetrics:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_latency: float = 0.0
    rating_sum: int = 0
    rating_count: int = 0
    task_rating_sum: dict[str, int] = field(default_factory=dict)
    task_rating_count: dict[str, int] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    total_cost_cny: float = 0.0
    primary_calls: int = 0
    verification_calls: int = 0
    comparison_calls: int = 0
    primary_cost_cny: float = 0.0
    verification_cost_cny: float = 0.0
    comparison_cost_cny: float = 0.0

    # Role-specific observations keep comparison/verification calls from
    # distorting future primary-answer estimates. These fields have defaults so
    # state files written by the first Chapter 06 build remain readable.
    primary_successes: int = 0
    primary_prompt_tokens: int = 0
    primary_completion_tokens: int = 0
    primary_cache_hit_tokens: int = 0
    primary_cache_miss_tokens: int = 0
    verification_successes: int = 0
    verification_prompt_tokens: int = 0
    verification_completion_tokens: int = 0
    verification_cache_hit_tokens: int = 0
    verification_cache_miss_tokens: int = 0

    @property
    def average_latency(self) -> float | None:
        return self.total_latency / self.attempts if self.attempts else None

    @property
    def reliability(self) -> float:
        return (self.successes + 2.0) / (self.attempts + 3.0)

    def normalized_quality(self, task_type: str) -> float:
        count = self.task_rating_count.get(task_type, 0)
        if count:
            average = self.task_rating_sum.get(task_type, 0) / count
            return (average - 1.0) / 4.0
        if self.rating_count:
            average = self.rating_sum / self.rating_count
            return (average - 1.0) / 4.0
        return 0.65

    def latency_score(self, speed_hint: float) -> float:
        if self.average_latency is None:
            return speed_hint
        return 1.0 / (1.0 + self.average_latency / 10.0)

    @property
    def exploration_score(self) -> float:
        return 1.0 / math.sqrt(self.attempts + 1.0)

    @property
    def cache_hit_ratio(self) -> float:
        categorized = self.cache_hit_tokens + self.cache_miss_tokens
        return self.cache_hit_tokens / categorized if categorized else 0.0

    @property
    def average_output_tokens(self) -> float | None:
        return self.completion_tokens / self.successes if self.successes else None

    def cache_hit_ratio_for_role(self, role: str) -> float:
        if role == "primary":
            hit, miss = self.primary_cache_hit_tokens, self.primary_cache_miss_tokens
        elif role == "verification":
            hit = self.verification_cache_hit_tokens
            miss = self.verification_cache_miss_tokens
        else:
            return self.cache_hit_ratio
        categorized = hit + miss
        return hit / categorized if categorized else 0.0

    def average_output_tokens_for_role(self, role: str) -> float | None:
        if role == "primary":
            if self.primary_successes:
                return self.primary_completion_tokens / self.primary_successes
            return None
        if role == "verification":
            if self.verification_successes:
                return self.verification_completion_tokens / self.verification_successes
            return None
        return self.average_output_tokens


@dataclass(frozen=True)
class RoutingSnapshot:
    providers: dict[str, ProviderMetrics]

    def for_provider(self, key: str) -> ProviderMetrics:
        return self.providers.get(key, ProviderMetrics())

    @property
    def total_cost_cny(self) -> float:
        return sum(item.total_cost_cny for item in self.providers.values())


@dataclass
class RoutingMetricsStore:
    path: Path
    _providers: dict[str, ProviderMetrics] = field(default_factory=dict)

    def load(self) -> RoutingSnapshot:
        if not self.path.exists():
            self._providers = {}
            return self.snapshot()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MetricsFormatError(
                f"无法读取路由记录：{self.path}\n原文件没有被覆盖，请先改名备份。"
            ) from exc
        self._providers = self._validate(payload)
        return self.snapshot()

    def snapshot(self) -> RoutingSnapshot:
        return RoutingSnapshot(
            providers={
                key: ProviderMetrics(**asdict(value))
                for key, value in self._providers.items()
            }
        )

    def record_attempt(
        self,
        provider_key: str,
        task_type: str,
        role: str,
        success: bool,
        elapsed_seconds: float,
        usage: TokenUsage | None = None,
        cost_cny: float = 0.0,
    ) -> None:
        if task_type not in TASK_TYPES:
            raise ValueError(f"未知任务类型：{task_type}")
        if role not in CALL_ROLES:
            raise ValueError(f"未知调用角色：{role}")
        if (
            not math.isfinite(elapsed_seconds)
            or not math.isfinite(cost_cny)
            or elapsed_seconds < 0
            or cost_cny < 0
        ):
            raise ValueError("耗时和成本必须是有限的非负数。")
        usage = usage or TokenUsage()
        item = self._providers.setdefault(provider_key, ProviderMetrics())
        item.attempts += 1
        item.total_latency += elapsed_seconds
        if success:
            item.successes += 1
        else:
            item.failures += 1
        item.prompt_tokens += usage.prompt_tokens
        item.completion_tokens += usage.completion_tokens
        item.cache_hit_tokens += usage.cache_hit_tokens
        item.cache_miss_tokens += usage.cache_miss_tokens
        item.total_cost_cny += cost_cny
        if role == "primary":
            item.primary_calls += 1
            item.primary_cost_cny += cost_cny
            if success:
                item.primary_successes += 1
            item.primary_prompt_tokens += usage.prompt_tokens
            item.primary_completion_tokens += usage.completion_tokens
            item.primary_cache_hit_tokens += usage.cache_hit_tokens
            item.primary_cache_miss_tokens += usage.cache_miss_tokens
        elif role == "verification":
            item.verification_calls += 1
            item.verification_cost_cny += cost_cny
            if success:
                item.verification_successes += 1
            item.verification_prompt_tokens += usage.prompt_tokens
            item.verification_completion_tokens += usage.completion_tokens
            item.verification_cache_hit_tokens += usage.cache_hit_tokens
            item.verification_cache_miss_tokens += usage.cache_miss_tokens
        else:
            item.comparison_calls += 1
            item.comparison_cost_cny += cost_cny
        self.save()

    def record_rating(self, provider_key: str, task_type: str, rating: int) -> None:
        if task_type not in TASK_TYPES:
            raise ValueError(f"未知任务类型：{task_type}")
        if not 1 <= rating <= 5:
            raise ValueError("评分必须位于 1 到 5 之间。")
        item = self._providers.setdefault(provider_key, ProviderMetrics())
        item.rating_sum += rating
        item.rating_count += 1
        item.task_rating_sum[task_type] = item.task_rating_sum.get(task_type, 0) + rating
        item.task_rating_count[task_type] = item.task_rating_count.get(task_type, 0) + 1
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "providers": {key: asdict(value) for key, value in self._providers.items()},
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate(payload: Any) -> dict[str, ProviderMetrics]:
        if not isinstance(payload, dict):
            raise MetricsFormatError("路由记录顶层必须是 JSON 对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise MetricsFormatError(
                f"不支持的路由记录版本：{payload.get('schema_version')!r}。"
                "这是独立章节，请备份旧文件后使用本章自己的 data 目录。"
            )
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            raise MetricsFormatError("providers 必须是对象。")
        result: dict[str, ProviderMetrics] = {}
        for key, raw in providers.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(raw, dict):
                raise MetricsFormatError("provider 记录格式无效。")
            try:
                item = ProviderMetrics(**raw)
            except TypeError as exc:
                raise MetricsFormatError(f"{key} 的字段不完整或多余。") from exc
            RoutingMetricsStore._validate_item(key, item)
            result[key] = item
        return result

    @staticmethod
    def _validate_item(key: str, item: ProviderMetrics) -> None:
        integer_names = (
            "attempts", "successes", "failures", "rating_sum", "rating_count",
            "prompt_tokens", "completion_tokens", "cache_hit_tokens",
            "cache_miss_tokens", "primary_calls", "verification_calls",
            "comparison_calls", "primary_successes", "primary_prompt_tokens",
            "primary_completion_tokens", "primary_cache_hit_tokens",
            "primary_cache_miss_tokens", "verification_successes",
            "verification_prompt_tokens", "verification_completion_tokens",
            "verification_cache_hit_tokens", "verification_cache_miss_tokens",
        )
        for name in integer_names:
            value = getattr(item, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MetricsFormatError(f"{key}.{name} 必须是非负整数。")

        float_names = (
            "total_latency", "total_cost_cny", "primary_cost_cny",
            "verification_cost_cny", "comparison_cost_cny",
        )
        for name in float_names:
            value = getattr(item, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MetricsFormatError(f"{key}.{name} 必须是数字。")
            if not math.isfinite(float(value)) or value < 0:
                raise MetricsFormatError(f"{key}.{name} 必须是有限的非负数。")

        for name in ("task_rating_sum", "task_rating_count"):
            mapping = getattr(item, name)
            if not isinstance(mapping, dict):
                raise MetricsFormatError(f"{key}.{name} 必须是对象。")
            for task_type, value in mapping.items():
                if task_type not in TASK_TYPES:
                    raise MetricsFormatError(f"{key}.{name} 含未知任务类型。")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise MetricsFormatError(f"{key}.{name} 的值必须是非负整数。")

        if item.successes + item.failures != item.attempts:
            raise MetricsFormatError(f"{key} 的成功与失败计数不一致。")
        if item.primary_calls + item.verification_calls + item.comparison_calls != item.attempts:
            raise MetricsFormatError(f"{key} 的调用角色计数不一致。")
        if item.primary_successes > item.primary_calls:
            raise MetricsFormatError(f"{key} 的主回答成功数超过主回答调用数。")
        if item.verification_successes > item.verification_calls:
            raise MetricsFormatError(f"{key} 的验证成功数超过验证调用数。")
        if item.cache_hit_tokens + item.cache_miss_tokens > item.prompt_tokens:
            raise MetricsFormatError(f"{key} 的缓存 Token 超过输入 Token。")
        if item.primary_cache_hit_tokens + item.primary_cache_miss_tokens > item.primary_prompt_tokens:
            raise MetricsFormatError(f"{key} 的主回答缓存 Token 超过输入 Token。")
        if (
            item.verification_cache_hit_tokens + item.verification_cache_miss_tokens
            > item.verification_prompt_tokens
        ):
            raise MetricsFormatError(f"{key} 的验证缓存 Token 超过输入 Token。")
        if item.rating_count != sum(item.task_rating_count.values()):
            raise MetricsFormatError(f"{key} 的评分计数不一致。")
        if item.rating_sum != sum(item.task_rating_sum.values()):
            raise MetricsFormatError(f"{key} 的评分总和不一致。")
        if not math.isclose(
            item.total_cost_cny,
            item.primary_cost_cny + item.verification_cost_cny + item.comparison_cost_cny,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise MetricsFormatError(f"{key} 的分栏成本与总成本不一致。")
