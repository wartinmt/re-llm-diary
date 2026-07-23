from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import normalize_usage, read_decimal_env


class ConfigurationTests(unittest.TestCase):
    def test_nonfinite_prices_are_rejected(self):
        for raw in ("nan", "inf", "-inf", "Infinity"):
            with self.subTest(raw=raw), patch.dict(
                os.environ, {"AUDIT_PRICE": raw}
            ):
                with self.assertRaises(RuntimeError):
                    read_decimal_env("AUDIT_PRICE", "1")

    def test_negative_price_is_rejected(self):
        with patch.dict(os.environ, {"AUDIT_PRICE": "-0.1"}):
            with self.assertRaises(RuntimeError):
                read_decimal_env("AUDIT_PRICE", "1")


class UsageTests(unittest.TestCase):
    def test_negative_usage_is_rejected(self):
        with self.assertRaises(RuntimeError):
            normalize_usage(SimpleNamespace(prompt_tokens=-1))

    def test_invalid_usage_is_rejected(self):
        with self.assertRaises(RuntimeError):
            normalize_usage(SimpleNamespace(completion_tokens="many"))

    def test_missing_cache_split_is_counted_as_miss(self):
        usage = normalize_usage(
            SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12)
        )
        self.assertEqual(usage.cache_hit_tokens, 0)
        self.assertEqual(usage.cache_miss_tokens, 10)

    def test_total_cannot_be_less_than_prompt_plus_completion(self):
        usage = normalize_usage(
            SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=1)
        )
        self.assertEqual(usage.total_tokens, 12)


if __name__ == "__main__":
    unittest.main()
