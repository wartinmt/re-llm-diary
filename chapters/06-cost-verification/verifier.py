"""Build and parse a deliberately small second-model verification protocol."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationOutcome:
    status: str
    note: str
    revised_answer: str | None = None


_SYSTEM = """你是一个克制的答案验证器。只检查候选答案是否直接回应问题、是否存在明显事实/逻辑冲突、是否遗漏关键约束。不要因为风格偏好要求重写。
第一行必须且只能以 PASS、REVISE 或 UNCERTAIN 开头。
PASS：第二行给一句简短理由。
UNCERTAIN：第二行说明无法确认之处。
REVISE：第二行说明问题，然后另起一行写 ---REVISED---，其后给出完整可替换答案。"""


def build_verifier_messages(prompt: str, candidate_answer: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                "原始问题：\n" + prompt.strip()
                + "\n\n候选答案：\n" + candidate_answer.strip()
            ),
        },
    ]


def parse_verification(text: str) -> VerificationOutcome:
    clean = text.strip()
    if not clean:
        return VerificationOutcome("uncertain", "验证模型返回空内容。")
    lines = clean.splitlines()
    first = lines[0].strip().upper()
    if first.startswith("PASS"):
        note = "\n".join(lines[1:]).strip() or "未发现需要修改的明显问题。"
        return VerificationOutcome("pass", note)
    if first.startswith("REVISE"):
        body = "\n".join(lines[1:]).strip()
        marker = "---REVISED---"
        if marker in body:
            note, revised = body.split(marker, 1)
            revised = revised.strip()
            if revised:
                return VerificationOutcome("revise", note.strip() or "候选答案需要修订。", revised)
        return VerificationOutcome("uncertain", "验证器要求修订，但没有给出完整替换答案。")
    if first.startswith("UNCERTAIN"):
        note = "\n".join(lines[1:]).strip() or "验证器无法确认答案。"
        return VerificationOutcome("uncertain", note)
    return VerificationOutcome("uncertain", "无法识别验证器的第一行状态。")


def apply_verification(candidate_answer: str, outcome: VerificationOutcome) -> str:
    if outcome.status == "revise" and outcome.revised_answer:
        return outcome.revised_answer
    if outcome.status == "uncertain":
        return candidate_answer.rstrip() + f"\n\n[验证提示：{outcome.note}]"
    return candidate_answer
