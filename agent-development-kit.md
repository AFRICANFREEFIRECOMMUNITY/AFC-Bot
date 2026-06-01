# The Agent Development Kit

`CLAUDE.md + Skills + Hooks + Subagents + Plugins`

A five-layer model for configuring an AI coding agent (Claude Code). One directory, `agent-dev-kit/`. Layers are ordered 1→5 by dependency; each assumes the ones before it.

> Accuracy note: the five features are real Claude Code concepts. "Plugins = npm packages" is an analogy, not a mechanism. Taglines are mnemonics, not specs. Exact paths/schemas may drift from current docs.

## How to use this document

This is the structural blueprint for any new project from beginning to end.

**Project-setup rule:** At the start of every new project, add the entire contents of this document into the project's `CLAUDE.md` (Layer 1). It must be loaded from day one. The five-layer structure, the verification and handoff rules, and the truth and accuracy rules are all non-negotiable defaults — they are the constitution every new project inherits before any code is written.

---

## Stack overview

| Layer | Name | Role | Job |
|---|---|---|---|
| L1 | CLAUDE.md | Memory Layer | Sets the rules — naming, structure, repo expectations |
| L2 | Skills | Knowledge Layer | Provides expertise — description-matched, auto-invoked context |
| L3 | Hooks | Guardrail Layer | Enforces quality — deterministic shell scripts on agent events |
| L4 | Subagents | Delegation Layer | Delegates work — isolated context windows, results only |
| L5 | Plugins | Distribution Layer | Distributes to team — bundles L1–L4 for one-step install |

**Pipeline:** CLAUDE.md (sets rules) → Skills (provide expertise) → Hooks (enforce quality) → Subagents (delegate work) → Plugins (distribute to team)

**Directory shape:**

| Path | Contains |
|---|---|
| `CLAUDE.md/` | `architecture.rules`, `global.md`, `project.md` |
| `skills/` | `SKILL.md`, `scripts/`, `context.md` |
| `hooks/` | `PreToolUse.sh`, `PostToolUse.sh`, `SessionStart.sh` |
| `subagents/` | `code-reviewer.md`, `test-runner.md`, `explorer.md` |
| `plugins/` | `manifest.json`, `marketplace.url`, `team.install` |

---

## Layer 1 — CLAUDE.md (Memory Layer)

**A. What it is:** Always loaded. Always active. The agent's constitution — context present in every session without being asked for.

**B. Where it lives:**

| Scope | Path | Loaded for | Contents |
|---|---|---|---|
| Global | `~/.claude/CLAUDE.md` | Every project | Default voice + style; tools you always have; personal preferences |
| Project | `.claude/CLAUDE.md` | This repo only | Architecture rules; naming + repo conventions; things future-you will forget |

**C. What to put in it:**

| Entry | Purpose |
|---|---|
| `architecture.rules` | How the system fits together |
| `naming.conventions` | File names, function names, casing |
| `test.expectations` | When to write tests, what counts |
| `repo.map` | Where things live, why |

**Behavior:** Global and project files are both read at session start and merged into the agent's working context before any output.

**Tagline:** Write CLAUDE.md once. Save yourself 100 prompts later.

---

## Layer 2 — Skills (Knowledge Layer)

**A. What it is:** On-demand. Modular. Description-matched, auto-invoked context. Pulled in only when the task matches its description (unlike CLAUDE.md, which is always on).

**B. Where it lives:**

| Scope | Path | Reusable across | Contents |
|---|---|---|---|
| Global | `~/.claude/skills/` | Every project | Skills you reuse across projects; PDF, video, Excalidraw, etc.; loaded only when needed |
| Project | `.claude/skills/` | This repo | Domain knowledge for this repo; internal API patterns; project-specific workflows |

**C. What to put in a skill:**

| Item | Purpose |
|---|---|
| `SKILL.md` | The description Claude matches a task against |
| `scripts/` | Reference scripts the skill calls |
| `templates/` | Boilerplate the skill copies in |
| `assets/` | Images, fonts, configs the skill ships |

**Invocation flow:** user request ("convert this PDF") → match against skill descriptions → matching skill (e.g. `pdf-skill`) selected and activated. Candidate skills (`video-skill`, `pdf-skill`, `excalidraw-skill`) each carry a one-line description; the agent loads only the matching one.

**Tagline:** One skill. Wired forever. Future Claude knows.

---

## Layer 3 — Hooks (Guardrail Layer)

