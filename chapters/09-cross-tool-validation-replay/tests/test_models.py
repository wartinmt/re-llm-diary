import unittest
from models import StepPlan, WorkflowPlan, ToolReceipt, ValidationResult, WorkflowResult, canonical_json, digest_text

class ModelTests(unittest.TestCase):
    def test_01_digest_stable(self): self.assertEqual(digest_text("a"), digest_text("a"))
    def test_02_digest_changes(self): self.assertNotEqual(digest_text("a"), digest_text("b"))
    def test_03_canonical_order(self): self.assertEqual(canonical_json({"b":1,"a":2}), '{"a":2,"b":1}')
    def test_04_step_to_dict(self): self.assertEqual(StepPlan("s","t","k",("a",),{}).to_dict()["depends_on"], ["a"])
    def test_05_plan_roundtrip(self):
        p=WorkflowPlan("w","t","a","c",digest_text("c"),(StepPlan("s","t","k",(),{}),))
        self.assertEqual(WorkflowPlan.from_dict(p.to_dict()), p)
    def test_06_plan_hash_stable(self):
        p=WorkflowPlan("w","t","a","c",digest_text("c"),())
        self.assertEqual(p.plan_hash(), p.plan_hash())
    def test_07_plan_hash_changes(self):
        a=WorkflowPlan("w","t","a","c",digest_text("c"),())
        b=WorkflowPlan("w","t","a","d",digest_text("d"),())
        self.assertNotEqual(a.plan_hash(), b.plan_hash())
    def test_08_receipt_roundtrip(self):
        r=ToolReceipt("r","t","k","op","e","applied",{"x":1})
        self.assertEqual(ToolReceipt.from_dict(r.to_dict()), r)
    def test_09_validation_result(self): self.assertTrue(ValidationResult(True,{"x":True},"ok").ok)
    def test_10_workflow_result(self): self.assertEqual(WorkflowResult("w","complete",("s",),"ok").completed_steps, ("s",))
