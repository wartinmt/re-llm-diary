import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory import ConversationStore, MemoryFormatError


class ConversationStoreTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ConversationStore(Path(tmp)/"m.json").load(), [])

    def test_roundtrip_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"m.json"; store=ConversationStore(path)
            messages=[{"role":"user","content":"海盐"},{"role":"assistant","content":"收到"}]
            store.save(messages)
            self.assertEqual(store.load(), messages)
            self.assertIn("海盐", path.read_text(encoding="utf-8"))

    def test_invalid_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"m.json"; path.write_text("{broken",encoding="utf-8")
            with self.assertRaises(MemoryFormatError): ConversationStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_rejects_bad_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"m.json"
            path.write_text(json.dumps({"schema_version":1,"messages":[{"role":"system","content":"x"}]}),encoding="utf-8")
            with self.assertRaises(MemoryFormatError): ConversationStore(path).load()

    def test_forget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"m.json"; store=ConversationStore(path)
            store.save([{"role":"user","content":"x"}])
            self.assertTrue(store.forget())
            self.assertFalse(store.forget())
            self.assertEqual(store.load(), [])

    def test_no_temp_files_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"m.json"; ConversationStore(path).save([{"role":"user","content":"x"}])
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


if __name__ == "__main__": unittest.main()