**A. What it is:** Deterministic. Not AI. Shell scripts that fire on agent events. Same input always produces the same outcome.

**B. How it triggers — two parts:**

*Matcher* — pattern matchers on tool calls. Example: `Bash(rm *)`.
- Wildcard matchers on tool name
- Regex matchers on the command
- Exact-string matchers

*Command* — plain shell; you write the rule. Example: `if [ ... ]; then exit 2; fi`.
- Block dangerous tools (`exit 2`)
- Inject context (`echo` to stdout)
- Audit log (append to a file)

**C. What hooks exist:**

| Hook | Fires |
|---|---|
| `PreToolUse.sh` | Inspect or block before any tool runs |
| `PostToolUse.sh` | Lint, log, or notify after a tool runs |
| `SessionStart.sh` | Load context when a session begins |
| `Stop.sh` | Run when Claude finishes a turn |
| `SubagentStop.sh` | Run when a subagent returns |

**Trigger sequence:** event fires → matcher checks → command runs.

**Worked example — enforce "no Claude co-author" (see Verification & handoff rule 6):**

`PreToolUse.sh`, matcher `Bash(git commit *)` and `Bash(git push *)` — blocks any commit carrying an AI co-author trailer:

```sh
# PreToolUse.sh — reject AI co-author attribution
if echo "$TOOL_INPUT" | grep -qiE 'Co-authored-by:.*(claude|anthropic|\[bot\])'; then
  echo "Blocked: AI co-author trailer not allowed in commits." >&2
  exit 2
fi
```

This makes rule 6 deterministic instead of relying on the agent to remember it — the commit cannot proceed if the trailer is present.

**Tagline:** Hooks turn vibes into rules. Git hooks, but for your agent.

---

## Layer 4 — Subagents (Delegation Layer)

**A. What it is:** Own context window. Delegates work without polluting the main session — does a job in isolation, hands back only the result.

**B. How it works — parent and child:**

| Role | What | Does |
|---|---|---|
| Parent | `main session` | Where you talk to Claude; plans the work; calls subagents like tools; stays clean, only sees results |
| Child | `subagent run` | Spawned to do one job; own system prompt + tools; own context window; returns ONE message back |

**C. What subagents exist:**

| Subagent | Job |
|---|---|
| `code-reviewer.md` | Reviews diffs against repo conventions |
| `test-runner.md` | Runs the suite and reports failures |
| `explorer.md` | Maps the codebase, returns findings |
| `feature-dev.md` | Designs and implements end-to-end |

**Delegation flow:** main session —delegate only→ subagent (code-reviewer / test-runner / explorer) —results only→ main session. The subagent's intermediate reasoning never enters the main context.

**Tagline:** Delegate the noise. Keep the main thread clean.

---

## Layer 5 — Plugins (Distribution Layer)

**A. What it is:** Bundle. Ship. Install. Packages agent capabilities for distribution. ("npm packages for agent capabilities" — analogy only.)

**B. What's in a plugin — two parts:**

*Manifest* — `plugin.json`:
```json
{ "name": "my-plugin", "version": "1.0.0", "skills": ["build", "ship"] }
```
- Declares what's inside
- Lists skills, agents, hooks, commands
- Versioned and signed

*Store* — `marketplace.url`. Listing: `my-plugin · v1.0.0 · team-ready` + Install button.
- Discoverable by the team
- One-click install per repo
- Updates push to everyone

**C. What you can ship:**

| Folder | Carries |
|---|---|
| `skills/` | Knowledge bundles ride along |
| `agents/` | Subagents ship inside the plugin |
| `hooks/` | Guardrails travel with the bundle |
| `commands/` | Slash-commands the team gets |

**Distribution flow:** bundle (`skills/`, `agent.md`, `hook.sh`, `cmd.md`) → publish (`.plugin`) → team install.

**Tagline:** Build it once. Install it everywhere. The team levels up together.

---

## Verification & handoff rules

Mandatory for any change or update before it is handed back to the user. Belongs in `CLAUDE.md` (Layer 1) as a `test.expectations` rule so it is always enforced.

