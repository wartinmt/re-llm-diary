import unittest

from costs import PriceTable, TokenUsage, calculate_cost, estimate_message_tokens, estimate_usage


class CostTests(unittest.TestCase):
    def test_exact_cost(self):
        price = PriceTable(.02, 1, 2)
        usage = TokenUsage(1000, 200, 250, 750)
        cost = calculate_cost(price, usage)
        self.assertAlmostEqual(cost.total, 250*.02/1_000_000 + 750/1_000_000 + 400/1_000_000)

    def test_uncategorized_prompt_is_miss(self):
        cost = calculate_cost(PriceTable(0, 10, 0), TokenUsage(100, 0, 20, 30))
        self.assertAlmostEqual(cost.total, 800/1_000_000)

    def test_invalid_usage_rejected(self):
        with self.assertRaises(ValueError):
            TokenUsage(10, 0, 8, 8)

    def test_message_estimate_is_nonzero(self):
        self.assertGreater(estimate_message_tokens([{"role": "user", "content": "你好"}]), 0)

    def test_estimate_respects_max_tokens(self):
        usage = estimate_usage([{"role": "user", "content": "分析风险"}], "analysis", .9, 64)
        self.assertEqual(usage.completion_tokens, 64)


if __name__ == '__main__':
    unittest.main()
