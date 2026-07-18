"""Side-effect-free recovery helpers for chapter 07."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from journal import JournalEvent, RecoveryBlocked, RecoveryPlan, TaskJournal
from memory import ConversationStore


@dataclass(frozen=True)
class RecoveryResult:
    task_id: str
    attempt: int
    status: str
    changed_memory: bool
    answer: str | None


def _last_payload(events: list[JournalEvent], kind: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.kind == kind:
            return event.payload
    return None


def _primary_response(events: list[JournalEvent]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.kind == "response_received" and event.payload.get("role") == "primary":
            return event.payload
    return None


def _already_in_memory(messages: list[dict[str, str]], prompt: str, answer: str) -> bool:
    if len(messages) < 2:
        return False
    return (
        messages[-2] == {"role": "user", "content": prompt}
        and messages[-1] == {"role": "assistant", "content": answer}
    )


def recover_local_task(
    journal: TaskJournal, memory: ConversationStore, task_id: str
) -> RecoveryResult:
    plan = journal.plan(task_id)
    attempt = plan.attempt
    events = journal.task_events(task_id, attempt)
    if plan.status == "complete":
        return RecoveryResult(task_id, attempt, "complete", False, None)
    if plan.status == "remote_unknown":
        raise RecoveryBlocked(plan.reason)
    if plan.status == "safe_to_send":
        raise RecoveryBlocked("该任务尚未发送；恢复会产生新的 API 调用，必须由用户主动继续。")
    if plan.status in {"abandoned", "inspect"}:
        raise RecoveryBlocked(plan.reason)

    if plan.status == "finish_only":
        journal.append(task_id, attempt, "task_completed", {"recovered": True})
        return RecoveryResult(task_id, attempt, "completed_locally", False, None)

    prompt = journal.prompt_for(task_id)
    if plan.status == "local_finalize":
        payload = _primary_response(events)
        if payload is None or not isinstance(payload.get("answer"), str):
            raise RecoveryBlocked("流水账中没有完整主回答。")
        answer = payload["answer"]
        provider = str(payload.get("provider", "unknown"))
        journal.append(
            task_id, attempt, "final_answer_ready",
            {"answer": answer, "provider": provider, "recovered_from": "primary_response"},
        )
    else:
        payload = _last_payload(events, "final_answer_ready")
        if payload is None or not isinstance(payload.get("answer"), str):
            raise RecoveryBlocked("流水账中没有完整最终答案。")
        answer = payload["answer"]

    messages = memory.load()
    changed = False
    if not _already_in_memory(messages, prompt, answer):
        memory.save([
            *messages,
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ])
        changed = True
    journal.append(
        task_id, attempt, "memory_committed",
        {"recovered": True, "already_present": not changed},
    )
    journal.append(task_id, attempt, "task_completed", {"recovered": True})
    return RecoveryResult(task_id, attempt, "completed_locally", changed, answer)


def recover_all_local(journal: TaskJournal, memory: ConversationStore) -> list[RecoveryResult]:
    results: list[RecoveryResult] = []
    for plan in list(journal.pending_plans()):
        if plan.can_resume_without_api:
            results.append(recover_local_task(journal, memory, plan.task_id))
    return results
