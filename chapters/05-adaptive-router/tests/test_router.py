from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from router import (
    RouterFormatError,
    RouterState,
    RouterStore,
    choose_provider,
    classify_prompt,
    rate_pending,
    record_result,
    set_pending_rating,
)


class RouterTests(unittest.TestCase):
    def test_classify_prompt(self):
        self.assertEqual(classify_prompt("修复这段 Python 报错").bucket, "code")
        self.assertEqual(classify_prompt("请润色这段文案").bucket, "writing")
        self.assertEqual(classify_prompt("分析这个方案的风险").bucket, "analysis")
        self.assertEqual(classify_prompt("你好").bucket, "general")

    def test_no_data_uses_default_provider(self):
        state = RouterState()
        decision = choose_provider("你好", ["deepseek", "glm"], state, "deepseek")
        self.assertEqual(decision.chosen_provider, "deepseek")

    def test_quality_policy_uses_ratings(self):
        state = RouterState(policy="quality")
        for key, rating in [("deepseek", 1), ("glm", 5)]:
            record_result(state, key, "analysis", True, 2.0)
            set_pending_rating(state, key, "analysis")
            rate_pending(state, rating)
        decision = choose_provider(
            "分析这个方案的风险", ["deepseek", "glm"], state, "deepseek"
        )
        self.assertEqual(decision.chosen_provider, "glm")

    def test_fast_policy_uses_latency(self):
        state = RouterState(policy="fast")
        for _ in range(3):
            record_result(state, "deepseek", "general", True, 8.0)
            record_result(state, "glm", "general", True, 1.0)
        decision = choose_provider("你好", ["deepseek", "glm"], state, "deepseek")
        self.assertEqual(decision.chosen_provider, "glm")

    def test_failures_lower_reliability(self):
        state = RouterState(policy="balanced")
        for _ in range(4):
            record_result(state, "deepseek", "general", False, 0.2)
            record_result(state, "glm", "general", True, 2.0)
        decision = choose_provider("你好", ["deepseek", "glm"], state, "deepseek")
        self.assertEqual(decision.chosen_provider, "glm")

    def test_store_roundtrip_and_no_prompt_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "router.json"
            store = RouterStore(path)
            state = RouterState()
            decision = choose_provider(
                "这是一条不应写进状态文件的秘密问题",
                ["deepseek", "glm"],
                state,
                "deepseek",
            )
            state.last_decision = decision.sanitized_dict()
            store.save(state)
            restored = store.load()
            self.assertEqual(restored.last_decision, state.last_decision)
            self.assertNotIn("秘密问题", path.read_text(encoding="utf-8"))

    def test_corrupt_store_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "router.json"
            path.write_text('{"schema_version": 999}', encoding="utf-8")
            with self.assertRaises(RouterFormatError):
                RouterStore(path).load()

    def test_rating_requires_pending_answer(self):
        with self.assertRaises(Exception):
            rate_pending(RouterState(), 5)

    def test_nonfinite_runtime_latency_is_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(Exception):
                record_result(RouterState(), "deepseek", "general", True, value)

    def test_nonfinite_saved_latency_is_rejected(self):
        payload = {
            "schema_version": 1,
            "mode": "auto",
            "policy": "balanced",
            "manual_provider": "",
            "providers": {
                "deepseek": {
                    "overall": {
                        "attempts": 1,
                        "successes": 1,
                        "total_latency_seconds": float("nan"),
                        "ratings_count": 0,
                        "ratings_sum": 0,
                    },
                    "buckets": {},
                }
            },
            "last_decision": None,
            "pending_rating": None,
        }
        with self.assertRaises(RouterFormatError):
            RouterState.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
