"""Build a Claude Code /plugin marketplace from .skill archives and SKILL.md packages."""

from claude_skill_marketplace.builder import (
    Skill,
    build_marketplace,
    collect_skills,
    parse_frontmatter,
)

__all__ = ["Skill", "build_marketplace", "collect_skills", "parse_frontmatter"]
__version__ = "0.1.0"