1. **Test fully and exhaustively.** Do not assume a change works. Verify every feature or change actually functions correctly — cover the main path, edge cases, and failure cases — before claiming it is done.
2. **Verify from the user's perspective.** For anything with a user-facing surface, confirm the experience the user will actually have, not just that the code runs. Use **Claude in Chrome** to exercise the feature end-to-end and confirm it works fine in practice. (For non-UI changes — CLI, API, scripts — verify against the equivalent user surface instead of the browser.)
3. **For design work, compare against the approved reference.** When the change is visual/design, check it against the reference the user has explicitly approved. Take screenshots of the produced work and compare them side by side against that reference.
4. **Iterate until it matches.** If the comparison shows gaps, fix them and re-verify. Repeat the screenshot-and-compare loop until the result genuinely matches the approved reference and looks correct.
5. **Only then hand over.** Deliver to the user only after verification passes — never before. State what was tested and how it was confirmed.
6. **Never add Claude as a git co-author.** When committing or pushing, do not add Claude (or any AI tool) as a co-author. No `Co-authored-by: Claude` trailer, no AI attribution in commit messages. Commits are authored solely by the user.

---

## Truth and accuracy rules

Committed to truth and accuracy above everything else, including being helpful. A wrong answer delivered confidently is worse than no answer. Belongs in `CLAUDE.md` (Layer 1) so it is always loaded.

1. **Uncertainty.** If not fully certain about something, say so clearly. Use phrases like "I am not certain, but..." or "You may want to verify this..." Never state guesses as facts.
2. **Sources.** Do not invent paper titles, author names, URLs, or book references. If a real, verifiable source cannot be named, say "I do not have a verified source for this."
3. **Statistics.** Flag any number not 100% confident in. Say "approximately" and recommend the user verify it from a primary source.
4. **Recent events.** Remind the user when a topic may have changed since the knowledge cutoff. Do not present outdated info as current.
5. **People and quotes.** Never attribute a quote to a real person without certainty they said it. If unsure, say "I cannot confirm this quote is accurate."
6. **Code and technical.** Never invent function names, library methods, or API syntax. If unsure a function exists, tell the user to verify it in current docs.
7. **Logic gaps.** Do not fill missing context with assumptions. Do not state assumptions and proceed. If anything is unclear, stop and ask a clarifying question before answering.

---

## Best practices

Cloud-agnostic engineering defaults the agent must follow on every project. Distilled from established cloud architecture, security, and agent-coding practice. Belongs in `CLAUDE.md` (Layer 1) so it is always loaded.

### Code discipline

1. **Think before coding.** State assumptions explicitly when they exist — if assumptions can't be avoided, surface them; do not hide them. If the request has multiple interpretations, present them rather than picking silently. If something is unclear, stop and ask (see Truth rule 7).
2. **Simplicity first.** Write the minimum code that solves the problem. No speculative features, no abstractions for single-use code, no "flexibility" that wasn't requested, no error handling for impossible scenarios. If 200 lines could be 50, rewrite it.
3. **Surgical changes.** Touch only what the request requires. Do not "improve" adjacent code, comments, or formatting. Do not refactor things that aren't broken. Match existing style even when personal preference differs. Every changed line must trace directly to the user's request.
4. **Goal-driven execution.** Convert vague tasks into verifiable goals. "Add validation" becomes "write tests for invalid inputs, then make them pass." "Fix the bug" becomes "write a test that reproduces it, then make it pass." Multi-step work gets a brief plan with a verification check after each step.
5. **Clean code checklist before completion.** Functions do one thing. Names are descriptive and intention-revealing. No magic numbers or strings — use named constants. Error handling is explicit, no empty catch blocks. No commented-out code. Tests cover the change.
6. **No suppressed errors.** Never silence type errors (`as any`, `@ts-ignore`, `# type: ignore`) or swallow exceptions without handling. If suppression is genuinely needed, comment why directly above it.

### Architecture

7. **Layered boundaries.** Keep presentation, application, domain, and infrastructure separated. Dependencies point inward — domain has no external dependencies; infrastructure implements interfaces defined by inner layers. Each layer must be testable in isolation.
8. **API design.** Organize APIs around resources using nouns in URIs, not verbs. Use standard HTTP methods with correct semantics. Use plural nouns for collections. Version APIs to manage breaking changes. Return appropriate status codes and consistent error bodies. Do not expose internal database structure through the API surface.
9. **Idempotency.** Make actions idempotent so retries are safe — especially `PUT` and `DELETE`. Use `create_or_update_*`-style operations where the platform supports it.
10. **Pagination, never unbounded.** Any endpoint or tool that returns a list must support a `limit` parameter and return pagination metadata (`has_more`, `next_offset`/`next_cursor`, `total_count`). Never load all results into memory. Default to 20–50 items.
11. **Handle large or slow work asynchronously.** Long-running operations return `202 Accepted` with a status-polling mechanism, not a synchronous wait. Decouple batch and long-running tasks from the user interface using background jobs triggered by events, schedules, or message queues.
12. **Caching with invalidation.** Cache data that is read often and changes infrequently. Set TTLs that balance freshness against hit rate. Implement cache-aside with explicit invalidation aligned to data-change patterns. Guard against cache stampede.
13. **Transient fault handling.** Retry transient failures (network blips, 429, 503) with exponential backoff and jitter. Use circuit breakers to stop retrying when failures are persistent. Never retry non-transient errors (400, 401, 404). Cap retries with a maximum count and total timeout.
14. **Autoscaling sanity.** Scale on metrics that correlate with actual load. Configure scale-in as carefully as scale-out. Use cooldown periods to prevent oscillation. Set explicit min, max, and default instance counts.

