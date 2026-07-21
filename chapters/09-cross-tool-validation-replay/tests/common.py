from pathlib import Path
import tempfile
import unittest

from workflow import CrossToolRuntime


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = CrossToolRuntime(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, workflow_id="wf_test", title="标题", content="内容\n", path="posts/a.md"):
        return self.runtime.create_plan(title, path, content, workflow_id)
