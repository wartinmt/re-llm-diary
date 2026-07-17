import unittest

from costs import PriceTable
from metrics import RoutingSnapshot
from providers import ProviderConfig
from router import classify_task, plan_verification, route_prompt
from verifier import build_verifier_messages


def configs():
    return {
        'cheap': ProviderConfig('cheap', 'Cheap', 'x', 'https://x', 'a',
            {'quick': .96, 'analysis': .50, 'code': .56, 'creative': .60, 'general': .82},
            .9, PriceTable(.02, 1, 2)),
        'strong': ProviderConfig('strong', 'Strong', 'y', 'https://y', 'b',
            {'quick': .48, 'analysis': .99, 'code': .96, 'creative': .90, 'general': .74},
            .6, PriceTable(2, 8, 28)),
    }


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = RoutingSnapshot({})

    def test_classifies_code(self):
        self.assertEqual(classify_task('这段 Python 代码为什么报错？').task_type, 'code')

    def test_economy_chooses_cheap_for_quick(self):
        prompt = '用一句话解释缓存。'
        decision = route_prompt(prompt, [{'role':'user','content':prompt}], configs(), self.snapshot, 'economy', .05, 512)
        self.assertEqual(decision.selected_provider, 'cheap')

    def test_trust_chooses_strong_for_analysis(self):
        prompt = '请审查这个架构的状态污染风险并给出验证方案。'
        decision = route_prompt(prompt, [{'role':'user','content':prompt}], configs(), self.snapshot, 'trust', .05, 512)
        self.assertEqual(decision.selected_provider, 'strong')

    def test_budget_score_penalizes_expensive(self):
        prompt = '写一个完整故事。'
        decision = route_prompt(prompt, [{'role':'user','content':prompt}], configs(), self.snapshot, 'economy', .0001, 512)
        cheap = next(x for x in decision.rankings if x.provider_key == 'cheap')
        strong = next(x for x in decision.rankings if x.provider_key == 'strong')
        self.assertGreater(cheap.budget, strong.budget)

    def test_verification_on_uses_alternate(self):
        prompt = '请审查架构风险。'
        decision = route_prompt(prompt, [{'role':'user','content':prompt}], configs(), self.snapshot, 'trust', .05, 512)
        plan = plan_verification(decision, 'strong', configs(), self.snapshot, 'on', .05,
                                 build_verifier_messages(prompt, 'answer'), 256)
        self.assertTrue(plan.enabled)
        self.assertEqual(plan.provider_key, 'cheap')

    def test_verification_stops_when_budget_low(self):
        prompt = '请审查架构风险。'
        decision = route_prompt(prompt, [{'role':'user','content':prompt}], configs(), self.snapshot, 'trust', .05, 512)
        plan = plan_verification(decision, 'strong', configs(), self.snapshot, 'on', 0.0,
                                 build_verifier_messages(prompt, 'answer'), 256)
        self.assertFalse(plan.enabled)
        self.assertIn('预算', plan.reason)


if __name__ == '__main__':
    unittest.main()
