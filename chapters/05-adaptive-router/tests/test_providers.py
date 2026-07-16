from __future__ import annotations

import unittest

from providers import choose_default_provider, load_provider_configs


class ProviderTests(unittest.TestCase):
    def test_placeholders_are_not_keys(self):
        configs = load_provider_configs(
            {
                "DEEPSEEK_API_KEY": "把你的_DeepSeek_API_Key_填在这里",
                "ZAI_API_KEY": "把你的_ZAI_API_Key_填在这里",
            },
            require_any=False,
        )
        self.assertEqual(configs, {})

    def test_two_real_keys_load(self):
        configs = load_provider_configs(
            {"DEEPSEEK_API_KEY": "real-a", "ZAI_API_KEY": "real-b"}
        )
        self.assertEqual(set(configs), {"deepseek", "glm"})
        self.assertNotIn("real-a", repr(configs["deepseek"]))

    def test_default_falls_back_to_deepseek(self):
        configs = load_provider_configs(
            {"DEEPSEEK_API_KEY": "real-a", "ZAI_API_KEY": "real-b"}
        )
        self.assertEqual(choose_default_provider(configs, "missing"), "deepseek")


if __name__ == "__main__":
    unittest.main()
