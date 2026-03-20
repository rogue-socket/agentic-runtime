from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = Path(__file__).resolve().parent
OUT_PATH = SITE_DIR / "content.js"


# [Pain Point Partial] #N12 Workflow Drift from Documentation: This bundler
#   auto-aggregates all markdown into the doc site, but it doesn't auto-generate
#   documentation from workflow YAML definitions (inputs, steps, contracts).
# TODO(Pain Point #N12 — Workflow Drift): Add an `ai docs` command or build step
#   that auto-generates documentation from workflow YAML — listing inputs, steps,
#   contracts, and branch conditions. When the workflow IS the documentation source,
#   drift becomes impossible.
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
