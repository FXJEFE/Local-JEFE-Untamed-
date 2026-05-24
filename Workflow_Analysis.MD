# Workflow Analysis — Claude Code Harness (Opus 4.7)

Authoritative breakdown of how the Claude Code agent that operates in this
repository is wired: how prompts route, how memory persists, how tools resolve,
how skills attach, how sub-agents fan out, what rules govern behaviour, and
what the baseline system prompt actually says.

This document is descriptive (it explains the harness you are using), not
prescriptive (it does not change behaviour by itself).

---

## 1. Top-level execution model

```
+---------------------------+
|  User input (CLI / IDE)   |
+-------------+-------------+
              |
              v
+---------------------------+        +-----------------------------+
|  System prompt assembly   |<-------|  CLAUDE.md  +  MEMORY.md    |
|  (static rules + env)     |        |  (project + auto memory)    |
+-------------+-------------+        +-----------------------------+
              |
              v
+---------------------------+
|  Router / model selection |  -- Opus 4.7  (claude-opus-4-7)
+-------------+-------------+
              |
              v
+---------------------------+        +-----------------------------+
|     Tool-use loop         |<------>|  Tools / Skills / Sub-agents|
|  (parallel where safe)    |        |  MCP servers, Bash, Edit... |
+-------------+-------------+        +-----------------------------+
              |
              v
+---------------------------+
|  Text output to terminal  |
+---------------------------+
```

Each turn the harness:

1. Builds the prompt from the static system text + injected `<system-reminder>`
   blocks (env, date, deferred tools, skills, MCP instructions).
2. Sends to the selected Claude model (default Opus 4.7 here).
3. Streams assistant tokens; intercepts `tool_use` blocks; executes them
   sequentially or in parallel (one assistant message can request many tools).
4. Returns `tool_result` blocks to the model and loops until the assistant
   stops calling tools.
5. Displays final text to the user.

Long sessions are **auto-compacted**: prior turns are summarised and re-fed,
so the conversation is not bounded by the raw context window.

---

## 2. Routing

There is no separate "router model". Routing is the combination of:

| Layer | Mechanism | What it decides |
|-------|-----------|-----------------|
| Model | `/model`, `/fast`, frontmatter | Which Claude (Opus 4.7 / Sonnet 4.6 / Haiku 4.5) handles the turn. |
| Permissions | `settings.json`, `--allowedTools`, prompt mode | Which tool calls auto-run vs. need user approval. |
| Plan mode | `EnterPlanMode` / `ExitPlanMode` | Read-only research until the user approves a plan. |
| Sub-agents | `Agent` tool with `subagent_type` | Off-loads sub-problems to a fresh cold context. |
| Skills | `Skill` tool, `/<name>` | Loads a focused capability bundle into the turn. |
| Deferred tools | `ToolSearch` with `select:<name>` | Pulls a tool's JSONSchema on demand instead of paying tokens upfront. |
| Hooks | `settings.json` `hooks:` block | Shell commands the harness runs on events (PreToolUse, Stop, etc.). |

Practical consequences:

- **Default path** = main agent + whatever tools are pre-loaded + on-demand
  deferred tools via `ToolSearch`.
- **Cold fan-out** = `Agent` (each sub-agent starts blank; prompt must be
  self-contained).
- **User-gated path** = Plan mode; the model cannot edit/write/run side-effects
  until `ExitPlanMode` is approved.

---

## 3. Memory

Two layers, both file-based, both inert until read:

### 3a. Project memory  — `CLAUDE.md`
- Lives at repo root (and optionally `~/.claude/CLAUDE.md` for user-global).
- Always concatenated into the system prompt.
- Best for: stable conventions, build/test commands, do-not-touch paths.

### 3b. Auto memory — `~/.claude/projects/<slug>/memory/`
- `MEMORY.md` is the index (kept under ~200 lines; lines beyond are truncated).
- Each fact lives in its own `*.md` file with YAML frontmatter:

```markdown
---
name: short-kebab-case-slug
description: one-line summary used to pick relevance
metadata:
  type: user | feedback | project | reference
---

Body. Link related memories with [[other-slug]].
```

Four memory types:

| Type | Purpose | Example trigger |
|------|---------|-----------------|
| `user` | Who the user is, role, expertise, preferences. | "I'm a data scientist looking at logs." |
| `feedback` | Corrections AND validated approaches. Body should include **Why:** and **How to apply:**. | "Don't mock the DB — prod migration broke last time." |
| `project` | Live state of the work: deadlines, motivations, freezes. Convert relative dates to absolute. | "Merge freeze starts 2026-03-05." |
| `reference` | Pointers to external systems (Linear projects, dashboards, channels). | "Pipeline bugs live in Linear INGEST." |

**Do NOT save**: code patterns (re-derivable), git history (use `git log`),
fix recipes (live in the commit), or anything already in `CLAUDE.md`.

