# `.claude/` — Agent Development Kit for the AFC bot

This repo is the AFC Discord bot: a single `bot.py` (~3.7k lines, sections marked `# ──`), no framework, no test suite. Most "fix the bot" work is a **prompt edit in `build_system_prompt()` (`bot.py:1045`)**, not a code edit.

This directory wires the repo to the five-layer **Agent Development Kit**. The canonical, project-agnostic blueprint lives at [`../agent-development-kit.md`](../agent-development-kit.md); the always-on rules are folded into [`../CLAUDE.md`](../CLAUDE.md) (L1). This file is the *where* — the map of what each artifact does.

## The five layers, as built here

| Layer | Role | Lives in |
|---|---|---|
| **L1 — Memory** | Always-on rules + constitution | [`../CLAUDE.md`](../CLAUDE.md) + [`../agent-development-kit.md`](../agent-development-kit.md) |
| **L2 — Skills** | Auto-invoked, description-matched knowledge | `.claude/skills/` |
| **L3 — Hooks** | Deterministic shell guardrails on tool events | `.claude/hooks/*.sh`, wired in `.claude/settings.json` |
| **L4 — Subagents** | Delegated work in an isolated context window | `.claude/agents/` |
| **L5 — Plugin** | Distributable bundle of L2–L4 | `../.claude-plugin/` |

## Directory layout

```
.claude/
├── settings.json                         # L3 — hook wiring (committed, shared)
├── settings.local.json                   # machine-local allowlist + MCP toggles (gitignored)
├── README.md                             # this file
├── skills/                               # L2
│   ├── editing-system-prompt/SKILL.md
│   ├── managing-knowledge-base/SKILL.md
│   ├── bot-background-loops/SKILL.md
│   └── deploying-the-bot/SKILL.md
├── agents/                               # L4
│   ├── code-reviewer.md
│   ├── prompt-auditor.md
│   └── bot-explorer.md
├── hooks/                                # L3
│   ├── block-knowledge-base-edit.sh
│   ├── pycompile-bot.sh
│   ├── block-npm.sh
│   └── block-ai-coauthor.sh
└── commands/                             # slash commands
    ├── scrape.md
    ├── add-knowledge.md
    └── syntax-check.md

.claude-plugin/                           # L5
├── plugin.json                           # plugin manifest
└── marketplace.json                      # marketplace listing (repo as installable source)
```

> Only `.claude/settings.local.json` is gitignored (a global `**/.claude/settings.local.json` rule). Everything else in `.claude/` and `.claude-plugin/` is committed and ships with the repo.

## L2 — Skills (auto-invoke when their description matches a task)

| Skill | Knows | Fires when |
|---|---|---|
| `editing-system-prompt` | The reply pipeline and every hard rule inside `build_system_prompt()` (`bot.py:1045`); the `needs_support` tuple contract | "fix the bot", "it said the wrong thing", "change how it talks", "wrong link", "didn't escalate" |
| `managing-knowledge-base` | The three knowledge layers and which to touch; `upload_docs.py`; the no-hand-edit rule for `knowledge_base.txt` | adding/fixing facts, updating rules/FAQ, staff-only info, refreshing scraped content |
| `bot-background-loops` | The 5 polling loops (lines, intervals, endpoints, channels), `seen_*.json` dedup + first-boot seeding, the event-time pitfall | editing/debugging any poll loop, announcements, dedup, or event live/ended logic |
| `deploying-the-bot` | Local run, worker dyno, Oracle Cloud Always Free (`deploy/oracle/`), env vars, `py_compile` gate | run, deploy, ship, redeploy, provision, host, restart |

## L3 — Hooks (deterministic; wired in `settings.json`)

| Hook | Event / matcher | What it does |
|---|---|---|
| `block-knowledge-base-edit.sh` | PreToolUse · `Edit\|Write\|MultiEdit` | Blocks edits to `knowledge_base.txt` (auto-scraped; hand-edits get overwritten) |
| `pycompile-bot.sh` | PostToolUse · `Edit\|Write\|MultiEdit` | After any edit to `bot.py`, runs `python -m py_compile bot.py`; surfaces syntax errors immediately (exit 2) |
| `block-npm.sh` | PreToolUse · `Bash` | Blocks any `npm` invocation (machine malware policy — use pnpm/bun) |
| `block-ai-coauthor.sh` | PreToolUse · `Bash` | Blocks `git commit`/`push` carrying an AI `Co-authored-by:` trailer (ADK rule 6) |

Each hook reads the tool-call JSON on stdin and exits `2` to block (its stderr is fed back to Claude). They are thin `bash` wrappers around `python -c` so they work identically on Windows (Git Bash) and POSIX — python handles path/env parsing.

## L4 — Subagents (delegate, get one result back)

| Subagent | Job |
|---|---|
| `code-reviewer` | Reviews a `bot.py` change against repo conventions before commit/merge (single-file discipline, the `needs_support` tuple, hard-rule regressions, `py_compile`). Read-only. |
| `prompt-auditor` | Audits any `build_system_prompt()` edit against the five authoritative hard rules (invite lockdown, the two support mechanisms, staff secrecy, classifier framing, support channel ID). Read-only. |
| `bot-explorer` | Fast read-only locator: behavior/symptom → owning section, function, and line range in `bot.py`. |

## Slash commands

`/scrape` (re-scrape into `knowledge_base.txt`) · `/add-knowledge <path>` (add a curated doc to `knowledge/`) · `/syntax-check` (`py_compile bot.py`).

## L5 — Distribution (and an honest caveat)

`../.claude-plugin/plugin.json` + `marketplace.json` package this repo as an installable Claude Code plugin.

**Important asymmetry:** Claude Code discovers *project-local* artifacts from `.claude/` (skills, agents, hooks via `settings.json`) — which is why the kit above is live in this repo with no install. But a *published plugin* discovers its components from the **plugin root** (`skills/`, `agents/`, `commands/`, `hooks/hooks.json`), not from a nested `.claude/`. So actually publishing as an installed plugin would mean relocating/copying the kit out of `.claude/` to those plugin-root locations and converting the hook wiring from `settings.json` into `hooks/hooks.json`. The manifests here reflect the documented Claude Code schema (v2.1.x) — **verify against current docs before publishing**, as plugin/marketplace schemas drift.
