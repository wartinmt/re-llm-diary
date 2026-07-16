from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import ConversationStore, MemoryFormatError


class MemoryTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp) / "conversation.json")
            messages = [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好"},
            ]
            store.save(messages)
            self.assertEqual(store.load(), messages)

    def test_invalid_role_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp) / "conversation.json")
            with self.assertRaises(MemoryFormatError):
                store.save([{"role": "system", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
