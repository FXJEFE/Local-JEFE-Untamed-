# Larry G-Force v2.1 — Project Structure

This is the canonical, organized structure for the Larry G-Force agent system.

## Root
- `agent_v2.py`              → Main agent entry point (imports from core/)
- `manage_larry.py`          → Primary management CLI
- `activate_larry.py`        → Interactive cross-platform activation pipeline
- `setup_larry.py`           → Legacy one-time setup (being phased into manage_larry)
- `smoke_test.py`            → Tool & MCP verification

## Framework Directories

### config/
All configuration files (no secrets in code).
- `larry_config.json`
- `mcp.json`
- `.env.example`
- `user_config.json` (for compiled builds / multiple machines)

### prompts/
System prompts and skill definitions.
- `LARRY_SYSTEM_PROMPT.md`
- `welcome_advisory.txt`

### skills/
Local MCP skills (Python + Ollama executable variants).
- Converted original skills + new high-quality tools.

### mcp/
MCP client + servers.
- `mcp_client.py`
- `mcp_servers/`
- `gforce-mcp-suite/` (rebranded powerful local tools)

### core/
Core agent logic and managers.
- `agent_v2.py` (symlink or thin launcher in root)
- All major managers and tool files.

### tools/
Security, web, and utility tools.
- `kali_tools.py`
- `web_tools.py`
- etc.

### api/
API layer (for dashboard, external access, etc.).

### db/
Databases.
- `unified_context.db`
- Other SQLite files.

### logs/
All logging (activity stream, agent logs, etc.).

### data/
RAG, user data, exports, sandbox, etc.

### scripts/
Helper and management scripts.
- `install_kali_tools.sh`
- etc.

## Philosophy
- Everything is local-first and security-hardened.
- Config is always external (especially for compiled/locked builds).
- No hard-coded personal information.
- Skills are converted to high-quality local Python + Ollama MCP servers (better than community alternatives).

## GITHUB/
Clean, distributable snapshot (source + locked build tools).