### Security

15. **Least privilege by default.** Grant the narrowest permission that makes the code work — never wildcards "to make it work for now." Each component (function, service, role) gets its own identity and scoped permissions.
16. **No secrets in code, config, or environment variables.** Use a managed secrets store. Environment variables may hold *references* to secrets (e.g. a secret ARN/URI), never the secret value itself. Never commit secrets, connection strings, or keys.
17. **Use platform-managed identity in production.** When the platform provides managed identity (cloud workload identity, instance roles, service accounts), use it. Reserve developer-credential chains for local development only.
18. **Validate and sanitize every input.** Use schema validation (Pydantic, Zod, JSON Schema) at every trust boundary. Sanitize file paths against traversal. Check parameter sizes and ranges. Prevent injection in system calls and queries.
19. **Encryption at rest and in transit.** Enable encryption on every data store. Enforce TLS on every network hop. Use customer-managed keys when compliance requires it.
20. **Scan and update dependencies.** Run `npm audit` / `pip-audit` / equivalent regularly. Use Dependabot, Snyk, or equivalent. Update vulnerable dependencies promptly. Keep the dependency set minimal.
21. **Never log sensitive data.** Tokens, keys, PII, full request bodies of authenticated endpoints — these never go into logs. Errors returned to clients must not expose internal details, stack traces, or implementation hints.

### Observability

22. **Structured logging, metrics, and tracing.** Instrument every service with all three. Logs are structured (JSON), metrics are named consistently, traces propagate a correlation ID across service boundaries.
23. **Actionable alerts only.** Every alert has a clear threshold, severity, and a documented response procedure. Tune alert rules regularly — alert fatigue from false positives is itself an outage risk.
24. **Monitor leading indicators.** Detect issues before users do. Track error rate, latency percentiles (p50/p95/p99), saturation, and traffic. Establish baselines and watch for deviations.

### MCP server design (when building tools the agent calls)

25. **Tool naming.** Snake_case, action-oriented, with a service prefix: `slack_send_message`, not `send_message`. Avoid generic names that conflict with other servers.
26. **Tool descriptions must be precise.** Descriptions must narrowly and unambiguously describe what the tool does and must match the actual implementation. Vague descriptions ("manages containers") fail discoverability; specific descriptions ("List storage containers; returns names, last-modified dates, and access levels") succeed.
27. **Dual response formats.** Tools that return data support both JSON (programmatic) and Markdown (human-readable). JSON includes full metadata; Markdown converts timestamps to human-readable form and omits noise.
28. **Tool annotations.** Set `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` honestly. They are hints, not security guarantees — but they shape how clients prompt for approval.
29. **Approval gating.** Read-only, non-sensitive operations can skip approval. Destructive operations (`delete_*`, `update_*`, `create_*` on shared resources) require approval. Prefer allow-lists over deny-lists.
30. **Error returns, not exceptions.** Tool errors return inside the result object (`isError: true` with a useful message and a suggested next step), not as protocol-level failures. Never leak internal implementation details in error messages.

### Testing

31. **Test the change, not the framework.** Cover the main path, edge cases, and failure cases of what was actually changed. Don't pad with tests that exercise the standard library.
32. **Test both success and error paths.** Every error branch in production code has a corresponding test that triggers it.
33. **Mock at the service boundary.** Mock external SDK clients and network calls at the boundary, not the internals. Tests must not hit live external services.
34. **Arrange-Act-Assert.** Test bodies follow a clear three-part shape — set up state, run the code under test, assert the outcome — with one logical assertion per test.

### Git and GitHub

