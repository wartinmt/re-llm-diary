import json
import tempfile
import unittest
from pathlib import Path

from memory import ConversationStore, MemoryFormatError


class ConversationStoreTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ConversationStore(Path(tmp) / "x.json").load(), [])

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp) / "x.json")
            messages = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]
            store.save(messages)
            self.assertEqual(store.load(), messages)

    def test_invalid_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(MemoryFormatError):
                ConversationStore(path).load()

    def test_api_key_is_not_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            ConversationStore(path).save([{"role": "user", "content": "hello"}])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("api_key", payload)
