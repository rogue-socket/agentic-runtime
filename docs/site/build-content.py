from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT / "content.js"


# This script is used by `ai docs` to regenerate docs/site/content.js.
_SKIP = {"content.js", "app.js", "styles.css", "build-content.py", "mermaid.min.js"}

def build() -> None:
    docs = {}
    for path in ROOT.rglob("*.md"):
        if path.name in _SKIP:
            continue
        rel = path.relative_to(ROOT).as_posix()
        docs[rel] = path.read_text(encoding="utf-8")

    OUT_PATH.write_text("window.DOCS = " + json.dumps(docs) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} with {len(docs)} docs")


if __name__ == "__main__":
    build()
