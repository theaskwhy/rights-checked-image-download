# Rights Checked Image Download — by The Ask Why Company

Safely retrieve a small, bounded set of images from a specific public URL when official image sources cannot provide them. Creates source manifests; downloads remain uncleared until a separate rights review.

Read the skill: [skills/rights-checked-image-download/SKILL.md](skills/rights-checked-image-download/SKILL.md)

Works with Claude (Claude Code, Claude.ai) and any tool that reads the open [Agent Skills](https://agentskills.io) `SKILL.md` format.

## Install in Claude

**Claude Code:**
```
/plugin marketplace add theaskwhy/rights-checked-image-download
/plugin install rights-checked-image-download@rights-checked-image-download
```

Or from the full catalogue: `/plugin marketplace add theaskwhy/skills` then `/plugin install rights-checked-image-download@theaskwhy`.

**Manual:** copy `skills/rights-checked-image-download/` into `~/.claude/skills/` (personal) or `.claude/skills/` (project).

**Claude.ai:** zip the `skills/rights-checked-image-download` folder and upload it under Settings → Capabilities → Skills.

## Use with other AI agents

This skill uses the open **Agent Skills** standard. The same `SKILL.md` works with compatible tools including OpenAI Codex, Cursor, Gemini CLI, GitHub Copilot, Windsurf, Antigravity, OpenCode, and Goose.

**Quick install:** the open-source `skills` installer detects supported tools:
```
npx skills add theaskwhy/rights-checked-image-download
```

**Manual:** copy `skills/rights-checked-image-download/` into your tool's skills folder:

| Tool | Personal (all projects) | One project |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| OpenAI Codex | `~/.codex/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `.cursor/skills/` |
| Gemini CLI / Antigravity | `~/.gemini/skills/` | `.gemini/skills/` |
| GitHub Copilot | `~/.copilot/skills/` | `.github/skills/` |
| Windsurf | — | `.windsurf/skills/` |
| Any spec-compliant agent | — | `.agents/skills/` |

For tools without skills support, paste `SKILL.md` into the tool's rules or instructions file.

## Licence

MIT. See [LICENSE](LICENSE).
