from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import print_unsaved_answer


class MainFailurePathTests(unittest.TestCase):
    def test_paid_answer_remains_visible_when_memory_save_fails(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_unsaved_answer("DeepSeek", "已经返回的回答")
        self.assertIn("DeepSeek（未保存）：已经返回的回答", output.getvalue())


if __name__ == "__main__":
    unittest.main()
