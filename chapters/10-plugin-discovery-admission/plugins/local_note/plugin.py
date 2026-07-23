from pathlib import Path
import hashlib

class ToolPlugin:
    def __init__(self, workspace: Path): self.workspace = workspace
    def _safe_path(self, value):
        root = self.workspace.resolve()
        target = (root / str(value)).resolve()
        if target != root and root not in target.parents:
            raise ValueError("路径越过插件 workspace。")
        return target
    def probe(self, payload): return {"ok": True, "writable": True}
    def preview(self, payload):
        directory = self._safe_path(payload.get("directory"))
        safe = str(payload.get("title")).replace("/", "-").replace("\\", "-")
        path = self._safe_path(directory / f"{safe}.md")
        return {"would_write": str(path.relative_to(self.workspace.resolve()))}
    def execute(self, payload):
        directory = self._safe_path(payload["directory"])
        directory.mkdir(parents=True, exist_ok=True)
        directory = self._safe_path(directory)
        safe = str(payload["title"]).replace("/", "-").replace("\\", "-")
        path = self._safe_path(directory / f"{safe}.md")
        content = f"# {payload['title']}\n"
        path.write_text(content, encoding="utf-8")
        return {"path": str(path.relative_to(self.workspace.resolve())), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    def query(self, payload):
        path = self._safe_path(payload["path"])
        return {"exists": path.exists()}
    def compensate(self, payload):
        path = self._safe_path(payload["path"]); existed = path.exists(); path.unlink(missing_ok=True)
        return {"removed": existed}
