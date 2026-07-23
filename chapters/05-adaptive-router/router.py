"""透明、可解释、会从运行记录中更新的本地路由器。"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
VALID_BUCKETS = {"general", "analysis", "code", "writing"}
VALID_POLICIES = {"balanced", "fast", "quality"}
VALID_MODES = {"auto", "manual"}

_POLICY_WEIGHTS = {
    "balanced": {"quality": 0.40, "reliability": 0.30, "speed": 0.20, "exploration": 0.10},
    "fast": {"quality": 0.20, "reliability": 0.25, "speed": 0.45, "exploration": 0.10},
    "quality": {"quality": 0.60, "reliability": 0.25, "speed": 0.05, "exploration": 0.10},
}

_CODE_MARKERS = (
    "```", "traceback", "报错", "代码", "函数", "python", "swift",
    "javascript", "typescript", "sql", "debug", "bug", "编译", "api",
)
_WRITING_MARKERS = (
    "改写", "润色", "文案", "标题", "写一篇", "故事", "语气", "邮件",
    "创作", "脚本", "小红书", "总结成",
)
_ANALYSIS_MARKERS = (
    "分析", "为什么", "比较", "权衡", "评估", "推理", "设计", "规划",
    "风险", "利弊", "架构", "决策", "原因", "可行性",
)


class RouterError(RuntimeError):
    """路由状态或操作不合法。"""


class RouterFormatError(RouterError):
    """路由状态文件存在，但格式不受支持。"""


@dataclass(frozen=True)
class TaskFeatures:
    bucket: str
    signals: tuple[str, ...]


@dataclass
class MetricStats:
    attempts: int = 0
    successes: int = 0
    total_latency_seconds: float = 0.0
    ratings_count: int = 0
    ratings_sum: int = 0

    def record_result(self, success: bool, latency_seconds: float) -> None:
        if not math.isfinite(latency_seconds) or latency_seconds < 0:
            raise RouterError("响应时间必须是大于等于 0 的有限数字。")
        self.attempts += 1
        if success:
            self.successes += 1
            self.total_latency_seconds += latency_seconds

    def add_rating(self, rating: int) -> None:
        if rating not in {1, 2, 3, 4, 5}:
            raise RouterError("评分必须是 1 到 5 的整数。")
        self.ratings_count += 1
        self.ratings_sum += rating

    def reliability_score(self) -> float:
        # Beta(2,1) 先验：数据很少时不因一次失败就降到 0。
        return (self.successes + 2) / (self.attempts + 3)

    def quality_score(self) -> float:
        # 两次 3.5 分的弱先验，最终归一化到 0..1。
        return ((self.ratings_sum + 7.0) / (self.ratings_count + 2)) / 5.0

    def average_latency(self) -> float | None:
        if self.successes <= 0:
            return None
        return self.total_latency_seconds / self.successes

    def speed_score(self) -> float:
        latency = self.average_latency()
        if latency is None:
            return 0.5
        return 1.0 / (1.0 + latency / 5.0)

    def exploration_score(self) -> float:
        return 1.0 / math.sqrt(self.attempts + 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "total_latency_seconds": round(self.total_latency_seconds, 6),
            "ratings_count": self.ratings_count,
            "ratings_sum": self.ratings_sum,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "MetricStats":
        if not isinstance(payload, dict):
            raise RouterFormatError("统计项必须是 JSON 对象。")
        try:
            stats = cls(
                attempts=int(payload.get("attempts", 0)),
                successes=int(payload.get("successes", 0)),
                total_latency_seconds=float(payload.get("total_latency_seconds", 0.0)),
                ratings_count=int(payload.get("ratings_count", 0)),
                ratings_sum=int(payload.get("ratings_sum", 0)),
            )
        except (TypeError, ValueError) as exc:
            raise RouterFormatError("统计项包含无效数字。") from exc
        if min(stats.attempts, stats.successes, stats.ratings_count, stats.ratings_sum) < 0:
            raise RouterFormatError("统计数字不能小于 0。")
        if stats.successes > stats.attempts:
            raise RouterFormatError("成功次数不能大于尝试次数。")
        if (
            not math.isfinite(stats.total_latency_seconds)
            or stats.total_latency_seconds < 0
        ):
            raise RouterFormatError("累计响应时间必须是大于等于 0 的有限数字。")
        if stats.ratings_sum > stats.ratings_count * 5:
            raise RouterFormatError("评分总和超出范围。")
        return stats


@dataclass
class ProviderStats:
    overall: MetricStats = field(default_factory=MetricStats)
    buckets: dict[str, MetricStats] = field(default_factory=dict)

    def for_bucket(self, bucket: str) -> MetricStats:
        if bucket not in VALID_BUCKETS:
            raise RouterError(f"不支持的任务分类：{bucket}")
        return self.buckets.setdefault(bucket, MetricStats())

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.to_dict(),
            "buckets": {key: value.to_dict() for key, value in sorted(self.buckets.items())},
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ProviderStats":
        if not isinstance(payload, dict):
            raise RouterFormatError("提供方统计必须是对象。")
        buckets_payload = payload.get("buckets", {})
        if not isinstance(buckets_payload, dict):
            raise RouterFormatError("buckets 必须是对象。")
        buckets: dict[str, MetricStats] = {}
        for key, value in buckets_payload.items():
            if key not in VALID_BUCKETS:
                raise RouterFormatError(f"未知任务分类：{key}")
            buckets[key] = MetricStats.from_dict(value)
        return cls(
            overall=MetricStats.from_dict(payload.get("overall", {})),
            buckets=buckets,
        )


@dataclass
class RouterState:
    mode: str = "auto"
    policy: str = "balanced"
    manual_provider: str = ""
    providers: dict[str, ProviderStats] = field(default_factory=dict)
    last_decision: dict[str, Any] | None = None
    pending_rating: dict[str, str] | None = None

    def provider(self, key: str) -> ProviderStats:
        return self.providers.setdefault(key, ProviderStats())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "policy": self.policy,
            "manual_provider": self.manual_provider,
            "providers": {key: value.to_dict() for key, value in sorted(self.providers.items())},
            "last_decision": self.last_decision,
            "pending_rating": self.pending_rating,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "RouterState":
        if not isinstance(payload, dict):
            raise RouterFormatError("路由状态顶层必须是 JSON 对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise RouterFormatError(
                f"不支持的路由状态版本：{payload.get('schema_version')!r}"
            )
        mode = payload.get("mode", "auto")
        policy = payload.get("policy", "balanced")
        manual_provider = payload.get("manual_provider", "")
        if mode not in VALID_MODES:
            raise RouterFormatError("mode 无效。")
        if policy not in VALID_POLICIES:
            raise RouterFormatError("policy 无效。")
        if not isinstance(manual_provider, str):
            raise RouterFormatError("manual_provider 必须是字符串。")
        providers_payload = payload.get("providers", {})
        if not isinstance(providers_payload, dict):
            raise RouterFormatError("providers 必须是对象。")
        providers = {
            str(key): ProviderStats.from_dict(value)
            for key, value in providers_payload.items()
        }
        last_decision = payload.get("last_decision")
        if last_decision is not None and not isinstance(last_decision, dict):
            raise RouterFormatError("last_decision 必须是对象或 null。")
        pending_rating = payload.get("pending_rating")
        if pending_rating is not None:
            if not isinstance(pending_rating, dict):
                raise RouterFormatError("pending_rating 必须是对象或 null。")
            if not isinstance(pending_rating.get("provider"), str):
                raise RouterFormatError("pending_rating.provider 无效。")
            if pending_rating.get("bucket") not in VALID_BUCKETS:
                raise RouterFormatError("pending_rating.bucket 无效。")
        return cls(
            mode=mode,
            policy=policy,
            manual_provider=manual_provider,
            providers=providers,
            last_decision=last_decision,
            pending_rating=pending_rating,
        )


@dataclass(frozen=True)
class ScoreBreakdown:
    quality: float
    reliability: float
    speed: float
    exploration: float
    total: float
    attempts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": round(self.quality, 4),
            "reliability": round(self.reliability, 4),
            "speed": round(self.speed, 4),
            "exploration": round(self.exploration, 4),
            "total": round(self.total, 4),
            "attempts": self.attempts,
        }


@dataclass(frozen=True)
class RouteDecision:
    bucket: str
    signals: tuple[str, ...]
    policy: str
    chosen_provider: str
    scores: dict[str, ScoreBreakdown]
    reason: str

    def sanitized_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "signals": list(self.signals),
            "policy": self.policy,
            "chosen_provider": self.chosen_provider,
            "scores": {key: value.to_dict() for key, value in sorted(self.scores.items())},
            "reason": self.reason,
        }


def classify_prompt(prompt: str) -> TaskFeatures:
    normalized = prompt.strip().lower()
    signals: list[str] = []
    if any(marker in normalized for marker in _CODE_MARKERS):
        signals.append("检测到代码或调试线索")
        return TaskFeatures("code", tuple(signals))
    if any(marker in normalized for marker in _WRITING_MARKERS):
        signals.append("检测到写作或改写线索")
        return TaskFeatures("writing", tuple(signals))
    if any(marker in normalized for marker in _ANALYSIS_MARKERS):
        signals.append("检测到分析或权衡线索")
        return TaskFeatures("analysis", tuple(signals))
    if len(prompt) >= 120:
        signals.append("文本长度超过 120 字")
        return TaskFeatures("analysis", tuple(signals))
    signals.append("没有命中特殊线索")
    return TaskFeatures("general", tuple(signals))


def _effective_stats(provider: ProviderStats, bucket: str) -> tuple[MetricStats, MetricStats]:
    bucket_stats = provider.buckets.get(bucket, MetricStats())
    return provider.overall, bucket_stats


def _score_provider(
    provider: ProviderStats, bucket: str, policy: str
) -> ScoreBreakdown:
    overall, bucket_stats = _effective_stats(provider, bucket)
    weights = _POLICY_WEIGHTS[policy]

    quality_source = bucket_stats if bucket_stats.ratings_count > 0 else overall
    reliability_source = bucket_stats if bucket_stats.attempts > 0 else overall
    speed_source = bucket_stats if bucket_stats.successes > 0 else overall

    quality = quality_source.quality_score()
    reliability = reliability_source.reliability_score()
    speed = speed_source.speed_score()
    attempts = bucket_stats.attempts
    exploration = bucket_stats.exploration_score()
    total = (
        quality * weights["quality"]
        + reliability * weights["reliability"]
        + speed * weights["speed"]
        + exploration * weights["exploration"]
    )
    return ScoreBreakdown(
        quality=quality,
        reliability=reliability,
        speed=speed,
        exploration=exploration,
        total=total,
        attempts=attempts,
    )


def choose_provider(
    prompt: str,
    provider_keys: Iterable[str],
    state: RouterState,
    default_provider: str,
) -> RouteDecision:
    keys = sorted(set(provider_keys))
    if not keys:
        raise RouterError("没有可用模型。")
    if state.policy not in VALID_POLICIES:
        raise RouterError(f"不支持的策略：{state.policy}")

    features = classify_prompt(prompt)
    scores = {
        key: _score_provider(state.provider(key), features.bucket, state.policy)
        for key in keys
    }
    best_total = max(item.total for item in scores.values())
    candidates = [
        key for key, item in scores.items() if abs(item.total - best_total) < 1e-9
    ]
    if default_provider in candidates:
        chosen = default_provider
    else:
        chosen = min(candidates, key=lambda key: (scores[key].attempts, key))

    reason = (
        f"{features.bucket} 类任务；{state.policy} 策略下 "
        f"{chosen} 总分最高（{scores[chosen].total:.3f}）。"
    )
    return RouteDecision(
        bucket=features.bucket,
        signals=features.signals,
        policy=state.policy,
        chosen_provider=chosen,
        scores=scores,
        reason=reason,
    )


def record_result(
    state: RouterState,
    provider_key: str,
    bucket: str,
    success: bool,
    latency_seconds: float,
) -> None:
    provider = state.provider(provider_key)
    provider.overall.record_result(success, latency_seconds)
    provider.for_bucket(bucket).record_result(success, latency_seconds)


def set_pending_rating(state: RouterState, provider_key: str, bucket: str) -> None:
    if bucket not in VALID_BUCKETS:
        raise RouterError("无法为未知任务类型记录评分。")
    state.pending_rating = {"provider": provider_key, "bucket": bucket}


def rate_pending(state: RouterState, rating: int) -> tuple[str, str]:
    pending = state.pending_rating
    if pending is None:
        raise RouterError("目前没有等待评分的回答。")
    provider_key = pending["provider"]
    bucket = pending["bucket"]
    provider = state.provider(provider_key)
    provider.overall.add_rating(rating)
    provider.for_bucket(bucket).add_rating(rating)
    state.pending_rating = None
    return provider_key, bucket


@dataclass
class RouterStore:
    path: Path

    def load(self) -> RouterState:
        if not self.path.exists():
            return RouterState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RouterFormatError(
                f"无法读取路由状态：{self.path}\n"
                "原文件没有被覆盖。可先改名备份，再重新启动。"
            ) from exc
        return RouterState.from_dict(payload)

    def save(self, state: RouterState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
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

    def forget(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True