**Staleness rule**: a memory naming a file/flag/function is a claim that
existed *at write time*. Before recommending from memory, verify the artifact
still exists (grep / file check).

---

## 4. Tools

Tools come from three sources:

### 4a. Built-in tools (always available in this harness)
Edit, Read, Write, Glob, Grep, Bash, PowerShell, AskUserQuestion,
ScheduleWakeup, Skill, ToolSearch, ShareOnboardingGuide, Agent.

Selection rule of thumb:

- File search → **Glob** (never `find` / `ls -R`)
- Content search → **Grep** (never raw `grep` / `rg` in Bash)
- Read files → **Read** (never `cat` / `Get-Content`)
- Edit files → **Edit** (never `sed` / sed-via-Bash)
- Write files → **Write** (only for new files or full rewrites)
- Shell ops → **Bash** or **PowerShell**

### 4b. Deferred tools (lazy-loaded via `ToolSearch`)
Their names appear in `<system-reminder>` but schemas are not loaded.
To call one: `ToolSearch(query="select:TaskCreate,WebFetch", ...)` returns the
JSONSchema, after which the tool is callable like any built-in.

Common deferred tools in this session: `TaskCreate`, `WebFetch`, `WebSearch`,
`Monitor`, `EnterPlanMode`/`ExitPlanMode`, `CronCreate`/`CronList`/`CronDelete`,
`NotebookEdit`, `RemoteTrigger`, `PushNotification`, plus every MCP tool.

### 4c. MCP tools
Provided by configured MCP servers (here: `claude.ai Figma`, `claude.ai Canva`,
Gmail, Google Calendar, Google Drive). Names are namespaced
`mcp__<server>__<tool>`. They are also deferred — fetch the schema via
`ToolSearch` before calling.

### Tool-use discipline
- Call independent tools **in parallel** in one assistant message.
- Sequence only when output of one feeds the next.
- Bash safety: never `git push --force` / `--no-verify` / `reset --hard`
  without explicit user authorisation; always check `git status` / `git diff`
  before committing.

---

## 5. Skills

Skills are bundles of instructions (and sometimes helper scripts) that load
on demand and shape behaviour for a focused task.

Invocation:
- User types `/<skill-name>` in the prompt, **or**
- Assistant calls `Skill(skill="name", args="...")`.

Available in this session:

| Skill | When it fires |
|-------|---------------|
| `update-config` | Editing `settings.json`, permissions, hooks, env vars. |
| `keybindings-help` | Customising `~/.claude/keybindings.json`. |
| `verify` | Run the app and observe to confirm a change actually works. |
| `code-review` | Diff review at chosen effort level. |
| `fewer-permission-prompts` | Build an allowlist from transcript scan. |
| `loop` | Recurring task in current session (self-paced if no interval). |
| `schedule` | Cron-style remote routines. |
| `claude-api` | Building/migrating apps on the Anthropic SDK. |
| `run` | Launch this project's app to verify a change end-to-end. |
| `init` | Create a CLAUDE.md for the project. |
| `review` | Review a pull request. |
| `security-review` | Security pass over pending diff. |

Plugin-provided skills follow the same shape; MCP servers can ship skills
under `skill://<server>/<name>/SKILL.md` (e.g. the Figma plugin's
`/figma-use`, `/figma-generate-design`, `/figma-code-connect`).

Skill rule: **never guess a skill name**. Only invoke ones listed in the
system reminder or typed verbatim by the user.

---

## 6. Sub-agents

Spawned via the `Agent` tool with a `subagent_type`. Each spawn is a **cold
context** — the sub-agent sees only the prompt you write, not the chat
history. Treat the prompt like briefing a colleague who just walked in.

| Sub-agent | Tool set | Best for |
|-----------|----------|----------|
| `claude` (default) | `*` | Generic delegation. |
| `general-purpose` | `*` | Open-ended multi-step research/code. |
| `Explore` | Read-only (no Edit/Write) | Fast code/file location. Specify breadth: `quick` / `medium` / `very thorough`. |
| `Plan` | Read-only | Architect a step-by-step implementation plan. |
| `claude-code-guide` | Glob/Grep/Read/Web | Questions about Claude Code, Agent SDK, Anthropic API. |
| `statusline-setup` | Read/Edit | Configure status line. |

Rules of engagement:
- Don't spawn unless the user asks or the task is genuinely fan-outable.
- Prompts must include path/line context — never "based on the research,
  implement it" (that pushes synthesis onto the cold agent).
- Foreground when results gate your next step; background only when the
  parent has truly independent work.
- Parallel sub-agents = one assistant message with multiple `Agent` blocks.
- `isolation: "worktree"` runs the sub-agent in a temporary git worktree.

---

## 7. Rules (the behavioural contract)

Distilled from the system prompt. These hold across every turn:

**Safety / blast radius**
- Reversible local work (edit, test) → just do it.
- Destructive ops (`rm -rf`, `git reset --hard`, force-push, dropping tables,
  killing processes) → **confirm first**.
