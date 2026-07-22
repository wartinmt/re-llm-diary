from pathlib import Path

class ToolPlugin:
    def __init__(self, workspace: Path): self.workspace = workspace
    def probe(self, payload):
        (self.workspace / "should-not-exist.txt").write_text("side effect", encoding="utf-8")
        return {"ok": True}
    def preview(self, payload): return {"ok": True}
