import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from costs import PriceTable, TokenUsage
from main import (
    _answer_provider_after_verification,
    _call_and_record,
    _read_positive_float,
)
from metrics import MetricsFormatError, RoutingMetricsStore, RoutingSnapshot
from providers import ModelResult, ProviderConfig, load_provider_configs
from router import plan_verification, route_prompt
from verifier import VerificationOutcome, build_verifier_messages, parse_verification


def _configs():
    return {
        "cheap": ProviderConfig(
            "cheap", "Cheap", "x", "https://x", "a",
            {"quick": .96, "analysis": .50, "code": .56, "creative": .60, "general": .82},
            .9, PriceTable(.02, 1, 2),
        ),
        "strong": ProviderConfig(
            "strong", "Strong", "y", "https://y", "b",
            {"quick": .48, "analysis": .99, "code": .96, "creative": .90, "general": .74},
            .6, PriceTable(2, 8, 28),
        ),
    }


class _FailingMetrics:
    def record_attempt(self, *args, **kwargs):
        raise OSError("disk full")


class SafetyTests(unittest.TestCase):
    def test_corrupt_counter_is_cleanly_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({
                "schema_version": 2,
                "providers": {"a": {"attempts": "oops"}},
            }), encoding="utf-8")
            with self.assertRaises(MetricsFormatError):
                RoutingMetricsStore(path).load()

    def test_nonfinite_budget_is_rejected(self):
        with patch.dict("os.environ", {"TURN_BUDGET_CNY": "nan"}):
            with self.assertRaises(RuntimeError):
                _read_positive_float("TURN_BUDGET_CNY", .05)

    def test_nonfinite_provider_price_is_rejected(self):
        env = {
            "DEEPSEEK_API_KEY": "real",
            "DEEPSEEK_PRICE_OUTPUT_CNY": "inf",
        }
        with self.assertRaises(RuntimeError):
            load_provider_configs(env)

    def test_truncated_revise_cannot_replace_answer(self):
        outcome = parse_verification(
            "REVISE\n有问题\n---REVISED---\n半段答案", finish_reason="length"
        )
        self.assertEqual(outcome.status, "uncertain")
        self.assertIsNone(outcome.revised_answer)

    def test_rating_follows_reviser_only_when_revised(self):
        revise = VerificationOutcome("revise", "修订", "完整答案")
        passed = VerificationOutcome("pass", "通过")
        self.assertEqual(
            _answer_provider_after_verification("primary", "verifier", revise),
            "verifier",
        )
        self.assertEqual(
            _answer_provider_after_verification("primary", "verifier", passed),
            "primary",
        )

    def test_accounting_failure_does_not_turn_success_into_retry(self):
        configs = {"cheap": _configs()["cheap"]}
        calls = []

        def fake_request(client, config, messages, max_tokens):
            calls.append(config.key)
            return ModelResult("ok", TokenUsage(10, 2, 0, 10), config.model, "stop")

        result = _call_and_record(
            "cheap", "primary", "quick", [{"role": "user", "content": "hi"}],
            32, configs, {"cheap": object()}, _FailingMetrics(), fake_request,
        )
        self.assertEqual(calls, ["cheap"])
        self.assertEqual(result.result.answer, "ok")
        self.assertIn("不会因此重试", result.accounting_warning or "")

    def test_failed_provider_is_not_immediately_reused_for_verification(self):
        configs = _configs()
        prompt = "请审查架构风险。"
        decision = route_prompt(
            prompt, [{"role": "user", "content": prompt}], configs,
            RoutingSnapshot({}), "trust", .05, 512,
        )
        plan = plan_verification(
            decision, "strong", configs, RoutingSnapshot({}), "on", .05,
            build_verifier_messages(prompt, "answer"), 256,
            excluded_providers={"cheap"},
        )
        self.assertFalse(plan.enabled)
        self.assertIn("没有可用", plan.reason)

    def test_primary_estimates_ignore_comparison_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RoutingMetricsStore(Path(tmp) / "state.json")
            store.load()
            store.record_attempt(
                "cheap", "quick", "primary", True, .1,
                TokenUsage(10, 20, 0, 10), .001,
            )
            store.record_attempt(
                "cheap", "quick", "comparison", True, .1,
                TokenUsage(10, 1000, 0, 10), .001,
            )
            item = store.snapshot().for_provider("cheap")
            self.assertEqual(item.average_output_tokens_for_role("primary"), 20)
            self.assertEqual(item.average_output_tokens, 510)


if __name__ == "__main__":
    unittest.main()
