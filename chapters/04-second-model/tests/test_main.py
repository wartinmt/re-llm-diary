import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import build_api_messages, compare_providers
from providers import ProviderConfig


class MainLogicTests(unittest.TestCase):
    def setUp(self):
        self.configs = {
            "deepseek": ProviderConfig(
                "deepseek", "DeepSeek", "a", "https://a", "model-a"
            ),
            "glm": ProviderConfig("glm", "GLM", "b", "https://b", "model-b"),
        }
        self.clients = {"deepseek": object(), "glm": object()}

    def test_build_messages_does_not_mutate_history(self):
        history = [{"role": "user", "content": "旧问题"}]
        original = [dict(item) for item in history]
        result = build_api_messages(history, "新问题")
        self.assertEqual(history, original)
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[-1]["content"], "新问题")

    def test_compare_does_not_mutate_memory(self):
        history = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
        ]
        original = [dict(item) for item in history]

        def fake_request(client, config, messages, max_tokens):
            del client, messages, max_tokens
            return config.display_name

        results = compare_providers(
            ["deepseek", "glm"],
            self.configs,
            self.clients,
            history,
            "比较问题",
            128,
            request_fn=fake_request,
        )
        self.assertEqual(history, original)
        self.assertEqual([r.answer for r in results], ["DeepSeek", "GLM"])

    def test_one_provider_failure_does_not_hide_other_result(self):
        def fake_request(client, config, messages, max_tokens):
            del client, messages, max_tokens
            if config.key == "deepseek":
                raise RuntimeError("temporary failure")
            return "ok"

        results = compare_providers(
            ["deepseek", "glm"],
            self.configs,
            self.clients,
            [],
            "比较问题",
            128,
            request_fn=fake_request,
        )
        self.assertIsNotNone(results[0].error)
        self.assertEqual(results[1].answer, "ok")


if __name__ == "__main__":
    unittest.main()
