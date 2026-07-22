from pathlib import Path

class ToolPlugin:
    def __init__(self, workspace: Path): self.workspace = workspace
    def probe(self, payload): return {"ok": True}
    def preview(self, payload): return {"ok": True}
    def execute(self, payload): return {"ok": True}
