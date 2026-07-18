import unittest

from verifier import apply_verification, parse_verification


class VerifierTests(unittest.TestCase):
    def test_pass(self):
        result = parse_verification('PASS\n没有明显问题。')
        self.assertEqual(result.status, 'pass')

    def test_revise_with_full_answer(self):
        result = parse_verification('REVISE\n遗漏约束。\n---REVISED---\n完整新答案')
        self.assertEqual(result.status, 'revise')
        self.assertEqual(apply_verification('old', result), '完整新答案')

    def test_incomplete_revise_is_uncertain(self):
        result = parse_verification('REVISE\n只有评论')
        self.assertEqual(result.status, 'uncertain')

    def test_unknown_status_is_uncertain(self):
        result = parse_verification('MAYBE\n不知道')
        self.assertEqual(result.status, 'uncertain')

    def test_uncertain_appends_visible_note(self):
        result = parse_verification('UNCERTAIN\n缺少来源。')
        self.assertIn('验证提示', apply_verification('原答案', result))


if __name__ == '__main__':
    unittest.main()
