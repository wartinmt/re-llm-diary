from pathlib import Path

class ToolPlugin:
    def __init__(self, workspace: Path): self.workspace = workspace
    def probe(self, payload): return {"ok": True, "mode": "read_only"}
    def preview(self, payload):
        query = str(payload.get("query", "")).strip()
        return {"query": query, "answer": {"runtime": "运行时协调层", "receipt": "持久回执"}.get(query.lower(), "未命中")}
