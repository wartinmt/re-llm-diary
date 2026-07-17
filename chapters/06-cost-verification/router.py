"""Transparent task classification, price-aware routing, and verification plans."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Mapping

from costs import TokenUsage, calculate_cost, estimate_usage, format_cny
from metrics import RoutingSnapshot
from providers import ProviderConfig

TASK_LABELS = {
    "quick": "短问题",
    "analysis": "分析判断",
    "code": "代码与排错",
    "creative": "创作表达",
    "general": "一般对话",
}
POLICIES = {"balanced", "economy", "trust"}
VERIFY_MODES = {"auto", "on", "off"}

_CODE_WORDS = {
    "代码", "报错", "函数", "python", "swift", "xcode", "api", "json", "sql",
    "git", "debug", "bug", "traceback", "编译", "正则", "测试",
}
_ANALYSIS_WORDS = {
    "分析", "评估", "权衡", "风险", "根因", "方案", "架构", "设计", "审查",
    "论证", "比较", "为什么", "可行性", "可靠性", "取舍", "验证",
}
_CREATIVE_WORDS = {
    "写一段", "改写", "文案", "故事", "标题", "叙事", "风格", "润色", "起名",
    "小红书", "脚本", "诗", "想象",
}
_QUICK_WORDS = {"一句话", "简短", "只回答", "列出", "翻译", "定义", "是什么"}


@dataclass(frozen=True)
class TaskFeatures:
    task_type: str
    complexity: float
    signals: tuple[str, ...]


@dataclass(frozen=True)
class ScoreBreakdown:
    provider_key: str
    total: float
    profile: float
    quality: float
    reliability: float
    speed: float
    cost: float
    budget: float
    exploration: float
    estimated_cost_cny: float
    estimated_usage: TokenUsage


@dataclass(frozen=True)
class RouteDecision:
    selected_provider: str
    features: TaskFeatures
    policy: str
    budget_cny: float
    rankings: tuple[ScoreBreakdown, ...]

    @property
    def score_margin(self) -> float:
        if len(self.rankings) < 2:
            return 1.0
        return self.rankings[0].total - self.rankings[1].total

    def with_selected(self, provider_key: str) -> "RouteDecision":
        if provider_key not in {item.provider_key for item in self.rankings}:
            raise ValueError(f"{provider_key} 不在候选列表中。")
        return replace(self, selected_provider=provider_key)

    def explanation_lines(self, configs: Mapping[str, ProviderConfig]) -> list[str]:
        label = TASK_LABELS[self.features.task_type]
        signals = "；".join(self.features.signals) or "未发现强信号"
        lines = [
            f"策略：{self.policy}，单轮预算 {format_cny(self.budget_cny)}",
            f"任务形状：{label}，复杂度 {self.features.complexity:.2f}",
            f"识别依据：{signals}",
            "候选得分：",
        ]
        for item in self.rankings:
            name = configs[item.provider_key].display_name
            lines.append(
                f"  {item.provider_key:<8} {name:<10} 总分 {item.total:.3f} "
                f"预计 {format_cny(item.estimated_cost_cny)} "
                f"[适配 {item.profile:.2f} / 质量 {item.quality:.2f} / "
                f"可靠 {item.reliability:.2f} / 速度 {item.speed:.2f} / "
                f"成本 {item.cost:.2f} / 预算 {item.budget:.2f} / 探索 {item.exploration:.2f}]"
            )
        lines.append(f"本轮选择：{self.selected_provider}")
        return lines


@dataclass(frozen=True)
class VerificationPlan:
    enabled: bool
    provider_key: str | None
    estimated_cost_cny: float
    reason: str


def classify_task(prompt: str) -> TaskFeatures:
    text = prompt.strip()
    lowered = text.lower()
    signals: list[str] = []
    code_hits = sorted(word for word in _CODE_WORDS if word in lowered)
    analysis_hits = sorted(word for word in _ANALYSIS_WORDS if word in lowered)
    creative_hits = sorted(word for word in _CREATIVE_WORDS if word in lowered)
    quick_hits = sorted(word for word in _QUICK_WORDS if word in lowered)

    if code_hits or "```" in text or re.search(r"\b(def|class|import|func|let|var)\b", lowered):
        task_type = "code"
        signals.append("出现代码或排错信号：" + "、".join(code_hits[:4] or ["代码块/语法"]))
    elif analysis_hits:
        task_type = "analysis"
        signals.append("出现分析与判断信号：" + "、".join(analysis_hits[:4]))
    elif creative_hits:
        task_type = "creative"
        signals.append("出现创作表达信号：" + "、".join(creative_hits[:4]))
    elif len(text) <= 60 or quick_hits:
        task_type = "quick"
        signals.append(
            "出现简短回答信号：" + "、".join(quick_hits[:4])
            if quick_hits else f"文本较短：{len(text)} 字符"
        )
    else:
        task_type = "general"
        signals.append("没有单一类型占据明显优势")

    length_score = min(1.0, len(text) / 700.0)
    question_score = min(0.25, (text.count("？") + text.count("?")) * 0.08)
    structure_score = 0.18 if any(token in text for token in ("\n", "1.", "一、", "- ")) else 0.0
    keyword_score = min(0.35, (len(code_hits) + len(analysis_hits)) * 0.05)
    complexity = min(1.0, 0.12 + length_score * 0.55 + question_score + structure_score + keyword_score)
    if task_type == "quick":
        complexity = min(complexity, 0.35)
    if task_type in {"analysis", "code"}:
        complexity = max(complexity, 0.48)
    signals.append(f"长度 {len(text)}，问题标记 {text.count('？') + text.count('?')}")
    return TaskFeatures(task_type, round(complexity, 3), tuple(signals))


def _weights(policy: str, task_type: str, complexity: float) -> dict[str, float]:
    if policy not in POLICIES:
        raise ValueError(f"未知策略：{policy}")
    if policy == "economy":
        base = {"profile": .17, "quality": .13, "reliability": .12, "speed": .14,
                "cost": .28, "budget": .11, "exploration": .05}
    elif policy == "trust":
        base = {"profile": .25, "quality": .25, "reliability": .21, "speed": .07,
                "cost": .07, "budget": .05, "exploration": .10}
    else:
        base = {"profile": .22, "quality": .20, "reliability": .17, "speed": .11,
                "cost": .17, "budget": .07, "exploration": .06}

    if task_type in {"analysis", "code"}:
        shift = min(.05, complexity * .05)
        base["quality"] += shift
        base["profile"] += .02
        base["cost"] -= shift
        base["speed"] -= .02
    elif task_type == "quick":
        base["cost"] += .04
        base["speed"] += .03
        base["quality"] -= .04
        base["profile"] -= .03
    total = sum(base.values())
    return {key: value / total for key, value in base.items()}


def route_prompt(
    prompt: str,
    api_messages: list[dict[str, str]],
    configs: Mapping[str, ProviderConfig],
    snapshot: RoutingSnapshot,
    policy: str,
    budget_cny: float,
    max_tokens: int,
) -> RouteDecision:
    if not configs:
        raise RuntimeError("没有可供路由的模型。")
    if budget_cny <= 0:
        raise ValueError("单轮预算必须大于 0。")
    features = classify_task(prompt)
    weights = _weights(policy, features.task_type, features.complexity)

    estimates: dict[str, tuple[TokenUsage, float]] = {}
    for key, config in configs.items():
        observed = snapshot.for_provider(key)
        usage = estimate_usage(
            api_messages,
            features.task_type,
            features.complexity,
            max_tokens,
            observed.cache_hit_ratio,
            observed.average_output_tokens,
        )
        estimates[key] = (usage, calculate_cost(config.price, usage).total)
    min_cost = min(cost for _, cost in estimates.values())

    breakdowns: list[ScoreBreakdown] = []
    for key, config in configs.items():
        observed = snapshot.for_provider(key)
        usage, estimated_cost = estimates[key]
        profile = config.task_bias.get(features.task_type, config.task_bias.get("general", .5))
        quality = observed.normalized_quality(features.task_type)
        reliability = observed.reliability
        speed = observed.latency_score(config.speed_hint)
        cost_score = 1.0 if estimated_cost <= 0 else min(1.0, min_cost / estimated_cost)
        budget_score = 1.0 if estimated_cost <= budget_cny else max(0.0, budget_cny / estimated_cost)
        exploration = observed.exploration_score
        total = (
            weights["profile"] * profile
            + weights["quality"] * quality
            + weights["reliability"] * reliability
            + weights["speed"] * speed
            + weights["cost"] * cost_score
            + weights["budget"] * budget_score
            + weights["exploration"] * exploration
        )
        if not math.isfinite(total):
            raise RuntimeError(f"{key} 的路由得分无效。")
        breakdowns.append(ScoreBreakdown(
            provider_key=key,
            total=total,
            profile=profile,
            quality=quality,
            reliability=reliability,
            speed=speed,
            cost=cost_score,
            budget=budget_score,
            exploration=exploration,
            estimated_cost_cny=estimated_cost,
            estimated_usage=usage,
        ))
    breakdowns.sort(key=lambda item: (-item.total, item.provider_key))
    return RouteDecision(
        selected_provider=breakdowns[0].provider_key,
        features=features,
        policy=policy,
        budget_cny=budget_cny,
        rankings=tuple(breakdowns),
    )


def plan_verification(
    decision: RouteDecision,
    primary_provider: str,
    configs: Mapping[str, ProviderConfig],
    snapshot: RoutingSnapshot,
    verify_mode: str,
    remaining_budget_cny: float,
    verifier_messages: list[dict[str, str]],
    verifier_max_tokens: int,
) -> VerificationPlan:
    if verify_mode not in VERIFY_MODES:
        raise ValueError(f"未知验证模式：{verify_mode}")
    alternatives = [key for key in configs if key != primary_provider]
    if verify_mode == "off":
        return VerificationPlan(False, None, 0.0, "验证已关闭")
    if not alternatives:
        return VerificationPlan(False, None, 0.0, "没有第二个已配置模型")

    candidates: list[tuple[float, float, str]] = []
    for key in alternatives:
        config = configs[key]
        observed = snapshot.for_provider(key)
        usage = estimate_usage(
            verifier_messages,
            "analysis",
            max(.55, decision.features.complexity),
            verifier_max_tokens,
            observed.cache_hit_ratio,
            observed.average_output_tokens,
        )
        estimated = calculate_cost(config.price, usage).total
        trust_score = (
            .45 * observed.normalized_quality(decision.features.task_type)
            + .35 * observed.reliability
            + .20 * (1.0 if estimated <= 0 else 1.0 / (1.0 + estimated * 100))
        )
        candidates.append((trust_score, estimated, key))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    _, estimated, selected = candidates[0]
    if estimated > remaining_budget_cny:
        return VerificationPlan(
            False, None, estimated,
            f"预计验证成本 {format_cny(estimated)} 超过剩余预算 {format_cny(remaining_budget_cny)}",
        )

    reasons: list[str] = []
    if verify_mode == "on":
        reasons.append("验证模式为 on")
    else:
        if decision.policy == "trust" and decision.features.complexity >= .45:
            reasons.append("trust 策略处理复杂任务")
        if decision.features.complexity >= .78:
            reasons.append("任务复杂度较高")
        if decision.score_margin < .045:
            reasons.append("首选与次选得分接近")
        if not reasons:
            return VerificationPlan(False, None, estimated, "当前风险信号不足")
    return VerificationPlan(True, selected, estimated, "；".join(reasons))
