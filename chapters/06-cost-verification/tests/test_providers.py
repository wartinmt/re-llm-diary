import unittest
from types import SimpleNamespace

from providers import extract_usage, load_provider_configs


class ProviderTests(unittest.TestCase):
    def test_load_prices(self):
        env = {
            "DEEPSEEK_API_KEY": "real",
            "DEEPSEEK_PRICE_CACHE_HIT_CNY": "0.1",
            "DEEPSEEK_PRICE_CACHE_MISS_CNY": "1.2",
            "DEEPSEEK_PRICE_OUTPUT_CNY": "2.3",
        }
        config = load_provider_configs(env)["deepseek"]
        self.assertEqual(config.price.output_per_million, 2.3)

    def test_placeholders_are_ignored(self):
        with self.assertRaises(RuntimeError):
            load_provider_configs({"DEEPSEEK_API_KEY": "YOUR_API_KEY"})

    def test_extract_direct_cache_fields(self):
        raw = SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                              prompt_cache_hit_tokens=40, prompt_cache_miss_tokens=60)
        usage = extract_usage(raw)
        self.assertEqual((usage.cache_hit_tokens, usage.cache_miss_tokens), (40, 60))

    def test_extract_openai_cached_tokens(self):
        raw = SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=25))
        usage = extract_usage(raw)
        self.assertEqual((usage.cache_hit_tokens, usage.cache_miss_tokens), (25, 75))

    def test_missing_details_count_as_miss(self):
        raw = SimpleNamespace(prompt_tokens=50, completion_tokens=5)
        usage = extract_usage(raw)
        self.assertEqual(usage.cache_miss_tokens, 50)


if __name__ == '__main__':
    unittest.main()
