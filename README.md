# claude-skill-marketplace

Build a Claude Code `/plugin` marketplace from a directory of `.skill` archives
or `SKILL.md` packages.

## Why

[Claude Code skills](https://code.claude.com/docs) dropped into
`~/.claude/skills/` are **auto-loaded** into every session's system reminder.
Installing a collection of 20+ skills that way bloats every context, even when
you only want one.

Claude Code's [plugin marketplace](https://code.claude.com/docs/en/discover-plugins)
solves this: users can browse and toggle individual plugins on demand with
`/plugin`. But authoring the marketplace manifest and per-plugin scaffolding by
hand for a large collection is tedious.

This tool takes an existing collection and produces the scaffolding for you.

## Install

```bash
pip install claude-skill-marketplace
# or, from source:
pip install git+https://github.com/lobsterclause/claude-skill-marketplace
```

Requires Python 3.10+. No runtime dependencies.

## Usage

```bash
claude-skill-marketplace \
  --source path/to/skill-collection \
  --output path/to/marketplace-repo \
  --name my-skills \
  --description "My curated Claude Code skills" \
  --owner-name "Your Name" \
  --owner-url https://github.com/yourname \
  --author-name "Upstream Author" \
  --plugin-version 0.1.0
```

Outputs:

```
<output>/
├── .claude-plugin/
│   └── marketplace.json           # lists every plugin
└── plugins/
    └── <skill-name>/
        ├── .claude-plugin/plugin.json
        └── skills/<skill-name>/SKILL.md
```

Then from any Claude Code session:

```bash
claude plugin marketplace add yourname/your-marketplace-repo
/plugin                            # browse + enable only the skills you want
```

### Dry run

Add `--dry-run` to see which skills would be written, without touching the
filesystem.

### Flags

| Flag | Required | Purpose |
| --- | --- | --- |
| `--source` | no (default: cwd) | Directory to walk for `.skill` archives + `SKILL.md` packages |
| `--output` | no (default: same as `--source`) | Where to write `plugins/` and `.claude-plugin/marketplace.json` |
| `--name` | yes | Marketplace name |
| `--description` | yes | Marketplace description |
| `--owner-name` | yes | Marketplace owner name |
| `--owner-url` / `--owner-email` | no | Owner contact |
| `--author-name` / `--author-url` / `--author-email` | no | Author attached to every generated `plugin.json` — use this to credit the upstream author of the skills |
| `--plugin-version` | no (default `0.1.0`) | Version written into every `plugin.json` |
| `--plugins-dirname` | no (default `plugins`) | Name of the generated plugins directory |
| `--dry-run` | no | Discover and list without writing |

## What gets discovered

The walker handles two input formats under `--source`:

1. **`*.skill` archives** — zip files containing a `SKILL.md` (at the root, or
   nested one level deep like `<name>/SKILL.md`).
2. **`SKILL.md` packages** — any directory containing a `SKILL.md` with valid
   frontmatter.

Both formats need YAML frontmatter with at minimum:

```yaml
---
name: my-skill
description: What this skill does (shown in /plugin search results)
---
```

Additional frontmatter fields are preserved in the extracted `SKILL.md` but
aren't used for the manifest.

Skills with duplicate `name`s are deduped — first one wins, a warning is printed
to stderr.

## Library use

```python
from pathlib import Path
from claude_skill_marketplace import build_marketplace
from claude_skill_marketplace.builder import Owner

build_marketplace(
    source=Path("./my-skills"),
    output=Path("./my-marketplace"),
    marketplace_name="my-skills",
    marketplace_description="Personal skill collection",
    owner=Owner(name="me", url="https://github.com/me"),
)
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use a committed fixture at `tests/fixtures/sample.skill`. Regenerate with
`python tests/fixtures/make_fixture.py` if the fixture contents need to change.

## License

MIT