35. **Use the platform CLI for write operations.** Prefer `gh` (or equivalent) for PRs, issues, and releases over generic MCP `github_*` write tools — enterprise token restrictions and audit trails work better through the official CLI.
36. **Commits are atomic and message-clear.** One logical change per commit. Subject line under 72 chars, imperative mood. Body explains *why*, not *what* — the diff already shows what.
37. **No co-author attribution to Claude or any AI.** Restated from Verification rule 6 — the rule applies here too: commits are authored solely by the user.

---

## Resource discovery

This document never names specific skills, MCP servers, plugins, marketplace URLs, or external tools to use — those change constantly and depend on what is installed in the current environment. Instead, whenever the agent needs a capability, it discovers what is available and picks the best fit at runtime. Belongs in `CLAUDE.md` (Layer 1) so it is always loaded.

1. **Discover before you ask, never hardcode.** When a task needs domain knowledge, an external tool, or a specialized capability, the agent first checks what is already available in the current environment — installed skills, connected MCP servers, available subagents, plugin commands, repo-local scripts. It does not invent names, assume a tool exists, or ask the user to install something without first confirming nothing already fits.
2. **Where to look, by layer.**
    - **Skills (Layer 2):** list installed skills (`/skills` or by reading `~/.claude/skills/` and `.claude/skills/`); match the task against each skill's `SKILL.md` description; load the matching one.
    - **MCP servers:** check which servers are currently connected and what tools each exposes; pick the tool whose description matches the task.
    - **Subagents (Layer 4):** check the `subagents/` directory for a definition matching the job (`code-reviewer`, `test-runner`, `explorer`, etc.); delegate to the matching one rather than doing the work in the main session.
    - **Plugins (Layer 5):** check installed plugins for shipped skills, subagents, hooks, and slash-commands before adding anything new.
    - **Marketplaces:** if nothing local fits, check the configured plugin marketplace for a published bundle that does. Do not hardcode a marketplace URL — read it from the project or user configuration.
3. **Match by description, not by name.** Skills, MCP tools, and subagents declare what they do in their description. The agent picks based on a semantic match between the task and the description — not by guessing names. If multiple candidates match, prefer the most specific.
4. **Confirm before installing anything new.** If discovery finds nothing that fits, the agent reports what was searched, what was missing, and proposes installing something — but does not install without explicit user approval. Never auto-add a marketplace, plugin, or MCP server.
5. **Prefer the closest layer.** If a project-local skill exists, use it before a global one. If a global skill exists, use it before installing a new plugin. If a plugin already exposes a slash-command for the task, use it before writing custom code.
6. **No cached resource lists.** Each session re-checks what is available — installed skills, connected MCP servers, and active subagents can all change between sessions. The agent does not assume a previous session's environment.
7. **Surface the choice.** When the agent picks a skill, MCP tool, or subagent to use, it names which one and why in one short line ("Using `pdf-skill` because the task matches its description: read and convert PDF files"). This makes the choice auditable and lets the user override.
8. **When no match exists, say so.** If discovery finds nothing relevant, the agent says so plainly and asks how to proceed — it does not silently fall back to doing the work in the main context window or fabricating a tool name.

---

## Cross-cutting systems

Two systems sit alongside the five layers, not inside them.

**MCP Server** — connects the agent to external tools: GitHub, databases, APIs, custom integrations. Feeds capability into the stack; any layer can use an MCP-exposed tool.

**Agent Teams** — coordinates multiple agents: parallel execution, message passing, a lead agent, shared permissions. Extends L4: Subagents handle one delegated job; Agent Teams orchestrate many at once.

---

## Cross-layer reference

| Aspect | CLAUDE.md | Skills | Hooks | Subagents | Plugins |
|---|---|---|---|---|---|
| Layer role | Memory | Knowledge | Guardrail | Delegation | Distribution |
| When active | Always | On demand | On events | When delegated | Once installed |
| AI or deterministic | AI context | AI context | Deterministic | AI (isolated) | Packaging |
| Primary form | Markdown | SKILL.md + assets | Shell scripts | Agent definition `.md` | manifest + folders |
| Scope | Global / project | Global / project | Project | Project | Team-wide |
| Solves | Repeating context | Missing expertise | Inconsistent quality | Context pollution | Per-person setup drift |

**Mental model:** CLAUDE.md tells the agent the rules, Skills give it the know-how, Hooks keep it honest, Subagents let it hand off work cleanly, Plugins let the team run the same setup. Adopt in order — each layer is more useful once the one before it exists.
