from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class CliTests(unittest.TestCase):
    def capture(self, fn):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            fn()
        return buffer.getvalue()

    def test_01_self_test(self):
        output = self.capture(main.run_self_test)
        self.assertIn("离线自检通过", output)

    def test_02_demo_idempotency(self):
        output = self.capture(main.run_demo_idempotency)
        self.assertIn("实际文件数量：1", output)

    def test_03_demo_receipt_recovery(self):
        output = self.capture(main.run_demo_receipt_recovery)
        self.assertIn("恢复后文件数量仍为：1", output)

    def test_04_demo_unknown(self):
        output = self.capture(main.run_demo_unknown)
        self.assertIn("不会自动重试", output)

    def test_05_demo_compensation(self):
        output = self.capture(main.run_demo_compensation)
        self.assertIn("回执数：2", output)

    def test_06_parse_note_command(self):
        key, title, body = main.parse_note_command(
            "/create abc:key 标题 | 正文", "/create"
        )
        self.assertEqual((key, title, body), ("abc:key", "标题", "正文"))
