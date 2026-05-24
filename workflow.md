# Larry G-Force v2.1 — Workflow & Architecture (FXJEFE Local Larry)

**Version**: 2.1 Production (Clean GITHUB Distribution)  
**Date**: May 2026  
**Maintainer**: FXJEFE (Nikolai Warren Dreyer / Local Larry)

---

## 1. High-Level Architecture

```
User Input (CLI / Telegram / Dashboard)
          │
          ▼
┌──────────────────────────────┐
│   System Prompt Assembly     │  ← prompts/LARRY_SYSTEM_PROMPT.md + runtime context
│   + Agent Rules + Identity   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐     ┌──────────────────────────────┐
│      Model Router            │────▶│   Hardware Profile Manager   │
│   (task detection + model    │     │   (SPEED / BALANCED / ... )  │
│    selection + context size) │     └──────────────────────────────┘
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     Tool-Use / Agent Loop    │
│  (MCP Tools • FXJEFE Tools   │
│   Kali • Web • Sandbox •     │
│   Code Executor • Memory)    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│   Memory & Persistence Layer │
│  - Session Manager           │
│  - Unified Context (SQLite)  │
│  - RAG (ChromaDB + reranker) │
│  - Knowledge Graph           │
└──────────────┬───────────────┘
               │
               ▼
         Final Response + Side Effects
```

---

## 2. Input / Output

### Input Sources
- **Primary**: CLI via `agent_v2.py` (or legacy `locallarry_agent.py`)
- **Secondary**: Telegram Bot
- **Tertiary**: Dashboard (when present)
- Multi-turn conversation with full history (or compressed)

### Output
- Natural language response to user
- Tool execution results (shown or summarized)
- Side effects: file changes (via sandbox), network calls, subprocesses, memory writes, RAG indexing

**Contract**: Every response should be truthful, risk-aware, and actionable. The agent never lies or sycophantically agrees.

---

## 3. Routing

**Primary Router**: `src/model_router.py`

- Detects task type from user query:
  - `coding`, `reasoning`, `creative`, `summarize`, `vision`, `analysis`, `chat`
- Maps task → best model + recommended context size
- Respects current hardware profile (SPEED / BALANCED / ACCURACY / ULTRA_CONTEXT)
- Falls back gracefully if preferred model is not loaded

Hardware profiles control:
- `num_ctx`
- GPU layers offload
- Thread count
- Temperature

---

## 4. Memory Architecture (Multi-Layer)

1. **Session Manager** (`src/session_manager.py`)
   - Per-conversation turn history
   - Token tracking
   - Auto-summarization when approaching context limit

2. **Unified Context** (`src/unified_context_manager.py`)
   - SQLite-backed
   - Shared across CLI, Telegram, and Dashboard

3. **RAG / Vector Memory** (ChromaDB)
   - `production_rag.py` style or legacy `web_tools`
   - Documents indexed via `/index`
   - Retrieval + reranking (BAAI)

4. **Knowledge Graph** (NetworkX + file persistence)
   - Entities and relations
   - Used by legacy agent and some MCP memory tools

5. **Long-term Chunked Persistence**
   - Conversations saved in semantic chunks for later retrieval on new boot.

---

## 5. Tools

### Primary Categories
- **FXJEFE Local MCP** (`mcp/fxjefe-local-mcp/`)
  - Security scanning, prompt injection detection
  - PDF tools, safe browser automation (Playwright)
  - Safe file operations

- **Native / In-process MCP** (via `src/mcp_client.py`)
  - Filesystem, Memory, SQLite, Brave Search, Context7, Playwright, etc.

- **Kali Tools** (`src/kali_tools.py`)
  - Full security toolkit via WSL Kali when available

- **Web & Content** (`src/web_tools.py`)
  - Scraping, YouTube transcription + summarization

- **Safe Code Executor** (`src/safe_code_executor.py`)
  - Subprocess execution with syntax + static analysis

- **Sandbox Manager**
  - Stage → Edit → Test → Deploy workflow for file changes

- **GitHub / Remote** tools

**Rule**: Tools are preferred over direct model knowledge when freshness or precision is required.

---

## 6. Skills

Managed by `src/skill_manager.py`

- 15+ registered skills across categories: `code`, `context`, `file_operations`, `rag`, `sandbox`, `web`
- Skills are local, auditable Python functions.
- Philosophy: Convert useful external skills into fully local, MCP-compatible or direct-call versions.

Skills can be activated per session or globally.

---

## 7. Agent Rules (Non-Negotiable)

From the system prompt (see `prompts/LARRY_SYSTEM_PROMPT.md`):

- **Radical Honesty**: Tell the truth even when uncomfortable. Correct the user when wrong.
- **Full Device Access**: Use every capability on the host + Kali WSL.
- **Never Refuse Direct Tasks**: Only warn about risks and ask for explicit confirmation on dangerous actions.
- **Sub-Agent Inheritance**: Any spawned agent must receive the full current system prompt + rules.
- **Resource Guard**: Never push sustained system load > ~70% without warning.
- **Production Mindset**: Backups before edits, clean code, auditability.
- **Startup Ritual**: Announce identity as creation of FXJEFE every run.

---

## 8. System Prompt Location & Loading

**Primary**: `prompts/LARRY_SYSTEM_PROMPT.md`

This file is the authoritative source. It is loaded at agent startup and injected into every generation.

The prompt is **not** stored in code — it is externalized for easy auditing and editing.

---

## 9. Multi-Interface Persistence

All interfaces (CLI, Telegram, Dashboard) share the same:
- SQLite context database
- RAG store
- Knowledge graph (where applicable)

This allows seamless continuation of work across devices/interfaces.

---

**Status**: This document reflects the current operational state of the FXJEFE Local Larry v2.1 clean production distribution as of the latest work session.

Next step: We will create a matching high-quality `README.md` and then review both documents together before locking the final form.
