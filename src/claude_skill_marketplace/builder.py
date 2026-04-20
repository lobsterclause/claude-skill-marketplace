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
    # Exactly one of these is set, depending on how the skill was discovered.
    # Both are used by _write_plugin() to preserve supporting files (e.g.
    # scripts/, references/, assets/) alongside SKILL.md in the generated
    # plugin wrapper.
    package_dir: Path | None = None
    archive_path: Path | None = None


# Files/dirs we never want to copy from a skill's source into its plugin
# wrapper. VCS metadata, editor scratch, build artifacts, and anything the
# skill author marked hidden.
_COPY_IGNORE_NAMES = frozenset(
    {".git", ".DS_Store", "__pycache__", ".mypy_cache", ".pytest_cache",
     ".ruff_cache", "node_modules", ".venv", ".env"}
)


def _is_ignored(name: str) -> bool:
    return name in _COPY_IGNORE_NAMES or name.endswith(".pyc")


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
        archive_path=path,
    )


def _load_from_package(skill_md_path: Path) -> Skill:
    skill_md = skill_md_path.read_text(encoding="utf-8")
    meta = parse_frontmatter(skill_md)
    return Skill(
        name=meta["name"],
        description=meta["description"],
        skill_md=skill_md,
        source_hint=str(skill_md_path),
        package_dir=skill_md_path.parent,
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


def _copy_supporting_from_package(pkg_dir: Path, skill_dir: Path) -> None:
    """Copy everything from pkg_dir into skill_dir except SKILL.md and noise.

    Preserves arbitrary supporting content authors place alongside SKILL.md —
    scripts/, references/, assets/, evals/, whatever. Without this, plugins
    ship SKILL.md referencing files that don't exist in the wrapper.
    """
    for entry in pkg_dir.iterdir():
        if entry.name == "SKILL.md" or _is_ignored(entry.name):
            continue
        dest = skill_dir / entry.name
        if entry.is_dir():
            shutil.copytree(
                entry,
                dest,
                ignore=shutil.ignore_patterns(*_COPY_IGNORE_NAMES, "*.pyc"),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(entry, dest)


def _copy_supporting_from_archive(archive_path: Path, skill_dir: Path) -> None:
    """Extract archive contents into skill_dir except SKILL.md and noise.

    Archive layouts vary: some have a single top-level wrapper dir (common
    when zipped from a package), others are flat. We strip a single common
    top-level dir when every member shares it so the output matches the
    package-loaded layout (SKILL.md at skill_dir root, siblings next to it).

    Security: validates each destination path stays inside skill_dir. A
    malicious `.skill` archive could otherwise write outside the target via
    `../` traversal (Zip Slip / CWE-22). This matters: marketplaces exist to
    ingest third-party skills, which is exactly the attack surface.
    """
    skill_dir_resolved = skill_dir.resolve()
    with zipfile.ZipFile(archive_path) as zf:
        members = [m for m in zf.namelist() if not m.endswith("/")]
        if not members:
            return
        prefix = _common_top_level(members)
        for member in members:
            rel = member[len(prefix):] if prefix else member
            if not rel or rel.endswith("SKILL.md") or _is_ignored(Path(rel).name):
                continue
            if any(_is_ignored(part) for part in Path(rel).parts):
                continue
            # Reject path-traversal attempts up front; then double-check with
            # a resolved-path containment test in case symlinks or odd
            # normalization let something through the part-based check.
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                continue
            dest = skill_dir / rel
            try:
                dest.resolve().relative_to(skill_dir_resolved)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            info = zf.getinfo(member)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            # zip stores Unix mode bits in external_attr >> 16. copyfileobj
            # doesn't preserve them, so shell scripts would ship
            # non-executable. Apply the stored mode when present.
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                dest.chmod(mode)


# Top-level entries the archive may contain that shouldn't count when
# computing the shared wrapper prefix. macOS Finder zips include __MACOSX/
# alongside the real wrapper; a stray README at root is also common. Without
# this filter, one stray entry collapses the prefix to empty and every
# extracted file ends up nested inside the wrapper dir instead of flat.
_TOP_LEVEL_NOISE = frozenset({"__MACOSX", ".DS_Store"})


def _common_top_level(names: list[str]) -> str:
    """Return the shared top-level dir (including trailing slash) or '' if none.

    Ignores standard noise entries (`__MACOSX`, `.DS_Store`) when deciding
    whether a prefix is shared — Finder-zipped archives on macOS would
    otherwise always defeat prefix stripping.
    """
    def _top(name: str) -> str:
        slash = name.find("/")
        return name if slash == -1 else name[:slash]

    def _is_noise(name: str) -> bool:
        return _top(name) in _TOP_LEVEL_NOISE

    signal = [n for n in names if not _is_noise(n)]
    if not signal:
        return ""
    first = signal[0]
    slash = first.find("/")
    if slash == -1:
        return ""
    prefix = first[: slash + 1]
    return prefix if all(n.startswith(prefix) for n in signal) else ""


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
    if skill.package_dir is not None:
        _copy_supporting_from_package(skill.package_dir, skill_dir)
    elif skill.archive_path is not None:
        _copy_supporting_from_archive(skill.archive_path, skill_dir)
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
