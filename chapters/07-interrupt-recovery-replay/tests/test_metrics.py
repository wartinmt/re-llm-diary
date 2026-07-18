import json
import tempfile
import unittest
from pathlib import Path

from costs import TokenUsage
from metrics import MetricsFormatError, RoutingMetricsStore


class MetricsTests(unittest.TestCase):
    def test_persist_usage_cost_and_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            store = RoutingMetricsStore(path)
            store.load()
            store.record_attempt('a', 'quick', 'primary', True, .5, TokenUsage(10, 4, 2, 8), .001)
            item = RoutingMetricsStore(path).load().for_provider('a')
            self.assertEqual(item.primary_calls, 1)
            self.assertEqual(item.prompt_tokens, 10)
            self.assertAlmostEqual(item.total_cost_cny, .001)

    def test_roles_sum_must_match_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text(json.dumps({
                'schema_version': 2,
                'providers': {'a': {'attempts': 1, 'successes': 1, 'failures': 0}}
            }), encoding='utf-8')
            with self.assertRaises(MetricsFormatError):
                RoutingMetricsStore(path).load()

    def test_old_schema_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text('{"schema_version":1,"providers":{}}', encoding='utf-8')
            with self.assertRaises(MetricsFormatError):
                RoutingMetricsStore(path).load()

    def test_rating_changes_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RoutingMetricsStore(Path(tmp) / 'state.json')
            store.load()
            store.record_rating('a', 'analysis', 5)
            self.assertEqual(store.snapshot().for_provider('a').normalized_quality('analysis'), 1.0)


if __name__ == '__main__':
    unittest.main()
