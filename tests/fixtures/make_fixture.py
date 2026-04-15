"""Regenerate tests/fixtures/sample.skill.

Run from the repo root: `python tests/fixtures/make_fixture.py`. Only needed
if the fixture content changes — the resulting .skill is committed.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

FIXTURE = Path(__file__).parent / "sample.skill"
SKILL_MD = """---
name: sample-skill
description: A tiny fixture skill used only to verify that claude-skill-marketplace can extract SKILL.md from a .skill archive and emit plugin scaffolding.
---

# Sample Skill

This skill exists solely as a test fixture.
"""


def main() -> None:
    with zipfile.ZipFile(FIXTURE, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", SKILL_MD)
    print(f"wrote {FIXTURE}")


if __name__ == "__main__":
    main()
