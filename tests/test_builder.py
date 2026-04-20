"""Tests for the marketplace builder."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from claude_skill_marketplace.builder import (
    Owner,
    build_marketplace,
    collect_skills,
    parse_frontmatter,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_SKILL = FIXTURES / "sample.skill"


def test_parse_frontmatter_basic():
    body = "---\nname: foo\ndescription: hello\n---\n# heading"
    meta = parse_frontmatter(body)
    assert meta == {"name": "foo", "description": "hello"}


def test_parse_frontmatter_multiline_continuation():
    body = (
        "---\n"
        "name: foo\n"
        "description: line one\n"
        "  continued here\n"
        "---\n"
    )
    meta = parse_frontmatter(body)
    assert meta["description"] == "line one continued here"


def test_parse_frontmatter_missing_fields_raises():
    with pytest.raises(ValueError, match="missing name/description"):
        parse_frontmatter("---\nname: foo\n---\n")


def test_parse_frontmatter_no_frontmatter_raises():
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        parse_frontmatter("# just a heading\n")


def test_collect_skills_finds_archive(tmp_path: Path):
    shutil.copy(SAMPLE_SKILL, tmp_path / "sample.skill")
    skills = collect_skills(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "sample-skill"
    assert "fixture skill" in skills[0].description


def test_collect_skills_finds_package(tmp_path: Path):
    pkg = tmp_path / "my-skill"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: a package skill\n---\n# body\n"
    )
    skills = collect_skills(tmp_path)
    assert [s.name for s in skills] == ["my-skill"]


def test_collect_skills_dedupes_by_name(tmp_path: Path):
    shutil.copy(SAMPLE_SKILL, tmp_path / "a.skill")
    shutil.copy(SAMPLE_SKILL, tmp_path / "b.skill")
    skills = collect_skills(tmp_path, warn=lambda _msg: None)
    assert len(skills) == 1


def test_collect_skills_handles_nested_skill_md_in_archive(tmp_path: Path):
    archive = tmp_path / "nested.skill"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "wrapper/SKILL.md",
            "---\nname: nested-skill\ndescription: ok\n---\n",
        )
    skills = collect_skills(tmp_path)
    assert [s.name for s in skills] == ["nested-skill"]


def test_build_marketplace_writes_expected_tree(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(SAMPLE_SKILL, source / "sample.skill")

    output = tmp_path / "out"
    owner = Owner(name="tester", url="https://example.com")
    author = Owner(name="upstream", url="https://example.com/upstream")

    written = build_marketplace(
        source=source,
        output=output,
        marketplace_name="test-marketplace",
        marketplace_description="a test marketplace",
        owner=owner,
        author=author,
    )
    assert [s.name for s in written] == ["sample-skill"]

    plugin_json_path = (
        output / "plugins" / "sample-skill" / ".claude-plugin" / "plugin.json"
    )
    skill_md_path = output / "plugins" / "sample-skill" / "skills" / "sample-skill" / "SKILL.md"
    manifest_path = output / ".claude-plugin" / "marketplace.json"

    assert skill_md_path.exists()
    assert "sample-skill" in skill_md_path.read_text()

    plugin = json.loads(plugin_json_path.read_text())
    assert plugin["name"] == "sample-skill"
    assert plugin["author"] == {"name": "upstream", "url": "https://example.com/upstream"}

    manifest = json.loads(manifest_path.read_text())
    assert manifest["name"] == "test-marketplace"
    assert manifest["owner"]["name"] == "tester"
    assert len(manifest["plugins"]) == 1
    assert manifest["plugins"][0]["source"] == "./plugins/sample-skill"


def test_build_marketplace_dry_run_writes_nothing(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(SAMPLE_SKILL, source / "sample.skill")

    output = tmp_path / "out"
    skills = build_marketplace(
        source=source,
        output=output,
        marketplace_name="x",
        marketplace_description="y",
        owner=Owner(name="t"),
        dry_run=True,
    )
    assert len(skills) == 1
    assert not output.exists()


def test_build_marketplace_idempotent_regenerates_plugins_dir(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(SAMPLE_SKILL, source / "sample.skill")
    output = tmp_path / "out"

    kwargs = dict(
        source=source,
        output=output,
        marketplace_name="x",
        marketplace_description="y",
        owner=Owner(name="t"),
    )
    build_marketplace(**kwargs)
    stale = output / "plugins" / "ghost-skill" / "marker"
    stale.parent.mkdir(parents=True)
    stale.write_text("should be wiped")
    build_marketplace(**kwargs)

    assert not stale.exists()
    assert (output / "plugins" / "sample-skill").exists()


def test_build_marketplace_preserves_package_support_dirs(tmp_path: Path):
    """Skills shipped as a directory (SKILL.md + siblings) must have siblings
    preserved in the generated plugin wrapper. Without this, any skill whose
    SKILL.md references scripts/, references/, or assets/ ships broken."""
    source = tmp_path / "src"
    pkg = source / "my-skill"
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: pkg skill with support files\n---\n"
    )
    (pkg / "scripts").mkdir()
    (pkg / "scripts" / "run.sh").write_text("#!/usr/bin/env bash\necho hi\n")
    (pkg / "references").mkdir()
    (pkg / "references" / "notes.md").write_text("# notes\n")
    (pkg / "assets").mkdir()
    (pkg / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    output = tmp_path / "out"
    build_marketplace(
        source=source,
        output=output,
        marketplace_name="m",
        marketplace_description="d",
        owner=Owner(name="t"),
    )

    skill_dir = output / "plugins" / "my-skill" / "skills" / "my-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "run.sh").read_text().startswith("#!/usr/bin/env bash")
    assert (skill_dir / "references" / "notes.md").read_text() == "# notes\n"
    assert (skill_dir / "assets" / "logo.png").read_bytes().startswith(b"\x89PNG")


def test_build_marketplace_skips_noise_in_package(tmp_path: Path):
    source = tmp_path / "src"
    pkg = source / "noisy-skill"
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        "---\nname: noisy-skill\ndescription: has noise\n---\n"
    )
    (pkg / ".git").mkdir()
    (pkg / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "foo.cpython-311.pyc").write_bytes(b"bogus")
    (pkg / ".DS_Store").write_bytes(b"noise")
    (pkg / "real.txt").write_text("keep me\n")

    output = tmp_path / "out"
    build_marketplace(
        source=source,
        output=output,
        marketplace_name="m",
        marketplace_description="d",
        owner=Owner(name="t"),
    )

    skill_dir = output / "plugins" / "noisy-skill" / "skills" / "noisy-skill"
    assert (skill_dir / "real.txt").exists()
    assert not (skill_dir / ".git").exists()
    assert not (skill_dir / "__pycache__").exists()
    assert not (skill_dir / ".DS_Store").exists()


def test_build_marketplace_preserves_archive_support_files(tmp_path: Path):
    """.skill archives that bundle support files must also have them extracted
    into the plugin wrapper — symmetric with the package-dir path."""
    source = tmp_path / "src"
    source.mkdir()
    archive = source / "packed.skill"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "packed/SKILL.md",
            "---\nname: packed-skill\ndescription: archive with extras\n---\n",
        )
        zf.writestr("packed/scripts/helper.sh", "#!/bin/sh\necho ok\n")
        zf.writestr("packed/references/guide.md", "# guide\n")

    output = tmp_path / "out"
    build_marketplace(
        source=source,
        output=output,
        marketplace_name="m",
        marketplace_description="d",
        owner=Owner(name="t"),
    )

    skill_dir = output / "plugins" / "packed-skill" / "skills" / "packed-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "helper.sh").read_text() == "#!/bin/sh\necho ok\n"
    assert (skill_dir / "references" / "guide.md").read_text() == "# guide\n"


def test_build_marketplace_archive_with_flat_layout(tmp_path: Path):
    """Archives without a wrapper dir still extract cleanly."""
    source = tmp_path / "src"
    source.mkdir()
    archive = source / "flat.skill"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: flat-skill\ndescription: no wrapper dir\n---\n",
        )
        zf.writestr("extra.txt", "side\n")

    output = tmp_path / "out"
    build_marketplace(
        source=source,
        output=output,
        marketplace_name="m",
        marketplace_description="d",
        owner=Owner(name="t"),
    )

    skill_dir = output / "plugins" / "flat-skill" / "skills" / "flat-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "extra.txt").read_text() == "side\n"
