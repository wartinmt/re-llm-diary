"""Tool action coordinator with idempotency, reconciliation, and compensation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from journal import ActionJournal
from models import ActionResult, ToolReceipt, new_action_id, validate_idempotency_key, validate_payload
from receipts import ReceiptStore
from tools import EffectUnknownError, SimulatedProcessCrash, ToolError


class ActionCoordinatorError(RuntimeError):
    pass


class UnknownToolError(ActionCoordinatorError):
    pass


class RetryBlockedError(ActionCoordinatorError):
    pass


class ConfirmationRequiredError(ActionCoordinatorError):
    pass


class CompensationNotSupportedError(ActionCoordinatorError):
    pass


@dataclass
class ActionCoordinator:
    journal: ActionJournal
    receipts: ReceiptStore
    tools: Mapping[str, Any]

    def execute(
        self,
        *,
        tool_name: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        simulate: str | None = None,
        parent_action_id: str | None = None,
    ) -> ActionResult:
        key = validate_idempotency_key(idempotency_key)
        clean_payload = validate_payload(payload)
        tool = self._tool(tool_name)
        existing_events = self.journal.find_by_key(key)
        if existing_events:
            self._require_same_request(existing_events, tool_name, clean_payload)

        existing_receipt = self.receipts.get(key)
        if existing_receipt is not None:
            if not existing_events:
                raise RetryBlockedError(
                    "a receipt exists without its original action plan; request binding cannot be proven"
                )
            if (
                existing_receipt.tool_name != tool_name
                or existing_receipt.idempotency_key != key
                or existing_receipt.outcome != "applied"
            ):
                raise RetryBlockedError(
                    "the existing receipt does not match this planned tool action"
                )
            action_id = existing_events[0]["action_id"]
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="receipt_replayed",
                tool_name=tool_name,
                payload={"receipt_id": existing_receipt.receipt_id},
                parent_action_id=parent_action_id,
            )
            return ActionResult(
                action_id=action_id,
                idempotency_key=key,
                status="completed",
                receipt=existing_receipt,
                reused=True,
                message="existing durable receipt reused; tool was not called again",
            )

        if existing_events and existing_events[-1]["event_type"] == "effect_unknown":
            raise RetryBlockedError(
                "the previous effect is unknown; do not retry with the same key or silently create another action"
            )

        action_id = existing_events[0]["action_id"] if existing_events else new_action_id()
        if not existing_events:
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="action_planned",
                tool_name=tool_name,
                payload={"request": clean_payload},
                parent_action_id=parent_action_id,
            )
        self.journal.append(
            action_id=action_id,
            idempotency_key=key,
            event_type="effect_started",
            tool_name=tool_name,
            payload={},
            parent_action_id=parent_action_id,
        )
        try:
            receipt = tool.execute(clean_payload, key, simulate=simulate)
        except SimulatedProcessCrash:
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="runtime_interrupted",
                tool_name=tool_name,
                payload={"reason": "effect may be complete; runtime receipt was not stored"},
                parent_action_id=parent_action_id,
            )
            raise
        except EffectUnknownError as exc:
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="effect_unknown",
                tool_name=tool_name,
                payload={"reason": str(exc)},
                parent_action_id=parent_action_id,
            )
            return ActionResult(
                action_id=action_id,
                idempotency_key=key,
                status="effect_unknown",
                receipt=None,
                message=str(exc),
            )
        except Exception as exc:
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="effect_failed",
                tool_name=tool_name,
                payload={"error": str(exc)},
                parent_action_id=parent_action_id,
            )
            raise

        return self._commit_receipt(
            action_id=action_id,
            tool_name=tool_name,
            key=key,
            receipt=receipt,
            parent_action_id=parent_action_id,
            reconciled=False,
        )

    def recover(self, idempotency_key: str) -> ActionResult:
        key = validate_idempotency_key(idempotency_key)
        events = self.journal.find_by_key(key)
        if not events:
            raise ActionCoordinatorError("no action exists for this idempotency key")
        action_id = events[0]["action_id"]
        tool_name = events[0]["tool_name"]
        tool = self._tool(tool_name)

        receipt = self.receipts.get(key)
        if receipt is not None:
            self._require_receipt_binding(
                receipt, tool_name=tool_name, key=key, outcome="applied"
            )
            if getattr(tool, "queryable", False):
                tool_receipt = tool.lookup(key)
                if tool_receipt != receipt:
                    raise ActionCoordinatorError(
                        "runtime receipt does not match the queryable tool receipt"
                    )
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="receipt_recovered",
                tool_name=tool_name,
                payload={"receipt_id": receipt.receipt_id, "source": "runtime_store"},
                parent_action_id=events[0]["parent_action_id"],
            )
            return ActionResult(
                action_id=action_id,
                idempotency_key=key,
                status="completed",
                receipt=receipt,
                reused=True,
                message="runtime receipt already existed",
            )

        if not getattr(tool, "queryable", False):
            if events[-1]["event_type"] != "effect_unknown":
                self.journal.append(
                    action_id=action_id,
                    idempotency_key=key,
                    event_type="effect_unknown",
                    tool_name=tool_name,
                    payload={"reason": "tool has no lookup interface"},
                    parent_action_id=events[0]["parent_action_id"],
                )
            return ActionResult(
                action_id=action_id,
                idempotency_key=key,
                status="effect_unknown",
                receipt=None,
                message="tool cannot prove whether the side effect happened",
            )

        remote_receipt = tool.lookup(key)
        if remote_receipt is None:
            self.journal.append(
                action_id=action_id,
                idempotency_key=key,
                event_type="effect_not_found",
                tool_name=tool_name,
                payload={"safe_same_key_retry": True},
                parent_action_id=events[0]["parent_action_id"],
            )
            return ActionResult(
                action_id=action_id,
                idempotency_key=key,
                status="safe_to_retry_same_key",
                receipt=None,
                message="queryable tool reports no effect for this key",
            )
        self._require_receipt_binding(
            remote_receipt, tool_name=tool_name, key=key, outcome="applied"
        )
        return self._commit_receipt(
            action_id=action_id,
            tool_name=tool_name,
            key=key,
            receipt=remote_receipt,
            parent_action_id=events[0]["parent_action_id"],
            reconciled=True,
        )

    def retry_unknown(
        self,
        *,
        old_key: str,
        new_key: str,
        confirm: str,
        payload: Mapping[str, Any],
    ) -> ActionResult:
        if confirm != "CONFIRM":
            raise ConfirmationRequiredError("retry requires the exact word CONFIRM")
        old = validate_idempotency_key(old_key)
        new = validate_idempotency_key(new_key)
        if old == new:
            raise RetryBlockedError("a manually authorized retry must use a new idempotency key")
        events = self.journal.find_by_key(old)
        if not events or events[-1]["event_type"] != "effect_unknown":
            raise RetryBlockedError("the original action is not in effect_unknown state")
        return self.execute(
            tool_name=events[0]["tool_name"],
            payload=payload,
            idempotency_key=new,
            parent_action_id=events[0]["action_id"],
        )

    def compensate(
        self,
        *,
        original_key: str,
        compensation_key: str,
        confirm: str,
    ) -> ActionResult:
        if confirm != "CONFIRM":
            raise ConfirmationRequiredError("compensation requires the exact word CONFIRM")
        original = validate_idempotency_key(original_key)
        compensation = validate_idempotency_key(compensation_key)
        if original == compensation:
            raise ActionCoordinatorError("compensation needs its own idempotency key")
        original_receipt = self.receipts.get(original)
        if original_receipt is None:
            raise ActionCoordinatorError("original action has no durable receipt")
        tool = self._tool(original_receipt.tool_name)
        if not getattr(tool, "compensatable", False):
            raise CompensationNotSupportedError("this tool does not support compensation")

        existing = self.receipts.get(compensation)
        original_events = self.journal.find_by_key(original)
        parent_action_id = original_events[0]["action_id"] if original_events else None
        if existing is not None:
            events = self.journal.find_by_key(compensation)
            if (
                existing.tool_name != original_receipt.tool_name
                or existing.outcome != "compensated"
                or existing.metadata.get("compensates_receipt_id")
                != original_receipt.receipt_id
                or not events
                or events[0]["event_type"] != "compensation_planned"
                or events[0]["payload"].get("original_receipt_id")
                != original_receipt.receipt_id
            ):
                raise RetryBlockedError(
                    "the compensation key is already bound to a different effect"
                )
            return ActionResult(
                action_id=events[0]["action_id"],
                idempotency_key=compensation,
                status="compensated",
                receipt=existing,
                reused=True,
                message="existing compensation receipt reused",
            )

        action_id = new_action_id()
        self.journal.append(
            action_id=action_id,
            idempotency_key=compensation,
            event_type="compensation_planned",
            tool_name=original_receipt.tool_name,
            payload={"original_receipt_id": original_receipt.receipt_id},
            parent_action_id=parent_action_id,
        )
        receipt = tool.compensate(original_receipt, compensation)
        self._require_receipt_binding(
            receipt,
            tool_name=original_receipt.tool_name,
            key=compensation,
            outcome="compensated",
        )
        if (
            receipt.metadata.get("compensates_receipt_id")
            != original_receipt.receipt_id
        ):
            raise ActionCoordinatorError(
                "tool returned a compensation receipt for a different original effect"
            )
        self.receipts.put(receipt)
        self.journal.append(
            action_id=action_id,
            idempotency_key=compensation,
            event_type="compensation_completed",
            tool_name=original_receipt.tool_name,
            payload={
                "receipt_id": receipt.receipt_id,
                "original_receipt_id": original_receipt.receipt_id,
            },
            parent_action_id=parent_action_id,
        )
        return ActionResult(
            action_id=action_id,
            idempotency_key=compensation,
            status="compensated",
            receipt=receipt,
            reused=False,
            message="compensation recorded as a new auditable action",
        )

    def replay(self, action_id: str) -> list[dict[str, Any]]:
        events = self.journal.by_action(action_id)
        if not events:
            raise ActionCoordinatorError("action not found")
        return events

    def summaries(self) -> list[dict[str, Any]]:
        return self.journal.action_summaries()

    @staticmethod
    def _require_same_request(
        events: list[dict[str, Any]],
        tool_name: str,
        payload: Mapping[str, Any],
    ) -> None:
        planned = next(
            (event for event in events if event["event_type"] == "action_planned"),
            None,
        )
        if (
            planned is None
            or planned["tool_name"] != tool_name
            or planned["payload"].get("request") != dict(payload)
        ):
            raise RetryBlockedError(
                "the idempotency key is already bound to a different tool or payload"
            )

    @staticmethod
    def _require_receipt_binding(
        receipt: ToolReceipt,
        *,
        tool_name: str,
        key: str,
        outcome: str,
    ) -> None:
        if (
            receipt.tool_name != tool_name
            or receipt.idempotency_key != key
            or receipt.outcome != outcome
        ):
            raise ActionCoordinatorError(
                "tool receipt does not match the planned tool, key, or outcome"
            )

    def _commit_receipt(
        self,
        *,
        action_id: str,
        tool_name: str,
        key: str,
        receipt: ToolReceipt,
        parent_action_id: str | None,
        reconciled: bool,
    ) -> ActionResult:
        self._require_receipt_binding(
            receipt, tool_name=tool_name, key=key, outcome="applied"
        )
        self.receipts.put(receipt)
        self.journal.append(
            action_id=action_id,
            idempotency_key=key,
            event_type="effect_reconciled" if reconciled else "effect_confirmed",
            tool_name=tool_name,
            payload={"receipt_id": receipt.receipt_id, "effect_ref": receipt.effect_ref},
            parent_action_id=parent_action_id,
        )
        self.journal.append(
            action_id=action_id,
            idempotency_key=key,
            event_type="action_completed",
            tool_name=tool_name,
            payload={"outcome": receipt.outcome},
            parent_action_id=parent_action_id,
        )
        return ActionResult(
            action_id=action_id,
            idempotency_key=key,
            status="completed" if receipt.outcome == "applied" else "compensated",
            receipt=receipt,
            reused=reconciled,
            message="receipt reconciled without repeating the effect" if reconciled else "effect confirmed",
        )

    def _tool(self, tool_name: str) -> Any:
        tool = self.tools.get(tool_name)
        if tool is None:
            raise UnknownToolError(f"unknown tool: {tool_name}")
        return tool
