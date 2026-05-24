# FXJEFE Local Larry — Complete A-Z Bare-Metal Setup Guide (v2.1)

**For a true beginner on a fresh Windows machine.**

This guide follows the verified 16-point skeleton and incorporates all known gaps, recent improvements (memory handoff, embeddings system, FXJEFE MCP focus, updated system prompt), and the current clean state of the GITHUB distribution.

---

## 0. Glossary (C8)

- **RAG**: Retrieval-Augmented Generation — giving the model access to your documents via vector search.
- **MCP**: Model Context Protocol — standardized way for AI agents to call external tools.
- **FXJEFE Local MCP**: The only fully working local MCP server in this distribution (security scanning, PDF tools, safe browser automation, safe file operations).
- **Embedding**: Turning text into vectors for semantic search.
- **Reranker**: Second-stage model that improves RAG result quality (BAAI/bge-reranker-v2-m3).
- **keep_alive**: How long Ollama keeps a model loaded in VRAM after last use.
- **Hardware Profile**: SPEED / BALANCED / ACCURACY / ULTRA_CONTEXT — controls context size and GPU usage.
- **Memory Handoff**: System that lets new agent instances or different models inherit context from previous runs via `data/agent_memory_handoff/`.
- **Token Tracker**: Tracks token usage across sessions and model switches for continuity.

---

## 1. Hardware & OS Prerequisites (C1)

**Recommended Spec:**
- Windows 10/11 (64-bit)
- Python 3.11 or 3.12
- NVIDIA GPU with CUDA support (RTX 3060 6GB+ strongly recommended)
- 64GB RAM (32GB minimum)
- 150GB+ free disk space (default model alone is ~26GB)

**Critical Windows Settings:**
- Enable Long Paths (see section 2)
- Visual C++ Build Tools (for compiling some wheels)
- NVIDIA drivers + CUDA runtime (if using GPU reranker)
- Windows Defender exclusions for:
  - `%USERPROFILE%\.ollama`
  - The entire GITHUB folder (especially `chroma_db`, `data`, `larry_logs`, `sandbox`)

---

## 2. Install Core Software

1. **Python 3.11 or 3.12** from python.org (check "Add Python to PATH")
2. **Git for Windows**
3. **Ollama** from ollama.com (Windows installer)
4. **Visual C++ Redistributable** (latest x64)
5. **NVIDIA Drivers** (Game Ready or Studio) + CUDA if using GPU features

**Enable Long Paths (PowerShell as Administrator):**
```powershell
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1
```

---

## 3. Pull Models (with disk/time table, C2)

**Minimum for default profile:**

```powershell
ollama pull dolphin-mixtral:8x7b          # ~26 GB — default + CLI model
ollama pull nomic-embed-text:latest       # ~270 MB — required for RAG
```

**Recommended models:**

| Model                        | Approx Size | Purpose                  | Required?             |
|-----------------------------|-------------|--------------------------|-----------------------|
| dolphin-mixtral:8x7b        | 26 GB      | Default / CLI            | Yes                   |
| nomic-embed-text:latest     | 270 MB     | RAG embeddings           | Yes                   |
| qwen3-coder:30b             | 18 GB      | Coding                   | Recommended           |
| llama3.3:70b                | 40+ GB     | Flagship reasoning       | Optional (Tier 1)     |
| ministral-3:latest          | ~5 GB      | Fast responses           | Optional              |

**Warning**: The default profile needs significant disk space and good internet.

---

## 4. Clone repo, create venv, pip install

```powershell
cd C:\Users\LocalLarry\Documents\LocalLarry\GITHUB

python -m venv venv
venv\Scripts\activate          # ← Correct Windows command (not `source`)

pip install -r requirements.txt
pip install -r config\requirements-production.txt   # optional extras

playwright install chromium
```

**Note**: On Windows always use `venv\Scripts\activate`.

---

## 5. Create .env (template + each key explained)

```powershell
copy config\.env.example .env
notepad .env
```

**Key explanations:**
- `BRAVE_API_KEY` — Web search tool
- `GITHUB_TOKEN` — GitHub operations
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_CHAT_IDS` — Remote access via Telegram
- `HF_TOKEN` — Helps with gated models (recommended for BAAI reranker)
- `OLLAMA_HOST` — Usually `http://localhost:11434`

---

## 6. Configure larry_config.json (CPU vs GPU branch, profile choice)

Open `config\larry_config.json`

Key decisions:
- `hardware.mode`: "GPU" or "CPU"
- `ollama.timeout`: Set to 1800 (30 minutes) for long queries
- `profiles.default`: "ACCURACY" recommended for most work
- `rag.reranker_device`: "cuda:0" or "cpu" (use cpu if low VRAM)

---

