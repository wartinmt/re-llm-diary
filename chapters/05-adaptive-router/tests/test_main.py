from __future__ import annotations

import unittest
import io
from contextlib import redirect_stdout

from main import (
    AppSettings,
    build_api_messages,
    choose_for_turn,
    compare_providers,
    print_unsaved_answer,
)
from providers import ProviderConfig
from router import RouterState
from pathlib import Path


class MainTests(unittest.TestCase):
    def configs(self):
        return {
            "deepseek": ProviderConfig("deepseek", "DeepSeek", "a", "https://a.invalid", "a"),
            "glm": ProviderConfig("glm", "GLM", "b", "https://b.invalid", "b"),
        }

    def test_build_api_messages(self):
        history = [{"role": "user", "content": "old"}]
        result = build_api_messages(history, "new")
        self.assertEqual(result[-1], {"role": "user", "content": "new"})
        self.assertEqual(history, [{"role": "user", "content": "old"}])

    def test_compare_does_not_mutate_history(self):
        history = [{"role": "user", "content": "old"}]
        original = [dict(item) for item in history]
        configs = self.configs()
        clients = {"deepseek": object(), "glm": object()}

        def fake_request(client, config, messages, max_tokens):
            del client, max_tokens
            return config.display_name + messages[-1]["content"]

        results = compare_providers(
            ["deepseek", "glm"], configs, clients, history, "new", 10,
            request_fn=fake_request,
        )
        self.assertEqual(history, original)
        self.assertEqual(len(results), 2)

    def test_manual_mode_respects_provider(self):
        settings = AppSettings(
            providers=self.configs(), default_provider="deepseek",
            memory_path=Path("m"), router_path=Path("r"), max_tokens=10,
            default_policy="balanced",
        )
        state = RouterState(mode="manual", manual_provider="glm")
        provider, decision, bucket = choose_for_turn("你好", settings, state)
        self.assertEqual(provider, "glm")
        self.assertIsNone(decision)
        self.assertEqual(bucket, "general")

    def test_paid_answer_remains_visible_when_memory_save_fails(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_unsaved_answer("DeepSeek", "已经返回的回答")
        self.assertIn("DeepSeek（未保存）：已经返回的回答", output.getvalue())


if __name__ == "__main__":
    unittest.main()
