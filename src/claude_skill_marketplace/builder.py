"""Core builder logic: discover skills, write plugin scaffolding + marketplace manifest."""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Skill:
    name: str
    description: str
    skill_md: str
    source_hint: str


@dataclass
class Owner:
    name: str
    url: str | None = None
    email: str | None = None

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {"name": self.name}
        if self.url:
            d["url"] = self.url
        if self.email:
            d["email"] = self.email
        return d


def parse_frontmatter(skill_md: str) -> dict[str, str]:
    """Parse YAML-ish frontmatter from a SKILL.md body.

    Only the small subset needed here (flat key: value, with simple continuation
    indentation) — we don't want a runtime yaml dependency just for this.
    """
    if not skill_md.startswith("---\n"):
        raise ValueError("SKILL.md missing YAML frontmatter")
    end = skill_md.find("\n---", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter not closed")
    block = skill_md[4:end]
    meta: dict[str, str] = {}
    current_key: str | None = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        if raw[0] in " \t" and current_key is not None:
            meta[current_key] += " " + raw.strip()
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        current_key = key.strip()
        meta[current_key] = value.strip()
    if "name" not in meta or "description" not in meta:
        raise ValueError(f"SKILL.md frontmatter missing name/description: {meta}")
    return meta


def _load_from_archive(path: Path) -> Skill:
    with zipfile.ZipFile(path) as zf:
        name = next((n for n in zf.namelist() if n.endswith("SKILL.md")), None)
        if name is None:
            raise ValueError(f"{path}: no SKILL.md in archive")
        skill_md = zf.read(name).decode("utf-8")
    meta = parse_frontmatter(skill_md)
    return Skill(
        name=meta["name"],
        description=meta["description"],
        skill_md=skill_md,
        source_hint=str(path),
    )


def _load_from_package(skill_md_path: Path) -> Skill:
    skill_md = skill_md_path.read_text(encoding="utf-8")
    meta = parse_frontmatter(skill_md)
    return Skill(
        name=meta["name"],
        description=meta["description"],
        skill_md=skill_md,
        source_hint=str(skill_md_path),
    )


def collect_skills(
    source_root: Path,
    *,
    warn: callable = lambda msg: print(msg, file=sys.stderr),
) -> list[Skill]:
    """Walk source_root for .skill archives and SKILL.md packages; dedupe by name."""
    skills: dict[str, Skill] = {}

    for archive in sorted(source_root.rglob("*.skill")):
        try:
            skill = _load_from_archive(archive)
        except (zipfile.BadZipFile, ValueError) as exc:
            warn(f"skip {archive}: {exc}")
            continue
        if skill.name in skills:
            warn(
                f"duplicate skill name {skill.name!r} "
                f"({skills[skill.name].source_hint} vs {skill.source_hint}); keeping first"
            )
            continue
        skills[skill.name] = skill

    for skill_md_path in sorted(source_root.rglob("SKILL.md")):
        # Ignore SKILL.md files we already generated under the output tree — the
        # caller passes a separate output dir; but a user might run the builder
        # against a tree that already contains a plugins/ directory.
        if skill_md_path.parts[-3:-2] and skill_md_path.parts[-3] == "skills":
            continue
        try:
            skill = _load_from_package(skill_md_path)
        except ValueError as exc:
            warn(f"skip {skill_md_path}: {exc}")
            continue
        if skill.name in skills:
            warn(
                f"duplicate skill name {skill.name!r} "
                f"({skills[skill.name].source_hint} vs {skill.source_hint}); keeping first"
            )
            continue
        skills[skill.name] = skill

    return sorted(skills.values(), key=lambda s: s.name)


def _write_plugin(
    skill: Skill,
    plugins_dir: Path,
    *,
    author: Owner | None,
    version: str,
) -> None:
    plugin_root = plugins_dir / skill.name
    skill_dir = plugin_root / "skills" / skill.name
    meta_dir = plugin_root / ".claude-plugin"
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill.skill_md, encoding="utf-8")
    plugin_json: dict[str, object] = {
        "name": skill.name,
        "version": version,
        "description": skill.description,
    }
    if author is not None:
        plugin_json["author"] = author.to_dict()
    (meta_dir / "plugin.json").write_text(
        json.dumps(plugin_json, indent=2) + "\n", encoding="utf-8"
    )


def _write_marketplace(
    skills: Iterable[Skill],
    manifest_path: Path,
    *,
    name: str,
    description: str,
    owner: Owner,
    plugins_rel_dir: str,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": name,
        "description": description,
        "metadata": {"description": description},
        "owner": owner.to_dict(),
        "plugins": [
            {
                "name": s.name,
                "description": s.description,
                "source": f"./{plugins_rel_dir}/{s.name}",
            }
            for s in skills
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_marketplace(
    source: Path,
    output: Path,
    *,
    marketplace_name: str,
    marketplace_description: str,
    owner: Owner,
    author: Owner | None = None,
    plugin_version: str = "0.1.0",
    plugins_dirname: str = "plugins",
    dry_run: bool = False,
) -> list[Skill]:
    """Build a marketplace under `output` from skills found under `source`.

    Clears and rewrites `output/plugins_dirname/` plus `output/.claude-plugin/marketplace.json`.
    Returns the list of skills written (empty if dry_run or no skills found).
    """
    source = source.resolve()
    output = output.resolve()
    skills = collect_skills(source)
    if not skills:
        return []

    if dry_run:
        return skills

    plugins_dir = output / plugins_dirname
    manifest_path = output / ".claude-plugin" / "marketplace.json"

    if plugins_dir.exists():
        shutil.rmtree(plugins_dir)

    for skill in skills:
        _write_plugin(skill, plugins_dir, author=author, version=plugin_version)

    _write_marketplace(
        skills,
        manifest_path,
        name=marketplace_name,
        description=marketplace_description,
        owner=owner,
        plugins_rel_dir=plugins_dirname,
    )
    return skills