## 7. Fix mcp.json (disable broken entries, add FXJEFE)

The current `config\mcp.json` has been updated to only enable the working FXJEFE Local server by default.

If you have an older version, replace it with the cleaned version that prioritizes the FXJEFE server (located at `mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py`).

---

## 8. Reserve ports / AV exclusions (C3)

**Ports to keep free:**
- 11434 — Ollama (mandatory)
- Any dashboard port (if enabled later)

**Add Windows Defender exclusions** for the entire GITHUB folder, especially:
- `chroma_db\`
- `data\`
- `larry_logs\`
- `sandbox\`

---

## 9. First run — smoke test + healthcheck (C4)

Run these in order:

```powershell
ollama list
ollama ps
curl http://127.0.0.1:11434/api/tags

nvidia-smi

python -c "import chromadb, sentence_transformers; print('Core deps OK')"

python src\smoke_test.py
python src\manage_larry.py mcp-test
```

---

## 10. Verify FXJEFE MCP responds

After starting the pipeline or the FXJEFE server manually:

```powershell
python src\manage_larry.py mcp-test
```

You should see the FXJEFE tools (security scan, PDF tools, browser automation, safe file operations).

---

## 11. Run agent (CLI / Telegram / web)

**Recommended:**

```powershell
python src\manage_larry.py activate-all
```

Or use the one-click launcher:
```
launchers\activate_larry_pipeline.ps1
```

Inside the agent try:
- `/help`
- `/mcp`
- `/fxjefe`
- `/profile`

---

## 12. First-run error table (C5)

| Symptom                                      | Cause                                           | Fix |
|---------------------------------------------|-------------------------------------------------|-----|
| ConnectionError to localhost:11434          | Ollama not running                              | `ollama serve` in another terminal |
| Model 'dolphin-mixtral:8x7b' not found      | Not pulled                                      | `ollama pull dolphin-mixtral:8x7b` |
| CUDA out of memory (reranker)               | GPU too small for LLM + reranker                | Set `rag.reranker_device: "cpu"` in config |
| ModuleNotFoundError: mcp_servers.*          | Old/broken mcp.json entries                     | Use cleaned mcp.json (only FXJEFE enabled) |
| Playwright executable missing               | Browser not installed                           | `playwright install chromium` |
| Permission errors on logs/sandbox           | Antivirus locking files                         | Add exclusions for the GITHUB folder |
| .env.example not found                      | Using old docs reference                        | Use `config\.env.example` |

---

## 13. File map of src/ (C9)

| File                              | Responsibility |
|-----------------------------------|----------------|
| `agent_v2.py`                     | Main production agent |
| `manage_larry.py`                 | Master CLI (setup, activate-all, testing) |
| `model_router.py`                 | Automatic task-based model selection + token awareness |
| `mcp_client.py`                   | MCP toolkit (FXJEFE + others) |
| `memory_handoff.py`               | Cross-model / cross-session memory sharing |
| `embeddings.py`                   | LangChain + Ollama + Chroma vector store |
| `token_manager.py`                | Token counting |
| `session_manager.py`              | Per-conversation memory + summarization |
| `kali_tools.py`                   | Security tools |
| `web_tools.py`                    | Scraping, YouTube, basic RAG |
| `safe_code_executor.py`           | Sandboxed code execution |
| `skill_manager.py`                | Local skills registry |

---

## 14. Skills overview (C6)

Skills are local Python capabilities registered via `skill_manager.py`.

They are different from MCP Tools:
- **Skills** = Direct Python functions the agent can call internally.
- **MCP Tools** = Capabilities exposed over the MCP protocol (FXJEFE server is the main production one).

Current skills are in `skills/local/`.

---

## 15. Clean reset procedure (C10)

If the system gets into a bad state:

```powershell
python src\manage_larry.py stop-services

# Nuclear reset (keeps source code)
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue chroma_db, data, larry_logs, memory.json

# Also clear any launchers runtime folders if they exist
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue launchers\chroma_db, launchers\sandbox, launchers\larry_logs

python src\manage_larry.py activate-all
```

**Note**: We use `larry_logs`.

---

## 16. Where to look next

- `workflow.md` — Full architecture, routing, memory layers, agent rules
- `README.md` — High-level project overview
- `docs/STRUCTURED_DATA_PACKAGE.md` — Complete gap analysis and roadmap
- `prompts/LARRY_SYSTEM_PROMPT.md` — The actual rules the agent follows (v2.1 final)
- `SETUP_GUIDE.md` (this file) — Beginner onboarding
- `src/manage_larry.py` — All available management commands

---

**You are now fully set up.**

Run the activation pipeline and start using the agent. The system has been significantly improved for continuity (memory handoff), clarity, and reliability.

Welcome to FXJEFE Local Larry v2.1.