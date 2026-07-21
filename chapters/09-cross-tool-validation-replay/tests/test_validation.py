from validation import validate_document, validate_index
from common import RuntimeCase

class ValidationTests(RuntimeCase):
    def test_41_missing_document(self): self.assertFalse(validate_document(self.runtime.documents_root,self.plan()).ok)
    def test_42_correct_document(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,p.content); self.assertTrue(validate_document(self.runtime.documents_root,p).ok)
    def test_43_wrong_document(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,"wrong"); self.assertFalse(validate_document(self.runtime.documents_root,p).ok)
    def test_44_missing_index(self): self.assertFalse(validate_index(self.runtime.index_tool,self.runtime.documents_root,self.plan()).ok)
    def test_45_correct_index(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,p.content); self.runtime.index_tool.register(p.steps[1].idempotency_key,p.title,p.document_path,p.content_sha256); self.assertTrue(validate_index(self.runtime.index_tool,self.runtime.documents_root,p).ok)
    def test_46_wrong_index_hash(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,p.content); self.runtime.index_tool.register(p.steps[1].idempotency_key,p.title,p.document_path,"0"*64); self.assertFalse(validate_index(self.runtime.index_tool,self.runtime.documents_root,p).ok)
    def test_47_wrong_index_path(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,p.content); self.runtime.index_tool.register(p.steps[1].idempotency_key,p.title,"wrong",p.content_sha256); self.assertFalse(validate_index(self.runtime.index_tool,self.runtime.documents_root,p).ok)
    def test_48_disk_changes_after_index(self):
        p=self.plan(); self.runtime.document_tool.write(p.steps[0].idempotency_key,p.document_path,p.content); self.runtime.index_tool.register(p.steps[1].idempotency_key,p.title,p.document_path,p.content_sha256); (self.runtime.documents_root/p.document_path).write_text("changed",encoding="utf-8"); self.assertFalse(validate_index(self.runtime.index_tool,self.runtime.documents_root,p).ok)
