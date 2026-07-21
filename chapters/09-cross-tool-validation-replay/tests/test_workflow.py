from workflow import CrossToolRuntime, SimulatedCrash
from common import RuntimeCase

class WorkflowTests(RuntimeCase):
    def test_49_success(self):
        p=self.plan(); self.assertEqual(self.runtime.execute(p.workflow_id).status,"complete")
    def test_50_validation_failure(self):
        p=self.plan(); self.assertEqual(self.runtime.execute(p.workflow_id,wrong_index_hash="0"*64).status,"validation_failed")
    def test_51_no_completion_on_failure(self):
        p=self.plan(); self.runtime.execute(p.workflow_id,wrong_index_hash="0"*64); self.assertFalse(any(e["event_type"]=="workflow_completed" for e in self.runtime.replay(p.workflow_id)))
    def test_52_resume_recovers_receipt(self):
        p=self.plan();
        with self.assertRaises(SimulatedCrash): self.runtime.execute(p.workflow_id,crash_after_document_tool=True)
        rt=CrossToolRuntime(self.root); self.assertEqual(rt.execute(p.workflow_id).status,"complete"); self.assertTrue(any(e["event_type"]=="step_receipt_recovered" for e in rt.replay(p.workflow_id)))
    def test_53_resume_single_file(self):
        p=self.plan();
        with self.assertRaises(SimulatedCrash): self.runtime.execute(p.workflow_id,crash_after_document_tool=True)
        CrossToolRuntime(self.root).execute(p.workflow_id); self.assertEqual(len(list((self.root/"documents").rglob("*.md"))),1)
    def test_54_rollback_reverse(self):
        p=self.plan(); self.runtime.execute(p.workflow_id); r=self.runtime.rollback(p.workflow_id); self.assertEqual(r.completed_steps,("register_index","write_document"))
    def test_55_rollback_removes_effects(self):
        p=self.plan(); self.runtime.execute(p.workflow_id); self.runtime.rollback(p.workflow_id); self.assertFalse((self.runtime.documents_root/p.document_path).exists()); self.assertIsNone(self.runtime.index_tool.record(p.title))
    def test_56_plan_immutable(self):
        self.plan();
        with self.assertRaises(RuntimeError): self.runtime.create_plan("其他","posts/a.md","内容\n","wf_test")
    def test_57_replay_read_only(self):
        p=self.plan(); self.runtime.execute(p.workflow_id); before=self.runtime.journal.path.read_bytes(); self.runtime.replay(p.workflow_id); self.assertEqual(before,self.runtime.journal.path.read_bytes())
