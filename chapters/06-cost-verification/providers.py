"""Provider configuration and OpenAI-compatible requests with usage capture."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from costs import PriceTable, TokenUsage


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    display_name: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    task_bias: dict[str, float]
    speed_hint: float
    price: PriceTable
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelResult:
    answer: str
    usage: TokenUsage
    model: str
    finish_reason: str | None = None


_PROVIDER_TEMPLATES = (
    {
        "key": "deepseek",
        "display_name": "DeepSeek",
        "api_key_env": "DEEPSEEK_API_KEY",
        "placeholders": {
            "把你的_DeepSeek_API_Key_填在这里",
            "YOUR_DEEPSEEK_API_KEY",
            "YOUR_API_KEY",
        },
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-v4-flash",
        "speed_env": "DEEPSEEK_SPEED_HINT",
        "default_speed": 0.85,
        "price_hit_env": "DEEPSEEK_PRICE_CACHE_HIT_CNY",
        "price_miss_env": "DEEPSEEK_PRICE_CACHE_MISS_CNY",
        "price_output_env": "DEEPSEEK_PRICE_OUTPUT_CNY",
        "default_prices": (0.02, 1.0, 2.0),
        "task_bias": {
            "quick": 0.92,
            "analysis": 0.68,
            "code": 0.76,
            "creative": 0.66,
            "general": 0.82,
        },
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    {
        "key": "glm",
        "display_name": "GLM",
        "api_key_env": "ZAI_API_KEY",
        "placeholders": {
            "把你的_ZAI_API_Key_填在这里",
            "YOUR_ZAI_API_KEY",
            "YOUR_API_KEY",
        },
        "base_url_env": "ZAI_BASE_URL",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model_env": "ZAI_MODEL",
        "default_model": "glm-5.2",
        "speed_env": "ZAI_SPEED_HINT",
        "default_speed": 0.72,
        "price_hit_env": "ZAI_PRICE_CACHE_HIT_CNY",
        "price_miss_env": "ZAI_PRICE_CACHE_MISS_CNY",
        "price_output_env": "ZAI_PRICE_OUTPUT_CNY",
        "default_prices": (2.0, 8.0, 28.0),
        "task_bias": {
            "quick": 0.67,
            "analysis": 0.92,
            "code": 0.80,
            "creative": 0.88,
            "general": 0.78,
        },
        "extra_body": None,
    },
)


def _is_real_key(raw: str, placeholders: set[str]) -> bool:
    value = raw.strip()
    return bool(value) and value not in placeholders


def _read_unit_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效数字：{raw}") from exc
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise RuntimeError(f"{name} 必须位于 0 到 1 之间。")
    return value


def _read_nonnegative_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 不是有效数字：{raw}") from exc
    if not math.isfinite(value) or value < 0:
        raise RuntimeError(f"{name} 不能小于 0。")
    return value


def load_provider_configs(
    env: Mapping[str, str], require_any: bool = True
) -> dict[str, ProviderConfig]:
    configs: dict[str, ProviderConfig] = {}
    for template in _PROVIDER_TEMPLATES:
        raw_key = env.get(template["api_key_env"], "")
        if not _is_real_key(raw_key, template["placeholders"]):
            continue
        hit, miss, output = template["default_prices"]
        key = template["key"]
        configs[key] = ProviderConfig(
            key=key,
            display_name=template["display_name"],
            api_key=raw_key.strip(),
            base_url=(
                env.get(template["base_url_env"], template["default_base_url"]).strip()
                or template["default_base_url"]
            ),
            model=(
                env.get(template["model_env"], template["default_model"]).strip()
                or template["default_model"]
            ),
            task_bias=dict(template["task_bias"]),
            speed_hint=_read_unit_float(
                env, template["speed_env"], template["default_speed"]
            ),
            price=PriceTable(
                cache_hit_input_per_million=_read_nonnegative_float(
                    env, template["price_hit_env"], hit
                ),
                cache_miss_input_per_million=_read_nonnegative_float(
                    env, template["price_miss_env"], miss
                ),
                output_per_million=_read_nonnegative_float(
                    env, template["price_output_env"], output
                ),
            ),
            extra_body=template["extra_body"],
        )
    if require_any and not configs:
        raise RuntimeError(
            "没有找到可用的模型配置。请在 .env 中至少填写一个真实 API Key。"
        )
    return configs


def choose_default_provider(
    configs: Mapping[str, ProviderConfig], requested: str
) -> str:
    if not configs:
        raise RuntimeError("没有可用模型。")
    normalized = requested.strip().lower()
    if normalized in configs:
        return normalized
    if "deepseek" in configs:
        return "deepseek"
    return next(iter(configs))


def create_clients(configs: Mapping[str, ProviderConfig]) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "缺少新版 openai 包。请激活 .venv 后重新安装 requirements.txt。"
        ) from exc
    return {
        key: OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=60.0,
            # A transport error does not prove that the paid request was not
            # accepted remotely.  Let the chapter-level state machine decide
            # whether a new attempt is authorized.
            max_retries=0,
        )
        for key, config in configs.items()
    }


def _int_attr(value: Any, name: str, default: int = 0) -> int:
    raw = getattr(value, name, default) if value is not None else default
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return default


def extract_usage(raw_usage: Any) -> TokenUsage:
    prompt = _int_attr(raw_usage, "prompt_tokens")
    completion = _int_attr(raw_usage, "completion_tokens")

    hit = _int_attr(raw_usage, "prompt_cache_hit_tokens")
    miss = _int_attr(raw_usage, "prompt_cache_miss_tokens")
    details = getattr(raw_usage, "prompt_tokens_details", None)
    if hit == 0 and details is not None:
        hit = _int_attr(details, "cached_tokens")

    hit = min(hit, prompt)
    miss = min(miss, prompt - hit)
    if hit == 0 and miss == 0:
        miss = prompt
    elif hit + miss < prompt:
        miss += prompt - hit - miss

    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
    )


def request_answer(
    client: Any,
    config: ProviderConfig,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> ModelResult:
    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if config.extra_body is not None:
        kwargs["extra_body"] = config.extra_body
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    answer = choice.message.content
    if not answer:
        raise RuntimeError(f"{config.display_name} 返回了空内容。")
    return ModelResult(
        answer=answer.strip(),
        usage=extract_usage(getattr(response, "usage", None)),
        model=str(getattr(response, "model", config.model) or config.model),
        finish_reason=(
            str(getattr(choice, "finish_reason", "") or "").strip().lower() or None
        ),
    )
