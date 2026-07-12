"""《RE:从零开始的大模型研究日记》配套代码 01。

一个最小但完整的 DeepSeek 连续对话客户端。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

BASE_URL: Final = "https://api.deepseek.com"
DEFAULT_MODEL: Final = "deepseek-v4-flash"
SYSTEM_PROMPT: Final = "你是一个简洁、可靠的中文助手。"


def create_client() -> tuple[OpenAI, str]:
    """读取本地配置并创建 DeepSeek 客户端。"""
    load_dotenv(Path(__file__).with_name(".env"))

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请复制 .env.example 为 .env，"
            "然后把你的 DeepSeek API Key 填进去。"
        )

    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=60.0,
        max_retries=2,
    )
    return client, model


def print_help() -> None:
    print(
        "\n可用命令：\n"
        "  /reset  清空本次对话记录\n"
        "  /help   显示命令说明\n"
        "  /exit   退出程序\n"
    )


def request_answer(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """向 DeepSeek 发送当前完整对话并返回最终回答。"""
    response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        stream=False,
        # DeepSeek V4 默认开启思考模式；第一章显式关闭，保持输出简单。
        extra_body={"thinking": {"type": "disabled"}},
    )

    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("模型返回了空内容，请稍后重试。")
    return answer.strip()


def run_chat() -> None:
    client, model = create_client()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    print("DeepSeek 连续对话客户端")
    print(f"当前模型：{model}")
    print("输入 /help 查看命令。建议先告诉它一个临时代号，再在下一轮追问。")

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
        if command == "/reset":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("本次对话记录已清空。")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            answer = request_answer(client, model, messages)
        except OpenAIError as exc:
            # 请求失败时撤回最后一条用户消息，避免错误内容污染后续对话。
            messages.pop()
            print(f"\n请求失败：{exc}", file=sys.stderr)
            print("请检查 API Key、账户余额、网络和模型名称后重试。", file=sys.stderr)
            continue
        except RuntimeError as exc:
            messages.pop()
            print(f"\n运行失败：{exc}", file=sys.stderr)
            continue

        print(f"\nDeepSeek：{answer}")
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    try:
        run_chat()
    except RuntimeError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
