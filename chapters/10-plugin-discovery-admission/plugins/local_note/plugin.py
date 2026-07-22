from pathlib import Path
import hashlib

class ToolPlugin:
    def __init__(self, workspace: Path): self.workspace = workspace
    def probe(self, payload): return {"ok": True, "writable": True}
    def preview(self, payload): return {"would_write": f"{payload.get('directory')}/{payload.get('title')}.md"}
    def execute(self, payload):
        directory = self.workspace / str(payload["directory"])
        directory.mkdir(parents=True, exist_ok=True)
        safe = str(payload["title"]).replace("/", "-").replace("\\", "-")
        path = directory / f"{safe}.md"
        content = f"# {payload['title']}\n"
        path.write_text(content, encoding="utf-8")
        return {"path": str(path.relative_to(self.workspace)), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    def query(self, payload):
        path = self.workspace / str(payload["path"])
        return {"exists": path.exists()}
    def compensate(self, payload):
        path = self.workspace / str(payload["path"]); existed = path.exists(); path.unlink(missing_ok=True)
        return {"removed": existed}
