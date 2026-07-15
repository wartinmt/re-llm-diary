"""模型提供方配置与 OpenAI 兼容调用。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from openai import OpenAI


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    display_name: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    extra_body: dict[str, Any] | None = None


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
        "extra_body": None,
    },
)


def _is_real_key(raw: str, placeholders: set[str]) -> bool:
    value = raw.strip()
    return bool(value) and value not in placeholders


def load_provider_configs(
    env: Mapping[str, str], require_any: bool = True
) -> dict[str, ProviderConfig]:
    configs: dict[str, ProviderConfig] = {}
    for template in _PROVIDER_TEMPLATES:
        raw_key = env.get(template["api_key_env"], "")
        if not _is_real_key(raw_key, template["placeholders"]):
            continue
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


def create_clients(configs: Mapping[str, ProviderConfig]) -> dict[str, OpenAI]:
    return {
        key: OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=60.0,
            max_retries=2,
        )
        for key, config in configs.items()
    }


def request_answer(
    client: OpenAI,
    config: ProviderConfig,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if config.extra_body is not None:
        kwargs["extra_body"] = config.extra_body
    response = client.chat.completions.create(**kwargs)
    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError(f"{config.display_name} 返回了空内容。")
    return answer.strip()
