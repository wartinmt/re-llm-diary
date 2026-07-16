from __future__ import annotations

import unittest

from main import build_api_messages, compare_providers, choose_for_turn, AppSettings
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


if __name__ == "__main__":
    unittest.main()