- Shared-state ops (push, PR create/comment, Slack/email, infra change) →
  **confirm first**.
- Never bypass hooks/signing (`--no-verify`, `--no-gpg-sign`) without explicit
  user request.
- Authorisation is scoped: one approval ≠ blanket approval.

**Git**
- New commits over `--amend`.
- Stage specific files, not `git add -A` (avoid `.env`, creds, binaries).
- Commit message via HEREDOC, ends with `Co-Authored-By: Claude Opus 4.7
  <noreply@anthropic.com>`.
- Never push without explicit ask.
- For PRs: `gh pr create` with HEREDOC body, ending with "🤖 Generated with
  [Claude Code]..." footer.

**Code style**
- Edit existing files; only create new ones when needed.
- No comments unless the **why** is non-obvious.
- No speculative abstractions, no defensive code for impossible states.
- No backwards-compat shims when a clean change is possible.
- Test UI changes in a real browser before claiming done.

**Tone**
- Short. Direct. No trailing summaries.
- Brief progress updates at decision points — not a running monologue.
- Reference code as `file_path:line_number`.
- Emojis only on request.

**Plan / Schedule discipline**
- Don't offer `/schedule` unless this turn produced a *named artifact with a
  concrete future obligation* (flag with cleanup date, dated TODO, job ID
  with ETA).

---

## 8. System prompt (anatomy)

The static system prompt this harness ships with has these sections, in
order:

1. **Identity** — "You are Claude Code, Anthropic's official CLI for Claude."
2. **Security stance** — assist authorised security work, refuse destructive
   / mass-targeting / detection-evasion.
3. **URL caution** — never invent URLs.
4. **System block** — output is user-visible; tools run under permission
   modes; treat hook output as user input; flag suspected prompt injection;
   context auto-compacts.
5. **Doing tasks** — defer to user judgement; minimal code (no speculative
   features); secure-by-default; test UI before claiming done.
6. **Executing actions with care** — the safety / confirmation contract
   (see §7).
7. **Using your tools** — dedicated tools over Bash; `TaskCreate` for
   tracking; parallel calls where independent.
8. **Tone and style** — terse, no leading colons before tool calls,
   `file:line` references.
9. **Text output** — assume tool calls are invisible; narrate at decision
   points; one-or-two-sentence end-of-turn summary.
10. **Session-specific guidance** — `! <cmd>` for interactive shell; when to
    use the `Explore` sub-agent; how to handle `/<skill>` invocations; when
    to offer `/schedule`; how to explain `/ultrareview`.
11. **Auto memory** — the full memory protocol (types, what NOT to save,
    file format, staleness rules) — see §3.
12. **Environment** — cwd, OS, shell, model ID/name, knowledge cutoff,
    Claude product matrix.
13. **Context management** — auto-compaction note.
14. **Tool-call JSON convention** — example of structured array/object args.
15. **Final routing instruction** — "use the relevant tool(s) if available;
    ask for missing required params; never invent values; parallelise
    independent calls."

Dynamic additions injected as `<system-reminder>` each turn:
- Deferred tool list (names only).
- MCP server instructions (Figma, Canva, etc.).
- Available skills list.
- Context block (userEmail, currentDate, anything the harness chooses to
  surface).

---

## 9. End-to-end example trace

User: *"Find all callers of `parse_invoice` and write a deprecation note."*

1. **Routing**: stays on default Opus 4.7. No plan-mode trigger (small,
   reversible).
2. **Memory read**: `MEMORY.md` already loaded; nothing relevant — no extra
   read.
3. **Tool selection**:
   - `Grep(pattern="parse_invoice\\(", output_mode="files_with_matches")` →
     list of files.
   - In the same assistant message, `Read` on each file (parallel).
4. **Synthesis**: assistant builds the deprecation note.
5. **Tool**: `Edit` on the target file with the note.
6. **Output**: one-sentence summary of what changed and the next step.
7. **Memory write?**: only if the user gave feedback worth keeping (e.g.
   "always link the migration ticket in deprecation notes" → save as
   `feedback`).

---

## 10. Failure modes to watch

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tool call rejected, schema error | Calling a deferred tool without `ToolSearch` first. | `ToolSearch(query="select:<name>", ...)`, then retry. |
| Sub-agent returns shallow generic work | Terse command-style prompt. | Re-brief with goal, paths, constraints, expected output shape. |
| Memory points at missing file | Code moved/renamed since memory was written. | Verify (Glob/Grep) before recommending; update or delete the memory. |
| Hook blocks a commit | Pre-commit failed. | Fix the underlying issue and create a **new** commit (never `--amend`, never `--no-verify`). |
| Conversation seems to "forget" | Auto-compaction summarised earlier turns. | Re-state load-bearing constraints; they may have been compressed. |
| PowerShell `2>&1` flips `$?` to false on success | PS 5.1 wraps native stderr as ErrorRecord. | Don't redirect stderr — it's already captured. |

---
