"""Command-line interface for building a marketplace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_skill_marketplace.builder import Owner, build_marketplace


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-skill-marketplace",
        description=(
            "Build a Claude Code /plugin marketplace from a tree of .skill "
            "archives and SKILL.md packages."
        ),
    )
    p.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Directory to walk for .skill archives and SKILL.md packages (default: cwd)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory to write plugins/ and .claude-plugin/marketplace.json into (default: same as --source)",
    )
    p.add_argument(
        "--name",
        required=True,
        help="Marketplace name (written to marketplace.json)",
    )
    p.add_argument(
        "--description",
        required=True,
        help="Marketplace description",
    )
    p.add_argument("--owner-name", required=True, help="Owner name for the marketplace")
    p.add_argument("--owner-url", default=None, help="Owner URL (optional)")
    p.add_argument("--owner-email", default=None, help="Owner email (optional)")
    p.add_argument(
        "--author-name",
        default=None,
        help="Author name attached to every generated plugin.json (optional; e.g. the upstream author)",
    )
    p.add_argument("--author-url", default=None)
    p.add_argument("--author-email", default=None)
    p.add_argument(
        "--plugin-version",
        default="0.1.0",
        help='Version string for every generated plugin.json (default: "0.1.0")',
    )
    p.add_argument(
        "--plugins-dirname",
        default="plugins",
        help='Name of the generated plugins directory (default: "plugins")',
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover skills and print what would be written, without touching the filesystem",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    source = args.source
    output = args.output if args.output is not None else source

    if not source.exists():
        parser.error(f"--source {source} does not exist")

    owner = Owner(name=args.owner_name, url=args.owner_url, email=args.owner_email)
    author: Owner | None = None
    if args.author_name:
        author = Owner(
            name=args.author_name, url=args.author_url, email=args.author_email
        )

    skills = build_marketplace(
        source=source,
        output=output,
        marketplace_name=args.name,
        marketplace_description=args.description,
        owner=owner,
        author=author,
        plugin_version=args.plugin_version,
        plugins_dirname=args.plugins_dirname,
        dry_run=args.dry_run,
    )

    if not skills:
        print(f"no skills found under {source}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[dry-run] would write {len(skills)} plugins:")
        for s in skills:
            print(f"  - {s.name}  ({s.source_hint})")
        return 0

    print(f"wrote {len(skills)} plugins to {output}/{args.plugins_dirname}/")
    print(f"wrote marketplace manifest to {output}/.claude-plugin/marketplace.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
