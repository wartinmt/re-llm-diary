import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers import ProviderConfig, choose_default_provider, load_provider_configs


class ProviderConfigTests(unittest.TestCase):
    def test_placeholder_keys_are_not_configured(self):
        configs = load_provider_configs(
            {
                "DEEPSEEK_API_KEY": "把你的_DeepSeek_API_Key_填在这里",
                "ZAI_API_KEY": "把你的_ZAI_API_Key_填在这里",
            },
            require_any=False,
        )
        self.assertEqual(configs, {})

    def test_loads_both_official_defaults(self):
        configs = load_provider_configs(
            {"DEEPSEEK_API_KEY": "a", "ZAI_API_KEY": "b"}
        )
        self.assertEqual(configs["deepseek"].model, "deepseek-v4-flash")
        self.assertEqual(configs["glm"].model, "glm-5.2")
        self.assertEqual(
            configs["glm"].base_url, "https://open.bigmodel.cn/api/paas/v4/"
        )

    def test_repr_hides_api_key(self):
        config = ProviderConfig("x", "X", "top-secret", "https://x", "m")
        self.assertNotIn("top-secret", repr(config))

    def test_default_falls_back_to_deepseek(self):
        configs = load_provider_configs(
            {"DEEPSEEK_API_KEY": "a", "ZAI_API_KEY": "b"}
        )
        self.assertEqual(choose_default_provider(configs, "missing"), "deepseek")


if __name__ == "__main__":
    unittest.main()
