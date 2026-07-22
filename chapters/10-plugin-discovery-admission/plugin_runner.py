from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def load_class(source: Path):
    spec = importlib.util.spec_from_file_location("runtime_candidate_plugin", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载插件。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, "ToolPlugin", None)
    if cls is None:
        raise RuntimeError("入口模块没有 ToolPlugin。")
    return cls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--method", required=True, choices=["probe", "preview", "execute", "query", "compensate"])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()
    payload = json.loads(args.payload)
    cls = load_class(Path(args.source))
    plugin = cls(Path(args.workspace))
    result = getattr(plugin, args.method)(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
