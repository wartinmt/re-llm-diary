import json
import tempfile
import unittest
from pathlib import Path

from journal import JournalFormatError, RecoveryBlocked, TaskJournal
from memory import ConversationStore
from recovery import recover_local_task


class JournalTests(unittest.TestCase):
    def test_missing_journal_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            self.assertEqual(journal.load(), [])

    def test_append_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            journal = TaskJournal(path)
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "route_selected", {"provider": "a"})
            loaded = TaskJournal(path).load()
            self.assertEqual([e.kind for e in loaded], ["task_created", "route_selected"])

    def test_content_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            journal = TaskJournal(path)
            journal.create_task("hello")
            text = path.read_text(encoding="utf-8").replace("hello", "changed")
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(JournalFormatError):
                TaskJournal(path).load()

    def test_sequence_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            journal = TaskJournal(path)
            journal.create_task("hello")
            item = json.loads(path.read_text(encoding="utf-8"))
            item["seq"] = 2
            path.write_text(json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaises(JournalFormatError):
                TaskJournal(path).load()

    def test_trailing_partial_can_be_repaired_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            journal = TaskJournal(path)
            journal.create_task("hello")
            with path.open("ab") as handle:
                handle.write(b'{"partial":')
            with self.assertRaises(JournalFormatError):
                TaskJournal(path).load()
            backup = TaskJournal(path).repair_trailing_partial()
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            self.assertEqual(len(TaskJournal(path).load()), 1)

    def test_created_task_is_safe_to_send_but_not_auto_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, _ = journal.create_task("hello")
            plan = journal.plan(task_id)
            self.assertEqual(plan.status, "safe_to_send")
            self.assertFalse(plan.can_resume_without_api)

    def test_primary_response_is_local_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "request_sent", {"call_id": "x", "role": "primary", "provider": "a"})
            journal.append(task_id, attempt, "response_received", {"call_id": "x", "role": "primary", "provider": "a", "answer": "ok"})
            self.assertEqual(journal.plan(task_id).status, "local_finalize")

    def test_final_answer_is_local_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "final_answer_ready", {"answer": "ok", "provider": "a"})
            self.assertEqual(journal.plan(task_id).status, "local_commit")

    def test_memory_commit_is_finish_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "memory_committed", {})
            self.assertEqual(journal.plan(task_id).status, "finish_only")

    def test_sent_without_response_is_remote_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "request_sent", {"call_id": "x", "role": "primary", "provider": "a"})
            self.assertEqual(journal.plan(task_id).status, "remote_unknown")
            with self.assertRaises(RecoveryBlocked):
                recover_local_task(journal, ConversationStore(Path(tmp) / "memory.json"), task_id)

    def test_local_recovery_uses_saved_answer_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = TaskJournal(root / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "request_sent", {"call_id": "x", "role": "primary", "provider": "a"})
            journal.append(task_id, attempt, "response_received", {"call_id": "x", "role": "primary", "provider": "a", "answer": "ok"})
            memory = ConversationStore(root / "memory.json")
            result = recover_local_task(journal, memory, task_id)
            self.assertEqual(result.answer, "ok")
            self.assertEqual(memory.load()[-1]["content"], "ok")
            self.assertEqual(journal.plan(task_id).status, "complete")

    def test_recovery_does_not_duplicate_existing_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = TaskJournal(root / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "final_answer_ready", {"answer": "ok", "provider": "a"})
            memory = ConversationStore(root / "memory.json")
            memory.save([{"role": "user", "content": "hello"}, {"role": "assistant", "content": "ok"}])
            result = recover_local_task(journal, memory, task_id)
            self.assertFalse(result.changed_memory)
            self.assertEqual(len(memory.load()), 2)

    def test_retry_requires_confirmation_and_new_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TaskJournal(Path(tmp) / "tasks.jsonl")
            task_id, attempt = journal.create_task("hello")
            journal.append(task_id, attempt, "request_sent", {"call_id": "x", "role": "primary", "provider": "a"})
            with self.assertRaises(RecoveryBlocked):
                journal.authorize_retry(task_id, "yes")
            new_attempt, prompt = journal.authorize_retry(task_id, "CONFIRM")
            self.assertEqual(new_attempt, 2)
            self.assertEqual(prompt, "hello")
            self.assertEqual(journal.plan(task_id).status, "safe_to_send")


if __name__ == "__main__":
    unittest.main()
