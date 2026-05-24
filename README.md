# FXJEFE Local Larry — G-Force v2.1 (Clean Production Distribution)

**Author**: FXJEFE (Nikolai Warren Dreyer)  
**Current Version**: 2.1 — May 2026  
**Distribution**: Clean, production-ready, fully local Python + Ollama agent system

---

## Philosophy

Everything runs **100% locally** on your machine.

- No external skill marketplaces.
- No cloud dependencies for core operation.
- Maximum privacy, auditability, and control.
- Skills and tools are converted into high-quality, local, auditable implementations (primarily via MCP).

This is the **official clean production distribution** maintained separately from the main development folder.

---

## Quick Start

```powershell
cd C:\Users\LocalLarry\Documents\LocalLarry\GITHUB

# One-command full activation (recommended)
.\launchers\activate_larry_pipeline.ps1

# Or via management CLI
python src\manage_larry.py activate-all
```

### Manual Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python src\manage_larry.py setup
python src\manage_larry.py mcp-test
```

---

## Core Components

| Component                  | Location                          | Purpose |
|---------------------------|-----------------------------------|-------|
| Main Agent                | `src/agent_v2.py`                 | Primary interactive agent |
| Management CLI            | `src/manage_larry.py`             | Setup, validation, activation, testing |
| Model Router + Hardware   | `src/model_router.py` + `hardware_profiles.py` | Intelligent model selection + profile switching |
| MCP Client + FXJEFE Tools | `src/mcp_client.py` + `mcp/fxjefe-local-mcp/` | Local tool ecosystem |
| Session & Memory          | `src/session_manager.py` + unified context | Persistent multi-interface memory |
| Skills System             | `src/skill_manager.py`            | Registered local capabilities |
| Security Tools            | `src/kali_tools.py` + FXJEFE MCP  | Recon, scanning, hardening |
| Safe Execution            | `src/safe_code_executor.py`       | Sandboxed code running |
| Pipeline Activation       | `launchers/activate_larry_pipeline.*` | One-command full stack start |

---

## Key Architecture Highlights

- **Routing**: Task-aware model selection with hardware profile awareness (SPEED / BALANCED / ACCURACY / ULTRA_CONTEXT).
- **Memory**: Layered (session + unified SQLite context + RAG + knowledge graph).
- **Tools**: Heavy emphasis on the **FXJEFE Local MCP server** (security, PDF, browser, safe FS) + traditional MCP + Kali.
- **Safety**: Sandbox workflow for edits, explicit confirmation for risky actions, resource guards.
- **Multi-Interface**: CLI, Telegram, and Dashboard share the same persistent state.

Full technical workflow is documented in [`workflow.md`](workflow.md).

---

## Important Files

- `workflow.md` — Detailed architecture, routing, memory, tools, rules, and system prompt explanation.
- `prompts/LARRY_SYSTEM_PROMPT.md` — The actual system prompt used by the agent.
- `src/larry_config.json` — Main configuration (models, hardware, timeouts, etc.).
- `src/mcp.json` — MCP server configuration.
- `launchers/activate_larry_pipeline.ps1` — Master one-click activation script.

---

## Building the Locked / Protected Version

```powershell
python build_locked.py
```

This produces a PyInstaller + PyArmor protected executable with external `user_config.json` support.

---

## License & Attribution

Created and maintained by **FXJEFE** (Nikolai Warren Dreyer).

This is a personal production system. Use responsibly.

---

**Status**: Actively maintained clean production distribution. All major components (agent, MCP/FXJEFE tools, pipeline, memory, routing) are verified operational as of the latest session.
