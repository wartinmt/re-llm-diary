from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]

class TempPluginMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def copy_plugin(self, name):
        dest = self.root / name
        shutil.copytree(ROOT / "plugins" / name, dest)
        return dest
