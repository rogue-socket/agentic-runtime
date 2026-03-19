from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = Path(__file__).resolve().parent
OUT_PATH = SITE_DIR / "content.js"


def build() -> None:
    docs = {}
    for path in ROOT.rglob("*.md"):
        if "site" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        docs[rel] = path.read_text(encoding="utf-8")

    OUT_PATH.write_text("window.DOCS = " + json.dumps(docs) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} with {len(docs)} docs")


if __name__ == "__main__":
    build()
