#!/usr/bin/env python3
"""
Local Larry v2 — G-FORCE Enhanced Agent
- Multi-model support with task-based routing
- Context limits per model
- File browsing and editing
- Persistent ChromaDB RAG
- Hardware profiles (SPEED / ACCURACY / ULTRA_CONTEXT)
- Sandbox safe-edit workflow
- Voice, MCP tools, web scraping
- Autonomous agentic mode
- 100% localhost (no external APIs)
"""

# =============================================================================
# ROBUST BOOTSTRAP FOR CLEAN DISTRIBUTION (GITHUB/src layout)
# Ensures that when running `python .../GITHUB/src/agent_v2.py` from anywhere,
# all sibling modules (file_browser, kali_tools, etc.) are importable.
# =============================================================================
from activity_stream import ActivityStream
from kali_tools import TOOLS, list_tools, tool_help, run_tool, parse_args_with_preset
from file_browser import FileBrowser, get_browser
from model_router import ModelRouter, TaskType, list_models, get_router, MODEL_CONFIGS
import uuid
import shutil
import tempfile
import logging
import json
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import difflib
import hashlib
import platform
import re
import sys as _sys  # avoid shadowing the one we just used for path manipulation
import os
import asyncio
import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_THIS_DIR = _THIS_FILE.parent

# 1. Always put the directory containing this script first in sys.path
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# 2. Also support the common "GITHUB root" layout where configs live one level up
_GITHUB_ROOT = _THIS_DIR.parent
if _GITHUB_ROOT.exists() and str(_GITHUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_GITHUB_ROOT))

# 3. Support running with config/ sibling directory
_CONFIG_DIR = _GITHUB_ROOT / "config"
if _CONFIG_DIR.exists() and str(_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(_CONFIG_DIR))
# =============================================================================


# pandas is optional — only required for /csv-edit
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False

# Fix Windows console encoding for Unicode/emoji support
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

try:
    import readline
except ModuleNotFoundError:
    try:
        import pyreadline3 as readline
    except ModuleNotFoundError:
        readline = None

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text
    from rich.theme import Theme
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    Console = Panel = Prompt = Text = Theme = box = None
    RICH_AVAILABLE = False

# Import our core modules

# Skill Manager
try:
    from skill_manager import get_skill_manager
    SKILL_MANAGER_AVAILABLE = True
except ImportError:
    get_skill_manager = None
    SKILL_MANAGER_AVAILABLE = False

# Context Manager
try:
    from context_manager import ContextManager, ModelTaskManager, get_context_manager, get_task_manager
    CONTEXT_MANAGER_AVAILABLE = True
except ImportError:
    ContextManager = ModelTaskManager = get_context_manager = get_task_manager = None
    CONTEXT_MANAGER_AVAILABLE = False

# Web Tools
try:
    from web_tools import (
        WebScraper, YouTubeSummarizer, FinanceScraper,
        get_web_scraper, get_youtube_summarizer, get_finance_scraper,
    )
    WEB_TOOLS_AVAILABLE = True
except ImportError:
    WebScraper = YouTubeSummarizer = FinanceScraper = None
    get_web_scraper = get_youtube_summarizer = get_finance_scraper = None
    WEB_TOOLS_AVAILABLE = False

# Voice Module
try:
    from voice_module import VoiceManager, get_voice_manager
    VOICE_AVAILABLE = True
except ImportError:
    VoiceManager = get_voice_manager = None
    VOICE_AVAILABLE = False

# MCP Tools
try:
    from mcp_client import MCPToolkit, get_mcp_toolkit
    MCP_AVAILABLE = True
except ImportError:
    MCPToolkit = get_mcp_toolkit = None
    MCP_AVAILABLE = False

# Safe Code Executor
try:
    from safe_code_executor import get_executor, DebugHelper
    CODE_EXECUTOR_AVAILABLE = True
except ImportError:
    get_executor = DebugHelper = None
    CODE_EXECUTOR_AVAILABLE = False

# Universal File Handler
try:
    from universal_file_handler import get_file_handler
    FILE_HANDLER_AVAILABLE = True
except ImportError:
    get_file_handler = None
    FILE_HANDLER_AVAILABLE = False

# Hardware Profile Manager
try:
    from hardware_profiles import ProfileManager, get_profile_manager, HardwareProfile
    PROFILE_MANAGER_AVAILABLE = True
except ImportError:
    ProfileManager = get_profile_manager = HardwareProfile = None
    PROFILE_MANAGER_AVAILABLE = False

# Token Manager
try:
    from token_manager import TokenManager
    TOKEN_MANAGER_AVAILABLE = True
except ImportError:
    TokenManager = None
    TOKEN_MANAGER_AVAILABLE = False

# Unified Context Manager
try:
    from unified_context_manager import UnifiedContextManager
    UNIFIED_CONTEXT_AVAILABLE = True
except ImportError:
    UnifiedContextManager = None
    UNIFIED_CONTEXT_AVAILABLE = False

# Cross-Platform Paths
try:
    from cross_platform_paths import CrossPlatformPathManager
    CROSS_PLATFORM_PATHS_AVAILABLE = True
except ImportError:
    CrossPlatformPathManager = None
    CROSS_PLATFORM_PATHS_AVAILABLE = False

# Sandbox Manager
try:
    from sandbox_manager import SandboxManager, get_sandbox_manager
    SANDBOX_MANAGER_AVAILABLE = True
except ImportError:
    SandboxManager = get_sandbox_manager = None
    SANDBOX_MANAGER_AVAILABLE = False

# Legacy RAG Integration
try:
    from rag_integration import get_rag_manager, RAGManager
    RAG_LEGACY_AVAILABLE = True
except ImportError:
    get_rag_manager = RAGManager = None
    RAG_LEGACY_AVAILABLE = False

# Security Command Center
try:
    from security_command_center import SecurityCommandCenter
    _security_center = SecurityCommandCenter()
    SECURITY_AVAILABLE = True
except ImportError:
    _security_center = None
    SECURITY_AVAILABLE = False

# Bash Script Runner
try:
    from bash_script_runner import BashScriptRunner
    _bash_runner = BashScriptRunner()
    BASH_AVAILABLE = True
except ImportError:
    _bash_runner = None
    BASH_AVAILABLE = False

# Production RAG (preferred over legacy)
try:
    from production_rag import ProductionRAG, get_rag
    PRODUCTION_RAG_AVAILABLE = True
except ImportError:
    ProductionRAG = get_rag = None
    PRODUCTION_RAG_AVAILABLE = False

# Tool-calling loop (Robin) — pipelines, background jobs, scheduled health checks
try:
    from agent_tools import chat as robin_chat, get_scheduler as robin_get_scheduler
    AGENT_TOOLS_AVAILABLE = True
except ImportError as _e:
    robin_chat = robin_get_scheduler = None
    AGENT_TOOLS_AVAILABLE = False

# Portable path resolution — honors $LARRY_HOME and anchors to this file's location
# so the project runs from any location (local install, USB stick, network share,
# Linux, or Windows).
try:
    from larry_paths import BASE_DIR, DATA_DIR, LOG_DIR
except ImportError:
    BASE_DIR = Path(__file__).parent.resolve()
    DATA_DIR = BASE_DIR / "data"
    LOG_DIR = BASE_DIR / "logs"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

MEMORY_FILE = DATA_DIR / "rag_memory.json"
HISTORY_FILE = DATA_DIR / "conversation_history.json"
LOG_FILE = LOG_DIR / "agent_log.txt"

# Load larry_config.json if available
LARRY_CONFIG = {}
config_path = BASE_DIR / "larry_config.json"
if config_path.exists():
    try:
        with open(config_path, "r") as f:
            LARRY_CONFIG = json.load(f)
    except Exception:
        pass

# Setup logging
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# G-FORCE HARDWARE PROFILES
HW_PROFILES = {
    "SPEED": {
        "num_gpu": 0,         # CPU-only (VRAM free)
        "num_ctx": 16384,
        "temperature": 0.7,
    },
    "ACCURACY": {
        "num_gpu": 0,         # CPU-only (VRAM free)
        "num_ctx": 65536,
        "temperature": 0.3,
    },
    "ULTRA_CONTEXT": {
        "num_gpu": 0,         # CPU-only — 64GB DDR5 handles it
        "num_ctx": 131072,
        "num_thread": 16,
    },
}


class ConversationStore:
    """Persistent conversation history."""

    def __init__(self, history_file: Path = HISTORY_FILE):
        self.history: List[Dict] = []
        self.history_file = history_file
        self.max_history = 100
        self.load_history()

    def load_history(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r") as f:
                    self.history = json.load(f)
                logger.info(f"Loaded {len(self.history)} history entries")
            except Exception as e:
                logger.error(f"Error loading history: {e}")
                self.history = []

    def save_history(self):
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history[-self.max_history:], f, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {e}")

    def add(self, role: str, content: str):
        self.history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.save_history()

    def get_context(self, n: int = 20, max_chars_per_msg: int = 2000) -> str:
        recent = self.history[-n:]
        parts = []
        for i, m in enumerate(recent):
            role = "User" if m['role'] == 'user' else "Assistant"
            content = m['content']
            # Never truncate the last user message — it's the current query context
            if i < len(recent) - 1 and len(content) > max_chars_per_msg:
                content = content[:max_chars_per_msg] + "\n... [truncated]"
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def clear(self):
        self.history = []
        self.save_history()


class EnhancedAgent:
    """Multi-model agent with file browsing, subagents, speech, sandbox, and RAG."""

    def __init__(self, working_dir: str = None):
        # Initialize components
        self.working_dir = os.path.abspath(
            working_dir or LARRY_CONFIG.get("working_directory") or str(BASE_DIR))
        self.router = get_router()
        self.browser = get_browser([self.working_dir])
        self.conversation = ConversationStore()
        self.current_profile = LARRY_CONFIG.get("default_profile", "SPEED")
        self.agent_name = LARRY_CONFIG.get("agent_name", "LARRY G-FORCE")

        # Context Manager (auto-summarization)
        if CONTEXT_MANAGER_AVAILABLE:
            self.context_mgr = get_context_manager(self.router)
            self.task_mgr = get_task_manager(self.router)
        else:
            self.context_mgr = None
            self.task_mgr = None

        # Production RAG (preferred)
        self.rag = None
        if PRODUCTION_RAG_AVAILABLE:
            try:
                self.rag = get_rag(
                    chroma_path=os.path.join(self.working_dir, "chroma_db"),
                    use_reranker=True
                )
                logger.info(
                    f"Production RAG initialized. Stats: {self.rag.get_stats()}")
            except Exception as e:
                logger.warning(f"Production RAG init failed: {e}")

        # Legacy RAG Manager (fallback)
        self.rag_manager = None
        if RAG_LEGACY_AVAILABLE:
            try:
                self.rag_manager = get_rag_manager()
            except Exception as e:
                logger.warning(f"Legacy RAG Manager init failed: {e}")

        # Universal File Handler
        self.file_handler = None
        if FILE_HANDLER_AVAILABLE:
            self.file_handler = get_file_handler(base_dir=self.working_dir)

        # Safe Code Executor
        self.executor = None
        if CODE_EXECUTOR_AVAILABLE:
            try:
                self.executor = get_executor(timeout=45)
            except Exception as e:
                logger.warning(f"Safe Code Executor init failed: {e}")

        # Web Tools
        if WEB_TOOLS_AVAILABLE:
            self.web_scraper = get_web_scraper(
                os.path.join(self.working_dir, "exports"))
            self.youtube = get_youtube_summarizer(
                os.path.join(self.working_dir, "exports"),
                chroma_db_path=os.path.join(self.working_dir, "chroma_db")
            )
            self.finance = get_finance_scraper()
        else:
            self.web_scraper = None
            self.youtube = None
            self.finance = None

        # MCP Tools (GitHub, Brave Search, Memory)
        if MCP_AVAILABLE:
            self.mcp = get_mcp_toolkit(
                os.path.join(self.working_dir, "mcp.json"))
        else:
            self.mcp = None

        # Voice Manager
        self.voice_manager = None
        if VOICE_AVAILABLE:
            try:
                self.voice_manager = get_voice_manager()
            except Exception as e:
                logger.warning(f"Voice Manager init failed: {e}")

        # Current model override (None = auto-route)
        self.forced_model: Optional[str] = None

        # Skill Manager
        self.skill_manager = get_skill_manager() if SKILL_MANAGER_AVAILABLE else None

        # Hardware Profile Manager
        self.profile_manager = None
        if PROFILE_MANAGER_AVAILABLE:
            try:
                self.profile_manager = get_profile_manager(
                    db_path=os.path.join(
                        self.working_dir, "data", "unified_context.db")
                )
            except Exception as e:
                logger.warning(f"Profile Manager init failed: {e}")

        # Token Manager
        self.token_manager = None
        if TOKEN_MANAGER_AVAILABLE:
            try:
                self.token_manager = TokenManager()
            except Exception as e:
                logger.warning(f"Token Manager init failed: {e}")

        # Unified Context Manager
        self.unified_context = None
        if UNIFIED_CONTEXT_AVAILABLE:
            try:
                self.unified_context = UnifiedContextManager(
                    db_path=os.path.join(
                        self.working_dir, "data", "unified_context.db"),
                    context_limit=65536,
                    summarization_threshold=0.75
                )
            except Exception as e:
                logger.warning(f"Unified Context Manager init failed: {e}")

        # Cross-Platform Path Manager
        self.path_manager = None
        if CROSS_PLATFORM_PATHS_AVAILABLE:
            try:
                self.path_manager = CrossPlatformPathManager(self.working_dir)
            except Exception as e:
                logger.warning(f"Cross-Platform Path Manager init failed: {e}")

        # Sandbox Manager
        self.sandbox = None
        if SANDBOX_MANAGER_AVAILABLE:
            try:
                self.sandbox = get_sandbox_manager(
                    db_path=os.path.join(
                        self.working_dir, "data", "unified_context.db"),
                    sandbox_root=os.path.join(self.working_dir, "sandbox")
                )
            except Exception as e:
                logger.warning(f"Sandbox Manager init failed: {e}")

        # System prompt
        self.system_prompt = f"""You are {self.agent_name}.
Hardware: CPU-only inference | 64GB DDR5 | GPU VRAM free.
Mode: Hybrid Performance.
Goal: Execute tasks with maximum efficiency using local resources.

Capabilities:
1. FILE OPS: Browse, edit, and refactor with surgical precision.
2. RAG INTEL: Retrieve critical data from your knowledge base.
3. SMART ROUTING: Deploy specialized models for specialized tasks.
4. PERSISTENCE: Maintain mission context across sessions.
5. SECURITY: Network scanning, port investigation, threat hunting.

Operational Protocols:
- Be proactive, efficient, and motivational.
- When editing: VERIFY, BACKUP, EXECUTE.
- Security tools available via /kali, /nmap, /security, etc.
- Do NOT simulate tool output — real results provided automatically.
Keep responses concise and actionable."""

        # Activity stream for dashboard
        self.activity = ActivityStream("agent_v2")
        self.activity.emit(ActivityStream.SYSTEM, "Agent v2 initialized")

        # Subagent registry
        self.subagents = {}
        self.register_subagents()

        # Speech integration
        self.speech_enabled = VOICE_AVAILABLE

        # Index codebase at startup if empty
        self._index_at_startup()

        # Robin tool-calling loop state (separate from RAG/chat history to avoid bleed)
        self.tool_history: List[Dict[str, Any]] = []
        self.tool_task_id: Optional[str] = None
        if AGENT_TOOLS_AVAILABLE:
            try:
                robin_get_scheduler()  # eagerly start + rehydrate scheduled jobs
            except Exception as e:
                logger.warning(f"Robin scheduler init failed: {e}")

        logger.info("EnhancedAgent initialized (G-FORCE)")

    def register_subagents(self):
        """Register subagents for specialized tasks."""
        self.subagents['python_debugger'] = self._python_debugger_subagent

    def _python_debugger_subagent(self, script_path: str) -> str:
        """Debug a Python script using SafeCodeExecutor."""
        if not self.executor:
            return "Code Executor not available for debugging."
        try:
            path = Path(script_path)
            if not path.exists():
                return f"Script not found: {script_path}"
            code = path.read_text(encoding="utf-8", errors="ignore")
            result = self.executor.execute(code)
            output = f"Exit code: {result.get('exit_code', '?')}\n"
            if result.get('stdout'):
                output += f"Output:\n{result['stdout'][:2000]}\n"
            if result.get('stderr'):
                output += f"Errors:\n{result['stderr'][:2000]}\n"
            if DebugHelper and result.get('stderr'):
                suggestions = DebugHelper.analyze_error(result['stderr'], code)
                if suggestions:
                    output += f"\nDebug suggestions:\n" + \
                        "\n".join(f"  - {s}" for s in suggestions)
            return output
        except Exception as e:
            return f"Debug failed: {e}"

    def safe_read_file(self, rel_path: str) -> Tuple[str, bool]:
        """Read file with path traversal protection."""
        if self.path_manager:
            safe = self.path_manager.resolve(rel_path)
            if safe is None:
                return "Path outside allowed directory.", False
            return self.browser.read_full(str(safe))
        return self.browser.read_full(rel_path)

    # ── Safe Code Execution ────────────────────────────────────────────
    def run_snippet(self, code: str) -> dict:
        """Execute a code snippet safely using SafeCodeExecutor."""
        if not self.executor:
            return {'status': 'failed', 'error': 'Safe Code Executor not available'}
        result = self.executor.execute(code)
        if result.get('success'):
            return {
                'status': 'ok',
                'output': result.get('stdout', '').strip(),
                'stderr': result.get('stderr', '').strip()
            }
        analysis = {}
        if DebugHelper and result.get('stderr'):
            analysis = DebugHelper.analyze_error(
                Exception(result.get('stderr', 'Unknown error'))
            )
        return {
            'status': 'failed',
            'error': result.get('stderr', result.get('error', 'Execution failed')),
            'suggestion': analysis.get('suggestion', '')
        }

    # ── Universal File Handler / RAG Q&A ──────────────────────────────
    def read_file(self, rel_path: str) -> str:
        """Read a file via UniversalFileHandler with format-aware output."""
        if not self.file_handler:
            # Fallback to plain browser read
            content, ok = self.browser.read_full(rel_path)
            return content if ok else f"Error reading {rel_path}: {content}"

        result = self.file_handler.read_file(rel_path)
        if not result.get('success', False):
            return f"Error reading {rel_path}: {result.get('error', 'unknown')}"

        content_type = result.get('type', 'unknown')

        if content_type == 'code':
            summary = (
                f"Language: {result.get('language')}\n"
                f"Lines: {result.get('lines')} (code: {result.get('code_lines')}, "
                f"comments: {result.get('comment_lines')}, blank: {result.get('blank_lines')})"
            )
            content = result.get('content', '') or ''
            return f"{summary}\n\n{content_type.capitalize()} content:\n{content[:4000]}"

        elif content_type in ('json', 'yaml', 'toml'):
            return result.get('formatted', result.get('content', ''))

        elif content_type in ('csv', 'tsv'):
            return (
                f"Shape: {result.get('shape')}\n"
                f"Columns: {result.get('columns')}\n"
                f"First 5 rows:\n{result.get('head', [])[:5]}"
            )

        else:
            content = result.get('content', '') or ''
            return content[:3000] + "..." if len(content) > 3000 else content

    def ask_about_code(self, question: str, max_context_tokens: int = 3800) -> str:
        """Ask a question about the indexed codebase using RAG context."""
        if not self.rag:
            return "❌ Production RAG not available."

        try:
            context = self.rag.get_context_for_query(
                question, max_tokens=max_context_tokens)
        except Exception as e:
            return f"❌ RAG query failed: {e}"

        if not context.strip():
            return "No relevant code or documentation found in the index."

        full_prompt = f"""Relevant code/documentation excerpts:
{context}

User question: {question}

Answer concisely and technically, citing file names and line numbers when possible:"""

        # Route through the model and return the answer (not just the prepared prompt)
        try:
            model = self.get_model_for_query(question)
            options = self._get_hw_options(question)
            return self.router.generate(full_prompt, model=model, options=options)
        except Exception as e:
            approx_tokens = len(full_prompt) // 4
            return (
                f"[RAG context prepared — {approx_tokens} tokens, model call failed: {e}]\n\n"
                f"{context[:2000]}..."
            )

    def get_relevant_context(self, query: str, max_chars: int = 12000) -> str:
        """Conservative RAG context budgeting."""
        if not self.rag:
            return ""
        try:
            raw = self.rag.get_context_for_query(query, max_tokens=3800)
        except Exception:
            return ""
        if len(raw) > max_chars:
            return raw[:max_chars - 200] + "\n\n[... context truncated ...]"
        return raw

    def chat(self, text: str) -> str:
        """Synchronous wrapper for process_query."""
        return asyncio.run(self.process_query(text))

    # ── Robin tool-calling loop ───────────────────────────────────────
    def process_tool_query(self, query: str, new_task: bool = False) -> str:
        """Run a query through the Robin tool-calling loop (agent_tools.chat).

        This bypasses the RAG/chat path and gives the model real tools:
        run_script, start_background, schedule_interval, health_check, etc.
        Used for operational requests like 'start the pipeline' or
        'schedule a health check every 60 seconds'.
        """
        if not AGENT_TOOLS_AVAILABLE:
            return ("Robin tool-calling loop is unavailable. "
                    "Install: pip install apscheduler  (in the agent venv)")
        if new_task or not self.tool_task_id:
            self.tool_history = []
            self.tool_task_id = uuid.uuid4().hex[:8]
        try:
            reply, self.tool_history = robin_chat(query, self.tool_history)
        except Exception as e:
            logger.error(f"Robin chat failed: {e}")
            return f"Robin tool-calling loop error: {e}"
        # Rolling window so context doesn't grow forever
        self.tool_history = self.tool_history[-20:]
        return reply

    # ── Sandbox Methods ───────────────────────────────────────────────
    def sandbox_stage_file(self, file_path: str) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.stage(file_path)

    def sandbox_edit_file(self, file_path: str, content: str) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.edit(file_path, content)

    def sandbox_test_changes(self, file_path: str) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.test(file_path)

    def sandbox_deploy(self, file_path: str, create_backup: bool = True) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.deploy(file_path, create_backup=create_backup)

    def sandbox_rollback(self, file_path: str) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.rollback(file_path)

    def get_sandbox_status(self, session_id: str = None) -> str:
        if not self.sandbox:
            return "Sandbox Manager not available."
        return self.sandbox.status(session_id)

    # ── Index at startup ──────────────────────────────────────────────
    def _index_at_startup(self, extensions=None, max_files=200):
        """Auto-index codebase for RAG if KB is empty."""
        if not self.rag:
            return
        try:
            stats = self.rag.get_stats()
            if stats.get("status") == "unavailable":
                logger.info(
                    "RAG unavailable (no ChromaDB) — skipping startup index")
                return
            kb_count = stats.get("collections", {}).get("knowledge_base", 0)
            if kb_count == 0:
                logger.info("RAG KB empty — indexing codebase at startup...")
                self.rag.index_directory(self.working_dir, max_files=max_files)
            else:
                logger.info(f"RAG KB has {kb_count} docs — skipping re-index")
        except Exception as e:
            logger.warning(f"Startup indexing failed: {e}")

    # ── Hardware profiles ─────────────────────────────────────────────
    def _get_hw_options(self, query: str, task_type=None) -> dict:
        """Get hardware options based on current profile."""
        if self.profile_manager:
            try:
                profile = self.profile_manager.get_current_profile()
                return profile.to_ollama_options() if hasattr(profile, 'to_ollama_options') else {}
            except Exception:
                pass
        return HW_PROFILES.get(self.current_profile, HW_PROFILES["SPEED"])

    def count_tokens(self, text: str) -> int:
        """Count tokens using TokenManager or approximation."""
        if self.token_manager:
            return self.token_manager.count(text)
        return len(text) // 4

    def get_profile_info(self) -> str:
        """Return current profile with available options."""
        if self.profile_manager:
            try:
                name = self.profile_manager.get_current_profile_name()
                profiles = self.profile_manager.list_profiles()
                return f"Current: {name}\nAvailable: {', '.join(profiles)}"
            except Exception:
                pass
        return f"Current: {self.current_profile}\nAvailable: {', '.join(HW_PROFILES.keys())}"

    def set_profile(self, profile_name: str) -> str:
        """Switch hardware profile."""
        up = profile_name.upper()
        if self.profile_manager:
            try:
                self.profile_manager.set_profile(up)
                self.current_profile = up
                return f"Profile switched to {up}"
            except Exception as e:
                return f"Profile switch failed: {e}"
        if up in HW_PROFILES:
            self.current_profile = up
            return f"Profile switched to {up}"
        return f"Unknown profile: {up}. Available: {', '.join(HW_PROFILES.keys())}"

    # ── Web commands ──────────────────────────────────────────────────
    def execute_web_command(self, cmd: str, args: List[str]) -> str:
        """Execute web scraping / search / finance commands."""
        if cmd in ("web", "scrape"):
            if not args:
                return "Usage: /web <url>  |  /web summarize <url>"
            if not self.web_scraper:
                return "Web Tools not available. Install: pip install beautifulsoup4 html2text"
            # /web summarize <url>
            if args[0].lower() == "summarize" and len(args) > 1:
                return self.web_scraper.summarize_url(args[1])
            url = args[0]
            result = self.web_scraper.scrape(url)
            if result and self.rag:
                try:
                    doc_id = f"web_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                    self.rag.kb_collection.add(
                        documents=[result[:8000]], ids=[doc_id],
                        metadatas=[
                            {"source": url, "indexed_at": datetime.now().isoformat()}]
                    )
                except Exception:
                    pass
            return result[:4000] if result else "Failed to scrape URL."

        elif cmd == "search_web":
            if not args:
                return "Usage: /search_web <query>"
            if not self.mcp:
                return "MCP/Brave Search not available."
            query = " ".join(args)
            try:
                results = self.mcp.brave_search(query, count=10)
                return results[:4000] if results else "No results."
            except Exception as e:
                return f"Search failed: {e}"

        elif cmd == "youtube":
            if not args:
                return "Usage: /youtube <url> [summarize]"
            if not self.youtube:
                return "YouTube tools not available. Install: pip install youtube-transcript-api"
            url = args[0]
            summarize = len(args) > 1 and args[1].lower() == "summarize"
            try:
                if summarize:
                    return self.youtube.summarize(url)[:4000]
                else:
                    transcript, success = self.youtube.get_transcript(
                        self.youtube.extract_video_id(url) or url
                    )
                    return transcript[:4000] if success else transcript
            except Exception as e:
                return f"YouTube failed: {e}"

        elif cmd == "sentiment":
            if not self.finance:
                return "Finance tools not available."
            topic = " ".join(args) if args else "market"
            sources = ["headlines", "x"]
            # Allow explicit source list: /sentiment XAUUSD headlines forexfactory
            if len(args) > 1:
                topic = args[0]
                sources = args[1:]
            return self.finance.get_sentiment(topic, sources)

        elif cmd == "prices":
            if not self.finance:
                return "Finance tools not available."
            if not args:
                return "Usage: /prices <symbol,...> [crypto|forex]"
            symbols = [s.strip() for s in args[0].split(",")]
            asset_type = args[1].lower() if len(args) > 1 else "crypto"
            data = self.finance.get_prices(symbols, asset_type)
            lines = []
            for k, v in data.items():
                if isinstance(v, dict):
                    price = v.get("price_usd", "?")
                    chg = v.get("change_24h")
                    chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
                    lines.append(f"  {k}: ${price}{chg_str}")
                else:
                    lines.append(f"  {k}: {v}")
            return "\n".join(lines) if lines else "No price data."

        elif cmd == "headlines":
            if not self.finance:
                return "Finance tools not available."
            source = args[0] if args else "reuters"
            return self.finance.scrape_headlines(source)

        elif cmd == "forexfactory":
            if not self.finance:
                return "Finance tools not available."
            return self.finance.scrape_forexfactory()

        return f"Unknown web command: {cmd}"

    # ── Agentic mode ──────────────────────────────────────────────────
    def _get_tools_description(self) -> str:
        """JSON tool list for agentic mode."""
        tools = [
            {"name": "ls", "description": "List directory",
                "parameters": {"path": "string"}},
            {"name": "read_file", "description": "Read file content",
                "parameters": {"path": "string"}},
            {"name": "write_file", "description": "Write to file",
                "parameters": {"path": "string", "content": "string"}},
            {"name": "edit_file", "description": "Edit lines", "parameters": {
                "path": "string", "start": "int", "end": "int", "content": "string"}},
            {"name": "run_command", "description": "Execute shell command",
                "parameters": {"command": "string"}},
            {"name": "run_snippet", "description": "Execute Python code snippet safely",
                "parameters": {"code": "string"}},
            {"name": "search", "description": "Search knowledge base",
                "parameters": {"query": "string"}},
        ]
        return json.dumps(tools, indent=2)

    def _execute_agent_action(self, action_json: str) -> str:
        """Parse & execute a tool call from agentic mode."""
        try:
            # Strip markdown code fences if present
            action_json = re.sub(r'^```(?:json)?\s*', '', action_json.strip())
            action_json = re.sub(r'\s*```$', '', action_json.strip())
            action = json.loads(action_json)
            name = action.get("name", "")
            params = action.get("parameters", {})

            if name == "ls":
                return self.browser.ls(params.get("path", "."))
            elif name == "read_file":
                content, ok = self.browser.read_full(params.get("path", ""))
                return content if ok else f"Error: {content}"
            elif name == "write_file":
                return self.browser.write(params.get("path"), params.get("content"), create_backup=True)
            elif name == "edit_file":
                return self.browser.edit_lines(params["path"], params["start"], params["end"], params["content"], create_backup=True)
            elif name == "run_command":
                cmd = params.get("command", "")
                r = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=60)
                return (r.stdout + r.stderr)[:2000]
            elif name == "run_snippet":
                result = self.run_snippet(params.get("code", ""))
                if result['status'] == 'ok':
                    output = result.get('output', '')
                    stderr = result.get('stderr', '')
                    return f"Output:\n{output}" + (f"\nStderr:\n{stderr}" if stderr else "")
                return f"Error: {result.get('error', 'Failed')}" + (f"\nSuggestion: {result['suggestion']}" if result.get('suggestion') else "")
            elif name == "search":
                if self.rag:
                    hits = self.rag.hybrid_search(
                        params.get("query", ""), k=5, final_k=3)
                    return "\n---\n".join(h['content'][:500] for h in hits)
                return "RAG not available."
            else:
                # Try MCP tool
                if self.mcp:
                    try:
                        return str(self.mcp.call_tool(name, params))[:2000]
                    except Exception:
                        pass
                return f"Unknown tool: {name}"
        except json.JSONDecodeError:
            return f"Invalid JSON: {action_json[:200]}"
        except Exception as e:
            return f"Action error: {e}"

    async def process_query_agentic(self, query: str, max_steps: int = 8, feedback_cb=None) -> str:
        """Autonomous ReAct loop: Thought -> Action -> Observation -> Final Answer."""
        tools_desc = self._get_tools_description()
        system = (
            f"{self.system_prompt}\n\n"
            "You have access to tools. Use them step by step.\n"
            f"Available tools:\n{tools_desc}\n\n"
            "Format:\nThought: <reasoning>\nAction: <JSON tool call>\n"
            "When done: Final Answer: <result>"
        )
        history = f"{system}\n\nUser: {query}\n"

        for step in range(max_steps):
            model = self.get_model_for_query(query)
            hw = self._get_hw_options(query)
            response = self.router.generate(
                history + "\nAssistant:", model=model, options=hw)
            history += f"\nAssistant: {response}\n"

            if "Final Answer:" in response:
                answer = response.split("Final Answer:", 1)[1].strip()
                if feedback_cb:
                    feedback_cb(f"[Step {step+1}] Final Answer reached.")
                return answer

            if "Action:" in response:
                action_text = response.split("Action:", 1)[1].strip()
                # Find JSON
                if "{" in action_text:
                    json_start = action_text.index("{")
                    json_end = action_text.rfind("}") + 1
                    action_json = action_text[json_start:json_end]
                    observation = self._execute_agent_action(action_json)
                    if len(observation) > 1000:
                        observation = observation[:1000] + "... [truncated]"
                    history += f"\nObservation: {observation}\n"
                    if feedback_cb:
                        feedback_cb(f"[Step {step+1}] Tool executed.")

        return "Reached max steps without final answer. Last response:\n" + response[:500]

    # ── Multi-model processing (shared history) ────────────────────────
    def process_query_multi(self, query: str, history: list = None,
                            profile_name: str = "SPEED", skill_name: str = "DEFAULT",
                            hw_options: dict = None) -> Tuple[str, list]:
        """Process query with shared history, skill-based prompts, and profile-aware retrieval."""
        # RAG retrieval — only for profiles that benefit, with strict threshold
        rag_k = 8 if profile_name in ("ACCURACY", "ULTRA_CONTEXT") else 5
        sources = []
        rag_context = ""
        if self.rag:
            try:
                hits = self.rag.hybrid_search(query, k=rag_k, final_k=2)
                relevant = [
                    h for h in hits
                    if h.get('rerank_score', h.get('score', 0)) >= 0.78
                    and h.get('metadata', {}).get('source', '') != 'conversation'
                ]
                if relevant:
                    rag_context = "\n---\n".join(h['content'][:300]
                                                 for h in relevant)
                    sources = [h.get('metadata', {}).get(
                        'source', '?') for h in relevant]
            except Exception:
                pass

        # Build system prompt (skill-based if available)
        sys_prompt = self.system_prompt
        if self.skill_manager and skill_name != "DEFAULT":
            try:
                skill_prompt = self.skill_manager.get_prompt(skill_name)
                if skill_prompt:
                    sys_prompt = skill_prompt
            except Exception:
                pass

        # Build conversation
        parts = [sys_prompt]
        if rag_context:
            parts.append(f"\nRelevant context:\n{rag_context}")
        if history:
            hist_text = "\n".join(
                f"{m['role']}: {m['content'][:200]}" for m in history[-10:])
            parts.append(f"\nConversation:\n{hist_text}")
        parts.append(f"\nUser: {query}\nAssistant:")

        full_prompt = "\n".join(parts)
        model = self.forced_model or self.router.route_query(query)[0]
        options = hw_options or self._get_hw_options(query)
        response = self.router.generate(
            full_prompt, model=model, options=options)
        return response, sources

    def get_model_for_query(self, query: str) -> str:
        """Get the appropriate model for this query."""
        if self.forced_model:
            return self.forced_model
        model, task, ctx = self.router.route_query(query)
        return model

    # Characters not allowed in tool arguments (prevents shell metacharacter injection)
    _SAFE_ARG_RE = re.compile(r'[;&|`$<>()\\\n\r]')

    def _try_tool_dispatch(self, query: str):
        """Detect natural-language tool requests. Returns (tool_name, args) or (None, None).
        Only matches when the query starts with a verb+tool or is solely the tool name,
        to avoid false positives on casual mentions mid-sentence."""
        verbs = r'(?:run|test|execute|use|try|call|invoke|scan\s+with|check\s+with)'
        q = query.strip()
        for tool_name in TOOLS:
            # verb+tool at start — OR — bare tool name alone / followed by args.
            # The bare-tool branch requires end-of-string or arg-like first chars
            # (flags, IPs/domains with dots, presets) to reject English prose
            # like "nmap is a great tool".
            verb_pattern = rf'^{verbs}\s+{re.escape(tool_name)}\b'
            bare_pattern = rf'^{re.escape(tool_name)}(?:\s+[-:0-9/.]|\s+\S+\.\S+|\s*$)'
            if re.search(verb_pattern, q, re.I) or re.search(bare_pattern, q, re.I):
                remaining = re.sub(rf'^{verbs}\s+', '', q, flags=re.I)
                remaining = re.sub(
                    rf'^{re.escape(tool_name)}\s*', '', remaining, flags=re.I).strip()
                # Strip shell metacharacters from args
                remaining = self._SAFE_ARG_RE.sub('', remaining)
                return tool_name, remaining
        return None, None

    def _try_security_dispatch(self, query: str):
        """Detect natural-language security/bash requests. Returns (type, args) or (None, None)."""
        q = query.strip().lower()
        # Security command center keywords
        sec_patterns = [
            (r'\b(run|do|execute|start)\s+(quick\s+)?security\s+(scan|check|overview)',
             'security', 'quick'),
            (r'\b(investigate|check)\s+(ports?|connections?)',
             'security', 'investigate'),
            (r'\b(hunt|discover|scan)\s+(network|subnet|hosts?)', 'security', 'hunt'),
            (r'\bfull\s+(security\s+)?audit\b', 'security', 'audit'),
            (r'\bcheck\s+(firewall|fw)\b', 'security', 'firewall'),
            (r'\b(traffic|flows?)\s+analysis\b', 'security', 'traffic'),
        ]
        # Bash script keywords
        bash_patterns = [
            (r'\b(run|start|launch)\s+(looting\s+larry|looting-larry|lootinglarry)\b',
             'bash', 'looting-scan'),
            (r'\b(homelab|home\s+lab)\s+(audit|scan|security)\b', 'bash', 'audit'),
            (r'\bverify\s+(network|connectivity)\b', 'bash', 'verify'),
            (r'\bipv6\s+scan\b', 'bash', 'ipv6'),
        ]
        for pattern, dtype, dargs in sec_patterns:
            if re.search(pattern, q):
                return dtype, dargs
        for pattern, dtype, dargs in bash_patterns:
            if re.search(pattern, q):
                return dtype, dargs
        return None, None

    async def process_query(self, query: str) -> str:
        """Process a user query with intelligent routing."""
        logger.info(f"Processing: {query[:50]}...")
        self.activity.emit(ActivityStream.QUERY_RECEIVED,
                           f"Query: {query[:80]}")

        # Check for natural-language security/bash dispatch
        dispatch_type, dispatch_args = self._try_security_dispatch(query)
        if dispatch_type == 'security' and SECURITY_AVAILABLE:
            self.activity.emit(ActivityStream.TOOL_DISPATCH,
                               f"Auto-security: {dispatch_args}")
            print(
                f"🛡️ Detected security request  running: /security {dispatch_args}")
            output = _security_center.handle_command("security", dispatch_args)
            print(output)
            self.conversation.add("user", query)
            self.conversation.add("assistant", output)
            self.activity.emit(ActivityStream.RESPONSE_DONE,
                               f"Security scan complete")
            return f"Security command executed. Output shown above."
        elif dispatch_type == 'bash' and BASH_AVAILABLE:
            self.activity.emit(ActivityStream.TOOL_DISPATCH,
                               f"Auto-bash: {dispatch_args}")
            print(
                f"🐚 Detected bash script request  running: /bash {dispatch_args}")
            output = _bash_runner.handle_command(dispatch_args)
            if output:
                print(output)
            self.conversation.add("user", query)
            self.conversation.add(
                "assistant", output or "[Bash script executed]")
            self.activity.emit(ActivityStream.RESPONSE_DONE,
                               f"Bash script complete")
            return f"Bash script executed. Output shown above."

        # Check if this is a natural-language security tool request
        tool_name, tool_args = self._try_tool_dispatch(query)
        if tool_name:
            self.activity.emit(ActivityStream.TOOL_DISPATCH,
                               f"Tool: {tool_name} {tool_args}")
            tool_obj = TOOLS.get(tool_name)
            if not tool_obj:
                return f"Tool '{tool_name}' not found."
            expanded = parse_args_with_preset(tool_obj, tool_args)
            if not expanded.startswith("__ERROR__"):
                print(
                    f"🔧 Detected tool request  running: {tool_obj.cmd} {expanded}")
                print(
                    f"Timeout: {tool_obj.default_timeout}s  (Ctrl+C to abort)\n")
                success, output = run_tool(tool_name, expanded)
                status = "Done" if success else "Finished (non-zero exit)"
                print(f"{output}\n\n[{status}] - agent_v2.py:1173")
                # Store in conversation so LLM can reference it
                self.conversation.add("user", query)
                self.conversation.add(
                    "assistant", f"[Tool executed: {tool_name} {tool_args}]\n{output}\n[{status}]")
                self.activity.emit(ActivityStream.RESPONSE_DONE,
                                   f"Tool {tool_name} complete", {"status": status})
                return f"Tool '{tool_name}' executed. Output shown above."

        # Get routing info
        model = self.get_model_for_query(query)
        task = self.router.detect_task(query)

        self.activity.emit(ActivityStream.MODEL_SELECTED,
                           f"{model} -> {task.value}", {"model": model, "task": task.value})
        print(f"🤖 Using model: {model} - agent_v2.py:1188")
        print(f"📋 Task type: {task.value} - agent_v2.py:1189")

        # Build context
        context_parts = [self.system_prompt]

        # Snapshot the last few turns BEFORE adding current message to avoid doubling it
        config = MODEL_CONFIGS.get(model)
        ctx_limit = config.context_limit if config else 8192
        # Reserve ~2k tokens for system prompt + current query + response overhead
        # Use up to half the remaining context for conversation history
        history_token_budget = (ctx_limit - 2048) // 2
        history_char_budget = history_token_budget * 4  # ~4 chars/token
        # Spread budget across 8 messages; floor at 4000, cap at 32000 per message
        max_chars_per_msg = max(4000, min(32000, history_char_budget // 8))
        self.activity.emit(ActivityStream.CONTEXT_BUDGET, f"ctx={ctx_limit} tokens, history={history_char_budget} chars", {
                           "ctx_limit": ctx_limit, "history_budget": history_char_budget})
        conv_context = self.conversation.get_context(
            n=8, max_chars_per_msg=max_chars_per_msg)
        if conv_context:
            context_parts.append(f"\nRecent conversation:\n{conv_context}")

        # Now record the user message
        self.conversation.add("user", query)

        # Add RAG context only for task types that truly benefit from retrieval,
        # with a strict relevance threshold to prevent hallucination from noise.
        rag_task_types = {TaskType.ANALYSIS, TaskType.SUMMARIZE}
        if self.rag and task in rag_task_types:
            self.activity.emit(ActivityStream.RAG_SEARCH,
                               "Searching knowledge base...")
            rag_hits = self.rag.hybrid_search(query, k=5, final_k=2)
            min_score = 0.78  # strict — only clearly relevant results
            relevant = [
                h['content'][:300] for h in rag_hits
                if h.get('rerank_score', h.get('score', 0)) >= min_score
                and h.get('metadata', {}).get('source', '') != 'conversation'
            ]
            if relevant:
                self.activity.emit(ActivityStream.RAG_SEARCH, f"RAG injected {len(relevant)} relevant docs", {
                                   "count": len(relevant)})
                context_parts.append(
                    f"\nRelevant context:\n" + "\n---\n".join(relevant))
            else:
                self.activity.emit(ActivityStream.RAG_SEARCH,
                                   "No relevant RAG docs (below threshold)")

        # Handle file-related queries
        if task == TaskType.FILE_EDIT or "file" in query.lower():
            file_context = self._handle_file_query(query)
            if file_context:
                context_parts.append(f"\nFile context:\n{file_context}")

        # Python debugger subagent
        if "debug python" in query.lower() or "debug script" in query.lower():
            import re as _re
            py_match = _re.search(r'[\w./\\-]+\.py', query)
            if py_match and 'python_debugger' in self.subagents:
                debug_out = self.subagents['python_debugger'](py_match.group())
                context_parts.append(f"\nDebug output:\n{debug_out}")

        # Build full prompt (after all context has been assembled)
        full_context = "\n".join(context_parts)
        full_prompt = f"{full_context}\n\nUser: {query}\n\nAssistant:"

        # Generate response with hardware profile
        hw_options = self._get_hw_options(query, task)
        self.activity.emit(ActivityStream.GENERATING, f"Generating via {model}...", {
                           "prompt_len": len(full_prompt)})
        response = self.router.generate(
            full_prompt, model=model, options=hw_options)
        self.activity.emit(ActivityStream.RESPONSE_DONE, f"Response: {len(response)} chars", {
                           "model": model, "response_len": len(response)})

        # Store response
        self.conversation.add("assistant", response)

        # Track in context manager
        if self.context_mgr:
            try:
                self.context_mgr.add_message("user", query)
                self.context_mgr.add_message("assistant", response)
            except Exception:
                pass

        # Store in legacy RAG manager
        if self.rag_manager:
            try:
                self.rag_manager.store_conversation(
                    query, response, {"source": "agent_cli"})
            except Exception:
                pass

        # Add to RAG conversation memory (prune to last 500 entries)
        if self.rag and getattr(self.rag, 'conv_collection', None):
            try:
                doc_id = f"conv_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                self.rag.conv_collection.add(
                    documents=[f"Q: {query}\nA: {response[:500]}"],
                    ids=[doc_id],
                    metadatas=[{"source": "conversation",
                                "timestamp": datetime.now().isoformat()}]
                )
                try:
                    existing = self.rag.conv_collection.get()
                    ids = existing.get("ids", [])
                    if len(ids) > 500:
                        self.rag.conv_collection.delete(
                            ids=ids[:len(ids) - 500])
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Failed to add to RAG memory: {e}")

        # Voice output
        if self.speech_enabled and self.voice_manager:
            try:
                self.voice_manager.speak(response)
            except Exception:
                pass

        return response

    def _handle_file_query(self, query: str) -> Optional[str]:
        """Handle file-related operations in query."""
        query_lower = query.lower()

        # Extract file paths from query
        words = query.split()
        potential_paths = [
            w for w in words if "/" in w or "\\" in w or "." in w[-5:]]

        results = []

        for path in potential_paths:
            # Clean up the path
            path = path.strip("'\".,;:")

            # Try to read the file
            content, success = self.browser.read_full(path)
            if success:
                # Truncate based on model context limit (reserve ~4K tokens for prompt+response)
                model = self.forced_model or self.router.current_model
                config = MODEL_CONFIGS.get(model)
                max_chars = ((config.context_limit - 4096)
                             * 4) if config else 32000
                # At least 8000 chars (~2K tokens)
                max_chars = max(8000, max_chars)
                if len(content) > max_chars:
                    content = content[:max_chars] + \
                        "\n... [truncated to fit context]"
                results.append(f"File: {path}\n```\n{content}\n```")

        return "\n\n".join(results) if results else None

    def execute_file_command(self, cmd: str, args: List[str]) -> str:
        """Execute a file browser command."""
        try:
            if cmd == "ls":
                path = args[0] if args else "."
                return self.browser.ls(path)
            elif cmd == "cd":
                path = args[0] if args else "."
                return self.browser.cd(path)
            elif cmd == "pwd":
                return self.browser.pwd()
            elif cmd == "tree":
                path = args[0] if args else "."
                depth = int(args[1]) if len(args) > 1 else 3
                return self.browser.tree(path, max_depth=depth)
            elif cmd == "cat" or cmd == "read" or cmd == "type":
                if not args:
                    return "❌ Usage: /cat <file> [start_line] [end_line]"
                path = args[0]
                # Single-path: prefer Universal File Handler for smart formatting
                if len(args) == 1:
                    return self.read_file(path)
                try:
                    start = int(args[1]) if len(args) > 1 else 1
                    end = int(args[2]) if len(args) > 2 else None
                except ValueError:
                    return "❌ Line numbers must be integers"
                return self.browser.read(path, start, end)
            elif cmd == "find":
                if not args:
                    return "❌ Usage: /find <pattern> [path] [-c for content search]"
                pattern = args[0]
                path = args[1] if len(
                    args) > 1 and not args[1].startswith("-") else "."
                content_search = "-c" in args
                return self.browser.find(pattern, path, content_search)
            elif cmd == "grep":
                if len(args) < 2:
                    return "❌ Usage: /grep <pattern> <file> [context_lines]"
                pattern = args[0]
                path = args[1]
                context = int(args[2]) if len(args) > 2 else 2
                return self.browser.grep(pattern, path, context)
            elif cmd == "edit":
                if len(args) < 4:
                    return "❌ Usage: /edit <file> <start_line> <end_line> <new_content> [--yes|--edit]"
                path = args[0]
                try:
                    start = int(args[1])
                    end = int(args[2])
                except ValueError:
                    return "❌ start_line and end_line must be integers"

                # Flags
                apply_now = "--yes" in args
                open_in_editor = "--edit" in args or "--open" in args
                content_parts = [a for a in args[3:]
                                 if a not in ("--yes", "--edit", "--open")]
                content = " ".join(content_parts)

                # If user wants interactive editor, open a temp file with selected lines
                if open_in_editor:
                    # Read full file and extract the target lines
                    full, ok = self.browser.read_full(path)
                    if not ok:
                        return f"❌ Cannot open file for editing: {full}"

                    lines = full.splitlines(keepends=True)
                    total = len(lines)
                    s = max(1, start)
                    e = min(end or total, total)
                    snippet = lines[s-1:e]

                    # Create temp file with same extension where possible
                    ext = Path(path).suffix or ".txt"
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False, suffix=ext, mode="w", encoding="utf-8")
                    try:
                        tmp.writelines(snippet)
                        tmp.flush()
                        tmp_name = tmp.name
                    finally:
                        tmp.close()

                    # Determine editor command
                    editor = os.environ.get("EDITOR")
                    if not editor:
                        if shutil.which("code"):
                            editor_cmd = ["code", "--wait", tmp_name]
                        elif shutil.which("notepad.exe") or shutil.which("notepad"):
                            editor_cmd = ["notepad", tmp_name]
                        else:
                            editor_cmd = [tmp_name]
                    else:
                        # split editor string into args
                        editor_cmd = editor.split() + [tmp_name]

                    # Launch editor and wait
                    try:
                        subprocess.run(editor_cmd)
                    except Exception as e:
                        return f"❌ Failed to open editor: {e}"

                    # Read edited content
                    try:
                        with open(tmp_name, "r", encoding="utf-8") as f:
                            new_content = f.read()
                    finally:
                        try:
                            os.unlink(tmp_name)
                        except Exception:
                            pass

                    # Apply edits with backup
                    result = self.browser.edit_lines(
                        path, start, end, new_content, create_backup=True)
                    return f"🔔 Editor saved changes.\n{result}"

                # Non-interactive preview/apply flow
                original = self.browser.read(path, start, end)
                proposed_lines = content.splitlines()
                proposed_display = [f"{i:4d} | {line}" for i, line in enumerate(
                    proposed_lines, start=start)]

                preview = ["🔎 Edit preview:", "--- Original ---",
                           original, "--- Proposed ---"]
                preview.extend(proposed_display or ["[empty]"])
                preview_text = "\n".join(preview)

                if not apply_now:
                    preview_text += f"\n\nTo apply this change, re-run with --yes: /edit {path} {start} {end} <new_content> --yes or use --edit to open your editor"
                    return preview_text

                # Apply change with backup
                result = self.browser.edit_lines(
                    path, start, end, content, create_backup=True)
                return preview_text + "\n\n" + result
            elif cmd == "write":
                if len(args) < 2:
                    return "❌ Usage: /write <file> <content> [--yes]"
                path = args[0]
                apply_now = "--yes" in args
                content_parts = [a for a in args[1:] if a != "--yes"]
                content = " ".join(content_parts)

                preview = [
                    f"🔎 Write preview: {path}", f"{len(content)} bytes will be written.", "--- Start of content ---"]
                preview.extend(content.splitlines()[:20])
                if len(content.splitlines()) > 20:
                    preview.append("... [truncated]")
                preview.append("--- End of content ---")
                preview_text = "\n".join(preview)

                if not apply_now:
                    preview_text += f"\n\nTo apply this write, re-run with --yes: /write {path} <content> --yes"
                    return preview_text

                result = self.browser.write(path, content, create_backup=True)
                return preview_text + "\n\n" + result

            elif cmd == "open":
                # Open file in external editor, show diff, prompt to apply
                if len(args) < 1:
                    return "❌ Usage: /open <file> [--diff] [--yes]"
                path = args[0]
                flags = set(a for a in args[1:])
                apply_now = "--yes" in flags

                full, ok = self.browser.read_full(path)
                if not ok:
                    return f"❌ Cannot open file: {full}"

                ext = Path(path).suffix or ".txt"
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=ext, mode="w", encoding="utf-8"
                )
                try:
                    tmp.write(full)
                    tmp.flush()
                    tmp_name = tmp.name
                finally:
                    tmp.close()

                editor = os.environ.get("EDITOR")
                if not editor:
                    if shutil.which("code"):
                        editor_cmd = ["code", "--wait", tmp_name]
                    elif shutil.which("notepad.exe") or shutil.which("notepad"):
                        editor_cmd = ["notepad", tmp_name]
                    else:
                        editor_cmd = [tmp_name]
                else:
                    editor_cmd = editor.split() + [tmp_name]

                try:
                    subprocess.run(editor_cmd)
                except Exception as e:
                    return f"❌ Failed to open editor: {e}"

                try:
                    with open(tmp_name, "r", encoding="utf-8") as f:
                        new_content = f.read()
                finally:
                    try:
                        os.unlink(tmp_name)
                    except Exception:
                        pass

                if new_content == full:
                    return "ℹ️ No changes made."

                diff_lines = list(
                    difflib.unified_diff(
                        full.splitlines(),
                        new_content.splitlines(),
                        fromfile=path,
                        tofile=f"{path} (edited)",
                        lineterm="",
                    )
                )
                diff_text = "\n".join(
                    diff_lines) if diff_lines else "(no diff)"

                if not apply_now:
                    print("\n - agent_v2.py:1567" +
                          "=" * 40 + " Diff " + "=" * 40)
                    print(diff_text)
                    print("= - agent_v2.py:1570" * 92 + "\n")
                    try:
                        ans = input("Apply changes? (y/N): ").strip().lower()
                    except EOFError:
                        ans = ""
                    if ans not in ("y", "yes"):
                        return "✖️ Changes discarded."

                # Apply write with backup
                target = (self.browser.current_dir / path).resolve()
                try:
                    self.browser._create_backup(target)
                except Exception:
                    pass

                try:
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(new_content)
                except Exception as e:
                    return f"❌ Failed to write file: {e}"

                return f"✅ Applied changes to {path}.\nDiff:\n{diff_text}"

            elif cmd == "csv-edit":
                # Usage: /csv-edit <file> <key_col> <key_val> <target_col> <new_val> [--add]
                if not PANDAS_AVAILABLE:
                    return "❌ /csv-edit requires pandas. Install: pip install pandas"
                if len(args) < 5:
                    return "❌ Usage: /csv-edit <file> <key_col> <key_val> <target_col> <new_val> [--add]"
                path = args[0]
                key_col = args[1]
                key_val = args[2]
                target_col = args[3]
                new_val = args[4]
                add_if_missing = "--add" in args

                target = (self.browser.current_dir / path).resolve()
                if not target.exists():
                    return f"❌ File not found: {path}"

                try:
                    df = pd.read_csv(target, dtype=str)
                except Exception as e:
                    return f"❌ Failed to read CSV: {e}"

                if key_col not in df.columns:
                    return f"❌ Key column not found: {key_col}"

                mask = df[key_col].fillna("").astype(str) == str(key_val)
                if hasattr(mask, 'any') and mask.any():
                    count = int(mask.sum()) if hasattr(mask, 'sum') else 0
                    if target_col not in df.columns:
                        df[target_col] = ""
                    df.loc[mask, target_col] = new_val
                    try:
                        self.browser._create_backup(target)
                    except Exception:
                        pass
                    df.to_csv(target, index=False)
                    return f"✅ Updated {count} row(s) in {path}"
                else:
                    if add_if_missing:
                        if target_col not in df.columns:
                            df[target_col] = ""
                        new_row = {c: "" for c in df.columns}
                        new_row[key_col] = key_val
                        new_row[target_col] = new_val
                        df = pd.concat(
                            [df, pd.DataFrame([new_row])], ignore_index=True)
                        try:
                            self.browser._create_backup(target)
                        except Exception:
                            pass
                        df.to_csv(target, index=False)
                        return f"✅ Added new row to {path}"
                    return f"⚠️ No matching rows for {key_col}={key_val}. Use --add to append."

            else:
                return f"❌ Unknown file command: {cmd}"
        except Exception as e:
            return f"❌ Error: {e}"


async def main():
    """Main interactive loop."""
    # Rich console or plain
    console = None
    if RICH_AVAILABLE:
        theme = Theme({
            "brand": "gold1", "muted": "grey70", "good": "green", "bad": "red",
        })
        console = Console(theme=theme)

    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║  LARRY G-FORCE — Enhanced Multi-Model Local AI Agent v2            ║
╠══════════════════════════════════════════════════════════════════════╣
║  🤖 Multi-model routing   📁 File browsing & editing              ║
║  🧠 Production RAG        💾 Persistent context                   ║
║  🔒 100% Localhost         ⚡ Hardware profiles                    ║
║  🛡️ Security tools         🎤 Voice I/O                           ║
║  🧰 Sandbox safe-edit     🤖 Autonomous agentic mode              ║
╚══════════════════════════════════════════════════════════════════════╝"""
    print(banner)
    print("\n  /help  full command list  |  /quit  exit - agent_v2.py:1674")
    print("/profile  hardware profile  |  /agent <task>  autonomous mode - agent_v2.py:1675")
    print("= - agent_v2.py:1676" * 70)

    agent = EnhancedAgent()

    # Setup readline history
    history_file = str(BASE_DIR / ".cli_history")
    if readline:
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(1000)

    while True:
        try:
            user_input = input("\n👤 You: ").strip()

            if not user_input:
                continue

            # Multi-line paste mode: start with <<< or """ to enter block input.
            # Type the same delimiter on its own line to finish.
            if user_input in ("<<<", '"""', "'''"):
                delimiter = user_input
                print(
                    f"(multiline mode  paste your content, then type {delimiter} on its own line to send)")
                lines = []
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line.strip() == delimiter:
                        break
                    lines.append(line)
                user_input = "\n".join(lines).strip()
                if not user_input:
                    continue

            if readline:
                readline.add_history(user_input)
                readline.write_history_file(history_file)

            # Handle commands
            if user_input.startswith("/"):
                parts = user_input[1:].split()
                cmd = parts[0].lower()
                args = parts[1:]

                if cmd in ["quit", "exit", "q"]:
                    print("👋 Goodbye! - agent_v2.py:1726")
                    break

                elif cmd == "models":
                    print(list_models())
                    continue

                elif cmd == "model":
                    if args:
                        model_name = args[0]
                        if model_name.lower() == "auto":
                            agent.forced_model = None
                            print(
                                "✅ Switched to auto model routing")
                        elif agent.router.set_model(model_name):
                            agent.forced_model = model_name
                            print(
                                f"✅ Switched to model: {model_name}")
                        else:
                            print(
                                f"❌ Model not found: {model_name}")
                            print(
                                "Use /models to see available models")
                    else:
                        current = agent.forced_model or "auto (routing)"
                        print(f"Current model: {current} - agent_v2.py:1751")
                    continue

                elif cmd == "stats":
                    print("\n📊 Statistics: - agent_v2.py:1755")
                    print(
                        f"Available models: {len(agent.router.available_models)}")
                    print(
                        f"Current model: {agent.forced_model or 'auto'}")
                    print(
                        f"Conversation history: {len(agent.conversation.history)} messages")
                    print(
                        f"Current directory: {agent.browser.current_dir}")

                    if agent.rag:
                        rag_stats = agent.rag.get_stats()
                        print(
                            f"Production RAG: {rag_stats.get('status', 'unknown')}")
                        print(
                            f"RAG reranker: {rag_stats.get('reranker', 'unknown')}")
                        if "collections" in rag_stats:
                            for name, count in rag_stats["collections"].items():
                                print(
                                    f"{name}: {count} chunks")

                    if agent.rag_manager:
                        try:
                            stats = agent.rag_manager.get_stats()
                            print(
                                f"Legacy RAG: {stats.get('status', 'unknown')} ({stats.get('backend', 'N/A')})")
                            if "collections" in stats:
                                for name, count in stats["collections"].items():
                                    print(
                                        f"{name}: {count} documents")
                            print(
                                f"Total legacy documents: {stats.get('total_documents', 0)}")
                        except Exception:
                            pass

                    if agent.voice_manager:
                        try:
                            voice_status = agent.voice_manager.get_status()
                            print("Voice capabilities: - agent_v2.py:1793")
                            print(
                                f"STT: {voice_status.get('stt', voice_status.get('stt_model', 'Not available'))}")
                            print(
                                f"TTS: {voice_status.get('tts', voice_status.get('tts_engine', 'Not available'))}")
                            print(
                                f"Voice sample: {voice_status.get('voice_sample', 'Not loaded')}")
                        except Exception:
                            pass
                    continue

                elif cmd == "clear":
                    agent.conversation.clear()
                    print("🧹 History cleared - agent_v2.py:1806")
                    continue

                elif cmd == "history":
                    print("\n📝 Conversation History: - agent_v2.py:1810")
                    for i, msg in enumerate(agent.conversation.history[-10:]):
                        role = "👤" if msg["role"] == "user" else "🤖"
                        print(
                            f"{role} {msg['content'][:80]}...")
                    continue

                elif cmd == "index":
                    if args:
                        directory = args[0]
                        try:
                            max_files = int(args[1]) if len(args) > 1 else 1000
                        except ValueError:
                            max_files = 1000
                        print(f"📁 Indexing: {directory} - agent_v2.py:1824")
                        if agent.rag:
                            result = agent.rag.index_directory(
                                directory, max_files=max_files)
                            print(
                                f"✅ Indexed {result.get('indexed', 0)} files")
                            print(
                                f"❌ Failed: {result.get('failed', 0)}")
                            print(
                                f"⚠️ Skipped: {result.get('skipped', 0)}")
                        elif agent.rag_manager:
                            result = agent.rag_manager.index_directory(
                                directory)
                            print(
                                f"✅ Indexed {result.get('indexed_count', 0)} files")
                        else:
                            print("❌ RAG not available - agent_v2.py:1840")
                    else:
                        print(
                            "❌ Usage: /index <directory> [max_files]")
                    continue

                elif cmd == "web":
                    if args:
                        url = args[0]
                        if not url.startswith(("http://", "https://")):
                            print(
                                "❌ Only http:// and https:// URLs are allowed")
                            continue
                        print(f"🌐 Fetching: {url} - agent_v2.py:1853")
                        try:
                            import urllib.request
                            with urllib.request.urlopen(url, timeout=15) as resp:
                                raw = resp.read().decode('utf-8', errors='ignore')
                            # Strip HTML tags simply
                            import re
                            text = re.sub(r'<[^>]+>', ' ', raw)
                            text = re.sub(r'\s+', ' ', text).strip()[:8000]
                            if agent.rag and getattr(agent.rag, 'kb_collection', None):
                                doc_id = f"web_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                                agent.rag.kb_collection.add(
                                    documents=[text],
                                    ids=[doc_id],
                                    metadatas=[
                                        {"source": url, "indexed_at": datetime.now().isoformat()}]
                                )
                                print(
                                    f"✅ Fetched and indexed: {url}")
                            else:
                                print(
                                    f"✅ Fetched (RAG unavailable, not indexed): {url[:60]}")
                        except Exception as e:
                            print(f"❌ Error: {e} - agent_v2.py:1876")
                    else:
                        print("❌ Usage: /web <url> - agent_v2.py:1878")
                    continue

                elif cmd in ["ls", "cd", "pwd", "tree", "cat", "read", "type",
                             "find", "grep", "edit", "open", "write", "csv-edit"]:
                    result = agent.execute_file_command(cmd, args)
                    print(result)
                    continue

                # ── Kali / Security tools ─────────────────────────────────
                elif cmd == "tools":
                    if not args:
                        print(list_tools())
                        continue
                    from kali_tools import CATEGORIES
                    first = args[0].lower()
                    # 1. Valid category → show that category
                    if first in CATEGORIES:
                        print(list_tools(first))
                        continue
                    # 2. Known tool name → show help + usage + presets
                    if first in TOOLS:
                        print(tool_help(first))
                        print(
                            f"\nTo run this tool: /kali {first} [args]")
                        continue
                    # 3. Neither category nor tool — show full list and hint
                    print(list_tools())
                    print(
                        f"\n⚠️  '{' '.join(args)}' is not a known category or tool.")
                    print("Categories: - agent_v2.py:1908" +
                          ", ".join(CATEGORIES.keys()))
                    print(
                        "To run a specific tool: /kali <tool> [args]")
                    continue

                elif cmd == "kali":
                    if not args:
                        print("Usage: /kali <tool> [:<preset>] [args]\n - agent_v2.py:1916"
                              "       /kali list [category]\n"
                              "       /kali help <tool>")
                        continue
                    sub = args[0].lower()
                    if sub == "list":
                        cat = args[1] if len(args) > 1 else None
                        print(list_tools(cat))
                        continue
                    if sub == "help":
                        tname = args[1] if len(args) > 1 else ""
                        print(tool_help(tname))
                        continue
                    # /kali <toolname> [args...]
                    tool_name = sub
                    raw_args = " ".join(args[1:])
                    tool_obj = TOOLS.get(tool_name)
                    if not tool_obj:
                        print(
                            f"Unknown tool '{tool_name}'. Use /kali list or /tools")
                        continue
                    expanded = parse_args_with_preset(tool_obj, raw_args)
                    if expanded.startswith("__ERROR__"):
                        print(expanded[9:])
                        continue
                    print(
                        f"Running: {tool_obj.cmd} {expanded}")
                    print(
                        f"Timeout: {tool_obj.default_timeout}s  (Ctrl+C to abort)\n")
                    success, output = run_tool(tool_name, expanded)
                    status = "Done" if success else "Finished (non-zero exit)"
                    print(f"{output}\n\n[{status}] - agent_v2.py:1947")
                    agent.conversation.add(
                        "user", f"/kali {tool_name} {raw_args}")
                    agent.conversation.add(
                        "assistant", f"[Tool: {tool_name} {raw_args}]\n{output}\n[{status}]")
                    continue

                # Shortcut: /nmap, /nikto, /whatweb, etc. → /kali <tool>
                elif cmd in TOOLS:
                    raw_args = " ".join(args)
                    tool_obj = TOOLS[cmd]
                    expanded = parse_args_with_preset(tool_obj, raw_args)
                    if expanded.startswith("__ERROR__"):
                        print(expanded[9:])
                        continue
                    print(
                        f"Running: {tool_obj.cmd} {expanded}")
                    print(
                        f"Timeout: {tool_obj.default_timeout}s  (Ctrl+C to abort)\n")
                    success, output = run_tool(cmd, expanded)
                    status = "Done" if success else "Finished (non-zero exit)"
                    print(f"{output}\n\n[{status}] - agent_v2.py:1968")
                    agent.conversation.add("user", f"/{cmd} {raw_args}")
                    agent.conversation.add(
                        "assistant", f"[Tool: {cmd} {raw_args}]\n{output}\n[{status}]")
                    continue

                # ── Security Command Center ───────────────────────────────
                elif cmd in ("security", "sec"):
                    if not SECURITY_AVAILABLE:
                        print(
                            "\n⚠️ Security Command Center not available.")
                        print(
                            "Place security_command_center.py + port_investigator.py in AgentLarry dir")
                    else:
                        sec_args = " ".join(args) if args else ""
                        agent.activity.emit(
                            agent.activity.TOOL_DISPATCH, f"Security: {sec_args or 'quick'}")
                        output = _security_center.handle_command(
                            "security", sec_args)
                        print(output)
                        agent.conversation.add("user", user_input)
                        agent.conversation.add("assistant", output)
                    continue

                elif cmd in ("investigate", "ports"):
                    if not SECURITY_AVAILABLE:
                        print("\n⚠️ Security tools not available - agent_v2.py:1994")
                    else:
                        inv_args = " ".join(args) if args else ""
                        output = _security_center.handle_command(
                            "security", f"investigate {inv_args}".strip())
                        print(output)
                        agent.conversation.add("user", user_input)
                        agent.conversation.add("assistant", output)
                    continue

                elif cmd == "hunt":
                    if not SECURITY_AVAILABLE:
                        print("\n⚠️ Security tools not available - agent_v2.py:2006")
                    else:
                        hunt_args = " ".join(args) if args else ""
                        output = _security_center.handle_command(
                            "security", f"hunt {hunt_args}".strip())
                        print(output)
                        agent.conversation.add("user", user_input)
                        agent.conversation.add("assistant", output)
                    continue

                # ── Bash Script Runner ────────────────────────────────────
                elif cmd == "bash":
                    if not BASH_AVAILABLE:
                        print(
                            "\n⚠️ Bash Script Runner not available.")
                        print(
                            "Place bash_script_runner.py in AgentLarry dir")
                    else:
                        bash_args = " ".join(args) if args else ""
                        agent.activity.emit(
                            agent.activity.TOOL_DISPATCH, f"Bash: {bash_args or 'list'}")
                        output = _bash_runner.handle_command(bash_args)
                        if output:
                            print(output)
                        agent.conversation.add("user", user_input)
                        agent.conversation.add(
                            "assistant", output or "[Bash command executed]")
                    continue

                # ── G-FORCE Extended Commands ─────────────────────────
                elif cmd == "help" or cmd == "h" or cmd == "?":
                    help_text = "\n".join([
                        "Commands:",
                        "  /help                - Show this help",
                        "  /quit, /exit, /q     - Exit",
                        "  /models              - List available Ollama models",
                        "  /model <name>        - Set model (or 'auto' for routing)",
                        "  /stats               - Show statistics",
                        "  /clear               - Clear history",
                        "  /history             - Show conversation history",
                        "  /profile [name]      - Show/switch hardware profile (SPEED/ACCURACY/ULTRA_CONTEXT)",
                        "  /tokens [text]       - Count tokens (uses TokenManager)",
                        "",
                        "Context Management:",
                        "  /context             - Show context usage and token stats",
                        "  /summarize           - Force context summarization",
                        "  /sessions [new]      - List sessions or start new one",
                        "  /tasks               - Show task→model mappings",
                        "",
                        "File Commands:",
                        "  /ls [path]           - List directory",
                        "  /cd <path>           - Change directory",
                        "  /pwd                 - Print working directory",
                        "  /tree [path] [depth] - Show directory tree",
                        "  /cat <file> [start] [end] - Read file (smart formatting)",
                        "  /find <pattern> [path] [-c] - Find files (-c for content)",
                        "  /grep <pattern> <file> - Search in file",
                        "  /edit <file> <start> <end> <content> [--yes|--edit] - Edit lines",
                        "  /open <file> [--diff] [--yes] - Open in editor (shows diff, prompts to apply)",
                        "  /write <file> <content> [--yes] - Preview then write",
                        "  /csv-edit <file> <key_col> <key_val> <target_col> <new_val> [--add]",
                        "  /run <script>        - Execute .py/.ps1/.bat scripts",
                        "",
                        "URL Processing (or just paste a URL):",
                        "  /web <url>           - Scrape & index web page",
                        "  /scrape <url>        - Scrape webpage to markdown",
                        "  /search_web <query>  - Brave Search (via MCP)",
                        "  /youtube <url>       - Get YouTube transcript / summary",
                        "  (Auto-detects URLs - just paste and press Enter!)",
                        "",
                        "Indexing & RAG:",
                        "  /index <dir> [limit] - Index directory for Production RAG",
                        "  /rag <question>      - Ask about codebase via RAG",
                        "  /ask <question>      - Alias for /rag",
                        "  /search <query>      - Search knowledge base directly",
                        "",
                        "Sandbox (Safe Edit Workflow):",
                        "  /sandbox stage <file>    - Stage for editing",
                        "  /sandbox edit <f> <txt>  - Edit in sandbox",
                        "  /sandbox test <file>     - Test changes",
                        "  /sandbox deploy <file>   - Deploy with backup",
                        "  /sandbox rollback <file> - Rollback to backup",
                        "  /sandbox status          - Show staged files",
                        "",
                        "Agentic Mode:",
                        "  /agent <task>        - Autonomous multi-step task solving",
                        "",
                        "MCP Tools (Native - No Docker Required):",
                        "  /mcp                 - Show MCP tools status",
                        "  /github, /gh         - GitHub commands (repos, issues, prs, search)",
                        "  /memory              - Knowledge graph (show, search, add, observe)",
                        "",
                        "Web & Finance (local-first, Playwright + Ollama):",
                        "  /web <url>           - Scrape URL to markdown",
                        "  /web summarize <url> - Scrape + summarize via local LLM",
                        "  /youtube <url> [summarize] - YouTube transcript/summary",
                        "  /sentiment <topic> [sources] - Aggregate sentiment analysis",
                        "  /prices <sym,...> [crypto|forex] - Live prices (no API key)",
                        "  /headlines [source]  - Finance news (reuters/marketwatch/cnbc)",
                        "  /forexfactory, /ff   - Today's economic calendar",
                        "  /search_web <query>  - Brave Search (needs API key)",
                        "",
                        "Voice Commands:",
                        "  /voice               - Show voice module status",
                        "  /speak <text>        - Generate and play voice",
                        "  /listen              - Voice input mode instructions",
                        "  /transcribe <file>   - Transcribe audio file to text",
                        "",
                        "Security Tools:",
                        "  /tools [category]    - List security tools",
                        "  /kali <tool> [args]  - Run Kali tool",
                        "  /security [subcmd]   - Security Command Center",
                        "  /investigate, /ports - Port investigation",
                        "  /hunt                - Network host discovery",
                        "  /bash [subcmd]       - Bash security scripts",
                        "",
                        "Skills:",
                        "  /skill [name]        - List or set active skill profile",
                    ])
                    print(help_text)
                    continue

                elif cmd == "profile":
                    if args:
                        result = agent.set_profile(args[0])
                        print(f"{result} - agent_v2.py:2131")
                    else:
                        print(
                            f"\n{agent.get_profile_info()}")
                    continue

                elif cmd == "context":
                    if agent.context_mgr:
                        try:
                            info = agent.context_mgr.get_stats()
                            print(f"\n📊 Context: {info} - agent_v2.py:2141")
                        except Exception as e:
                            print(f"Context info: {e} - agent_v2.py:2143")
                    else:
                        print(
                            f"History: {len(agent.conversation.history)} messages")
                        print(
                            f"Profile: {agent.current_profile}")
                    continue

                elif cmd == "tokens":
                    text = " ".join(
                        args) if args else agent.conversation.get_context(n=20)
                    count = agent.count_tokens(text)
                    print(f"Tokens: {count:,} - agent_v2.py:2155")
                    continue

                elif cmd in ("web", "scrape"):
                    result = agent.execute_web_command("web", args)
                    print(result)
                    continue

                elif cmd == "search_web":
                    result = agent.execute_web_command("search_web", args)
                    print(result)
                    continue

                elif cmd == "youtube":
                    result = agent.execute_web_command("youtube", args)
                    print(result)
                    continue

                elif cmd == "sentiment":
                    result = agent.execute_web_command("sentiment", args)
                    print(result)
                    continue

                elif cmd == "prices":
                    result = agent.execute_web_command("prices", args)
                    print(result)
                    continue

                elif cmd == "headlines":
                    result = agent.execute_web_command("headlines", args)
                    print(result)
                    continue

                elif cmd in ("forexfactory", "ff"):
                    result = agent.execute_web_command("forexfactory", args)
                    print(result)
                    continue

                elif cmd == "voice":
                    if not VOICE_AVAILABLE or not agent.voice_manager:
                        print("❌ Voice module not available - agent_v2.py:2195")
                        continue
                    try:
                        status = agent.voice_manager.get_status()
                    except Exception as e:
                        print(f"❌ Voice status failed: {e} - agent_v2.py:2200")
                        continue
                    print("\n🎤 Voice Module Status: - agent_v2.py:2202")
                    print("= - agent_v2.py:2203" * 40)
                    print(
                        f"🗣️ STT: {'✅' if status.get('stt_available') else '❌'} {status.get('stt_model', 'N/A')}")
                    print(
                        f"🔊 TTS: {'✅' if status.get('tts_available') else '❌'} {status.get('tts_engine', 'N/A')}")
                    print(
                        f"🎭 Voice Cloning: {'✅' if status.get('voice_cloning') else '❌'}")
                    print(
                        f"📁 Voice Sample: {'✅' if status.get('voice_sample') else '❌'}")
                    tasks = status.get("voice_tasks", [])
                    print(
                        f"🎯 Voice Tasks: {', '.join(tasks) if tasks else 'None'}")
                    continue

                elif cmd == "speak":
                    if not VOICE_AVAILABLE or not agent.voice_manager:
                        print("❌ Voice module not available - agent_v2.py:2219")
                        continue
                    if not args:
                        print("❌ Usage: /speak <text to speak> - agent_v2.py:2222")
                        continue
                    text = " ".join(args)
                    print(
                        f"🎭 Generating voice for: {text[:50]}{'...' if len(text) > 50 else ''}")
                    try:
                        audio_path = agent.voice_manager.speak(text)
                        if audio_path:
                            print(
                                f"✅ Voice generated: {audio_path}")
                            print("🎵 Playing audio... - agent_v2.py:2232")
                            try:
                                if platform.system() == "Windows":
                                    os.startfile(audio_path)
                                elif platform.system() == "Darwin":
                                    subprocess.run(["afplay", str(audio_path)])
                                else:
                                    subprocess.run(
                                        ["xdg-open", str(audio_path)])
                            except Exception as e:
                                print(
                                    f"⚠️ Could not autoplay: {e}")
                        else:
                            print("✅ Speaking... - agent_v2.py:2245")
                    except Exception as e:
                        print(
                            f"❌ Voice generation failed: {e}")
                    continue

                elif cmd == "listen":
                    if not VOICE_AVAILABLE or not agent.voice_manager:
                        print("❌ Voice module not available - agent_v2.py:2253")
                        continue
                    print(
                        "🎙️ Voice input mode  speak now (press Enter when done)")
                    print(
                        "Note: This requires a microphone and audio file input")
                    print("For now, you can: - agent_v2.py:2259")
                    print("1. Record audio to a file (WAV/MP3/OGG) - agent_v2.py:2260")
                    print("2. Use: /transcribe <audio_file_path> - agent_v2.py:2261")
                    continue

                elif cmd == "transcribe":
                    if not VOICE_AVAILABLE or not agent.voice_manager:
                        print("❌ Voice module not available - agent_v2.py:2266")
                        continue
                    if not args:
                        print(
                            "❌ Usage: /transcribe <audio_file_path>")
                        continue
                    audio_path = " ".join(args)
                    if not os.path.exists(audio_path):
                        print(
                            f"❌ Audio file not found: {audio_path}")
                        continue
                    print(f"🎤 Transcribing: {audio_path} - agent_v2.py:2277")
                    try:
                        text = agent.voice_manager.transcribe(audio_path)
                        if text and text.strip():
                            print(f"📝 Transcribed: {text} - agent_v2.py:2281")
                            print(
                                "\n🤖 Processing transcribed text...")
                            response = await agent.process_query(text)
                            print(f"💬 Response: {response} - agent_v2.py:2285")
                        else:
                            print("❌ Could not transcribe audio - agent_v2.py:2287")
                    except Exception as e:
                        print(
                            f"❌ Transcription failed: {e}")
                    continue

                elif cmd == "sandbox":
                    if not args:
                        print(
                            "Usage: /sandbox <stage|edit|test|deploy|rollback|status> [args]")
                    else:
                        sub = args[0].lower()
                        if sub == "stage" and len(args) > 1:
                            print(agent.sandbox_stage_file(args[1]))
                        elif sub == "edit" and len(args) > 2:
                            print(agent.sandbox_edit_file(
                                args[1], " ".join(args[2:])))
                        elif sub == "test" and len(args) > 1:
                            print(agent.sandbox_test_changes(args[1]))
                        elif sub == "deploy" and len(args) > 1:
                            print(agent.sandbox_deploy(args[1]))
                        elif sub == "rollback" and len(args) > 1:
                            print(agent.sandbox_rollback(args[1]))
                        elif sub == "status":
                            print(agent.get_sandbox_status())
                        else:
                            print(
                                "Usage: /sandbox <stage|edit|test|deploy|rollback|status> [args]")
                    continue

                elif cmd == "agent":
                    if not args:
                        print("Usage: /agent <task description> - agent_v2.py:2319")
                    else:
                        task = " ".join(args)
                        print(
                            f"🤖 Starting autonomous agent for: {task}")

                        def _feedback(msg):
                            print(f"{msg} - agent_v2.py:2326")
                        result = await agent.process_query_agentic(task, feedback_cb=_feedback)
                        print(
                            f"\n🤖 Agent result:\n{result}")
                    continue

                elif cmd == "mcp":
                    if MCP_AVAILABLE and agent.mcp:
                        print(
                            "\n🔌 MCP Tools Status (Native  No Docker):")
                        # Show the actual servers loaded by MCPClient — this is the
                        # source of truth. Avoids hardcoded label list mismatches.
                        try:
                            loaded = sorted(agent.mcp.client.servers.keys())
                        except Exception:
                            loaded = []
                        try:
                            status = agent.mcp.get_status()
                        except Exception:
                            status = {}
                        print(
                            f"Servers loaded: {len(loaded)}")
                        if loaded:
                            print(
                                f"Names: {', '.join(loaded)}")
                        print()
                        # Known tool-wrapper categories with per-feature status
                        for key, label, note in [
                            ("filesystem",   "Filesystem",    "local sandbox r/w"),
                            ("memory",       "Memory",        "knowledge graph"),
                            ("sqlite",       "SQLite",
                             "data/unified_context.db"),
                            ("context7",     "Context7",
                             "library docs lookup"),
                            ("playwright",   "Playwright",    "headless browser"),
                            ("n8n",          "n8n",
                             "workflow automation"),
                            ("podman",       "Podman/Docker", "container mgmt"),
                            ("brave_search", "Brave Search",
                             "needs BRAVE_API_KEY in .env"),
                            ("github",       "GitHub",
                             "needs GITHUB_TOKEN in .env"),
                        ]:
                            ok = status.get(key, False)
                            icon = "✅" if ok else "❌"
                            print(
                                f"{icon} {label:<14}  {note}")
                        # Extra loaded servers not in the standard wrapper set
                        extras = [s for s in loaded if s not in {
                            "filesystem", "memory", "sqlite", "context7", "playwright",
                            "n8n", "podman", "brave-search", "github",
                        }]
                        if extras:
                            print()
                            print(
                                f"Also loaded: {', '.join(extras)}")
                    else:
                        print(
                            "❌ MCP tools not available  check mcp.json and mcp_servers/ package")
                    continue

                elif cmd in ("rag", "ask"):
                    if not args:
                        print("❌ Usage: /rag <question> - agent_v2.py:2389")
                    else:
                        rag_query = " ".join(args)
                        print(agent.ask_about_code(rag_query))
                    continue

                elif cmd == "summarize":
                    if CONTEXT_MANAGER_AVAILABLE and agent.context_mgr:
                        print("📝 Forcing context summarization... - agent_v2.py:2397")
                        try:
                            summary = agent.context_mgr.force_summarize()
                            if summary:
                                print(
                                    f"✅ Context summarized ({len(summary)} chars)")
                                try:
                                    stats = agent.context_mgr.get_stats()
                                    print(
                                        f"New token usage: {stats.get('current_tokens', 0):,} / {stats.get('max_tokens', 0):,}")
                                except Exception:
                                    pass
                            else:
                                print(
                                    "⚠️ No messages to summarize")
                        except Exception as e:
                            print(
                                f"❌ Summarization failed: {e}")
                    else:
                        print("❌ Context manager not available - agent_v2.py:2416")
                    continue

                elif cmd == "sessions":
                    if CONTEXT_MANAGER_AVAILABLE and agent.context_mgr:
                        if args and args[0] == "new":
                            try:
                                new_id = agent.context_mgr.new_session()
                                print(
                                    f"✅ New session: {str(new_id)[:8]}...")
                            except Exception as e:
                                print(
                                    f"❌ Could not create session: {e}")
                        else:
                            try:
                                sessions = agent.context_mgr.list_sessions()
                                current = getattr(
                                    agent.context_mgr, 'current_session', None)
                                print("\n📋 Sessions: - agent_v2.py:2434")
                                for sess in sessions:
                                    sid = sess.get("id", "?")
                                    marker = "→" if sid == current else " "
                                    print(
                                        f"{marker} {str(sid)[:8]}... ({sess.get('messages', 0)} msgs, {sess.get('tokens', 0):,} tokens)")
                                print(
                                    "\n   Use /sessions new to start a new session")
                            except Exception as e:
                                print(
                                    f"❌ Could not list sessions: {e}")
                    else:
                        print("❌ Context manager not available - agent_v2.py:2446")
                    continue

                elif cmd == "tasks":
                    if CONTEXT_MANAGER_AVAILABLE and agent.task_mgr:
                        print("\n📋 Task → Model Mappings: - agent_v2.py:2451")
                        try:
                            for task, model in agent.task_mgr.task_models.items():
                                print(
                                    f"{str(task).ljust(12)} → {model}")
                            print(
                                "\n   Tasks: embedding, coding, reasoning, chat, vision, creative, analysis")
                        except Exception as e:
                            print(
                                f"❌ Could not read task mappings: {e}")
                    else:
                        print("❌ Task manager not available - agent_v2.py:2462")
                    continue

                elif cmd == "scrape":
                    if not args:
                        print("❌ Usage: /scrape <url> - agent_v2.py:2467")
                    elif not WEB_TOOLS_AVAILABLE or not agent.web_scraper:
                        print("❌ Web scraper not available - agent_v2.py:2469")
                    else:
                        url = args[0]
                        print(f"🌐 Scraping: {url} - agent_v2.py:2472")
                        try:
                            if hasattr(agent.web_scraper, 'scrape_and_save'):
                                filepath, success = agent.web_scraper.scrape_and_save(
                                    url)
                            else:
                                content, filepath, success = agent.web_scraper.scrape_to_markdown(
                                    url)
                            if success:
                                print(
                                    f"✅ Saved to: {filepath}")
                                if agent.rag_manager:
                                    try:
                                        content_text = Path(filepath).read_text(
                                            encoding="utf-8")
                                        agent.rag_manager.store_document(
                                            content_text[:5000],
                                            metadata={
                                                "source": "web_content", "url": url}
                                        )
                                        print(
                                            "📚 Added to RAG memory")
                                    except Exception:
                                        pass
                            else:
                                print(
                                    f"❌ Error: {filepath}")
                        except Exception as e:
                            print(f"❌ Error: {e} - agent_v2.py:2500")
                    continue

                elif cmd in ("youtube", "yt"):
                    if not args:
                        print("❌ Usage: /youtube <url> - agent_v2.py:2505")
                        continue
                    if not WEB_TOOLS_AVAILABLE:
                        print("❌ YouTube tools not available - agent_v2.py:2508")
                        continue
                    url = args[0]
                    print(f"📺 Processing YouTube: {url} - agent_v2.py:2511")
                    try:
                        # Re-initialize the summarizer to clear old cache
                        from web_tools import YouTubeSummarizer
                        yt = YouTubeSummarizer(
                            output_dir=str(BASE_DIR / "exports"),
                            chroma_db_path=str(BASE_DIR / "chroma_db"),
                        )
                        summary = yt.get_video_summary(url)
                        if summary:
                            print(
                                f"\n📝 Summary:\n{summary}")
                            agent.conversation.add(
                                "user",
                                f"I just watched this YouTube video ({url}). Here is the summary:\n{summary}",
                            )
                            agent.conversation.add(
                                "assistant", "Got it. I've analyzed the video summary."
                            )
                            try:
                                yt.process_video(url)
                                print(
                                    "✅ Full transcript indexed and saved to knowledge base.")
                            except Exception:
                                pass
                        else:
                            print("❌ Could not generate summary. - agent_v2.py:2537")
                    except Exception as e:
                        print(f"❌ YouTube Error: {e} - agent_v2.py:2539")
                    continue

                elif cmd == "memory":
                    if not MCP_AVAILABLE or not agent.mcp or not getattr(agent.mcp, 'memory', None) or not getattr(agent.mcp.memory, 'available', False):
                        print("❌ Memory server not available - agent_v2.py:2544")
                        continue
                    if not args:
                        print("\n🧠 Memory Commands: - agent_v2.py:2547")
                        print(
                            "/memory show                Show knowledge graph stats")
                        print(
                            "/memory search <query>      Search entities")
                        print(
                            "/memory add <name> <type>   Add an entity")
                        print(
                            "/memory observe <name> <observation>  Add observation")
                        continue
                    subcmd = args[0].lower()
                    subargs = args[1:]
                    try:
                        if subcmd == "show":
                            graph = agent.mcp.memory.read_graph()
                            print(f"\n🧠 Knowledge Graph: - agent_v2.py:2562")
                            print(
                                f"Entities: {graph.get('entity_count', 0)}")
                            print(
                                f"Relations: {graph.get('relation_count', 0)}")
                            if graph.get("entities"):
                                print("\n  Entities: - agent_v2.py:2568")
                                for e in graph["entities"][:10]:
                                    print(
                                        f"• {e['name']} [{e['entity_type']}]  {len(e.get('observations', []))} observations")
                        elif subcmd == "search" and subargs:
                            mem_query = " ".join(subargs)
                            result = agent.mcp.memory.search_nodes(mem_query)
                            print(
                                f"\n🔍 Search results for '{mem_query}':")
                            for e in result.get("results", []):
                                print(
                                    f"• {e['name']} [{e['entity_type']}]")
                                for obs in e.get("observations", [])[:2]:
                                    print(f"{obs[:80]}... - agent_v2.py:2581")
                        elif subcmd == "add" and len(subargs) >= 2:
                            name = subargs[0]
                            entity_type = subargs[1]
                            agent.mcp.memory.create_entities(
                                [{"name": name, "entityType": entity_type,
                                    "observations": []}]
                            )
                            print(
                                f"✅ Created entity: {name} [{entity_type}]")
                        elif subcmd == "observe" and len(subargs) >= 2:
                            name = subargs[0]
                            observation = " ".join(subargs[1:])
                            agent.mcp.memory.add_observations(
                                [{"entityName": name, "contents": [observation]}]
                            )
                            print(
                                f"✅ Added observation to {name}")
                        else:
                            print(
                                "❌ Unknown memory command. Use /memory for help.")
                    except Exception as e:
                        print(
                            f"❌ Memory command failed: {e}")
                    continue

                elif cmd in ("github", "gh"):
                    if not MCP_AVAILABLE or not agent.mcp or not getattr(agent.mcp, 'github', None):
                        print("❌ GitHub MCP tools not available - agent_v2.py:2609")
                        continue
                    if not args:
                        print("\n🐙 GitHub Commands: - agent_v2.py:2612")
                        print(
                            "/github auth                Check GitHub authentication")
                        print(
                            "/github repos               List your repositories")
                        print(
                            "/github repo <owner/name>   Get repository details")
                        print(
                            "/github issues <owner/name> [state]  List issues (open/closed/all)")
                        print(
                            "/github prs <owner/name> [state]     List pull requests")
                        print(
                            "/github search <query>      Search code in GitHub")
                        continue
                    subcmd = args[0].lower()
                    subargs = args[1:]
                    try:
                        if subcmd == "auth":
                            print(
                                "🔑 Checking GitHub authentication...")
                            user = agent.mcp.github.get_user()
                            if "error" in user:
                                print(
                                    f"❌ Authentication failed: {user['error']}")
                                print(
                                    "\n💡 To fix: Generate a new Personal Access Token at:")
                                print(
                                    "https://github.com/settings/tokens")
                                print(
                                    "Then update GITHUB_TOKEN in mcp.json or .env")
                            else:
                                print(
                                    f"✅ Authenticated as: {user.get('login')}")
                                print(
                                    f"Name: {user.get('name', 'N/A')}")
                                print(
                                    f"Public repos: {user.get('public_repos', 0)}")
                        elif subcmd == "repos":
                            print("📦 Fetching repositories... - agent_v2.py:2650")
                            repos = agent.mcp.github.list_repos()
                            if isinstance(repos, dict) and "error" in repos:
                                print(f"❌ {repos['error']} - agent_v2.py:2653")
                            elif repos:
                                print(
                                    f"\n📦 Your Repositories ({len(repos)}):")
                                for repo in repos[:20]:
                                    stars = repo.get("stargazers_count", 0)
                                    lang = repo.get("language", "N/A")
                                    print(
                                        f"• {repo['full_name']} ⭐{stars} [{lang}]")
                                if len(repos) > 20:
                                    print(f"... and {len(repos)  20} more - agent_v2.py:2663")
                            else:
                                print(
                                    "❌ No repositories found or authentication failed")
                        elif subcmd == "repo" and subargs:
                            repo_name = subargs[0]
                            print(
                                f"📦 Fetching {repo_name}...")
                            repo = agent.mcp.github.get_repo(repo_name)
                            if "error" in repo:
                                print(f"❌ {repo['error']} - agent_v2.py:2673")
                            elif repo:
                                print(
                                    f"\n📦 {repo['full_name']}")
                                print(
                                    f"Description: {repo.get('description', 'N/A')}")
                                print(
                                    f"Language: {repo.get('language', 'N/A')}")
                                print(
                                    f"Stars: {repo.get('stargazers_count', 0)}")
                                print(
                                    f"Forks: {repo.get('forks_count', 0)}")
                                print(
                                    f"Open Issues: {repo.get('open_issues_count', 0)}")
                                print(
                                    f"URL: {repo.get('html_url', 'N/A')}")
                            else:
                                print(
                                    f"❌ Repository not found: {repo_name}")
                        elif subcmd == "issues" and subargs:
                            repo_name = subargs[0]
                            state = subargs[1] if len(subargs) > 1 else "open"
                            print(
                                f"📋 Fetching issues for {repo_name}...")
                            issues = agent.mcp.github.list_issues(
                                repo_name, state=state)
                            if issues:
                                print(
                                    f"\n📋 Issues ({state})  {len(issues)} found:")
                                for issue in issues[:15]:
                                    labels = ", ".join(
                                        [l["name"] for l in issue.get("labels", [])])
                                    print(
                                        f"#{issue['number']} {issue['title'][:60]}")
                                    if labels:
                                        print(
                                            f"Labels: {labels}")
                            else:
                                print(
                                    f"No {state} issues found")
                        elif subcmd == "prs" and subargs:
                            repo_name = subargs[0]
                            state = subargs[1] if len(subargs) > 1 else "open"
                            print(
                                f"🔀 Fetching PRs for {repo_name}...")
                            prs = agent.mcp.github.list_pull_requests(
                                repo_name, state=state)
                            if prs:
                                print(
                                    f"\n🔀 Pull Requests ({state})  {len(prs)} found:")
                                for pr in prs[:15]:
                                    print(
                                        f"#{pr['number']} {pr['title'][:60]}")
                                    print(
                                        f"By: {pr['user']['login']} | {pr['state']}")
                            else:
                                print(
                                    f"No {state} pull requests found")
                        elif subcmd == "search" and subargs:
                            gh_query = " ".join(subargs)
                            print(
                                f"🔍 Searching GitHub for: {gh_query}...")
                            results = agent.mcp.github.search_code(gh_query)
                            if results:
                                print(
                                    f"\n🔍 Search Results ({len(results)} found):")
                                for item in results[:10]:
                                    print(
                                        f"• {item['repository']['full_name']}/{item['name']}")
                                    print(
                                        f"{item['html_url']}")
                            else:
                                print("No results found - agent_v2.py:2745")
                        else:
                            print(
                                "❌ Unknown GitHub command. Use /github for help.")
                    except Exception as e:
                        print(
                            f"❌ GitHub command failed: {e}")
                    continue

                elif cmd == "docker":
                    print(
                        "\n🐳 Docker commands disabled  using native MCP servers")
                    print(
                        "Native tools available (no Docker required):")
                    print(
                        "• /mcp           Show all MCP tools status")
                    print(
                        "• /search_web    Web search via Brave API")
                    print("• /memory        Knowledge graph storage - agent_v2.py:2763")
                    print("• /github        GitHub API operations - agent_v2.py:2764")
                    continue

                elif cmd == "search":
                    if not args:
                        print("Usage: /search <query> - agent_v2.py:2769")
                    elif agent.rag:
                        query = " ".join(args)
                        hits = agent.rag.hybrid_search(query, k=10, final_k=5)
                        for i, h in enumerate(hits):
                            score = h.get('rerank_score', h.get('score', 0))
                            src = h.get('metadata', {}).get('source', '?')
                            print(
                                f"[{i+1}] ({score:.2f}) {src}")
                            print(
                                f"{h['content'][:150]}...")
                    else:
                        print("RAG not available - agent_v2.py:2781")
                    continue

                elif cmd == "run":
                    if not args:
                        print("Usage: /run <script.py> - agent_v2.py:2786")
                    else:
                        script = args[0]
                        print(f"Running: {script} - agent_v2.py:2789")
                        try:
                            r = subprocess.run(
                                [sys.executable, script] if script.endswith('.py') else [
                                    script],
                                capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR)
                            )
                            if r.stdout:
                                print(r.stdout[:4000])
                            if r.stderr:
                                print(
                                    f"STDERR:\n{r.stderr[:2000]}")
                            print(
                                f"[Exit code: {r.returncode}]")
                        except subprocess.TimeoutExpired:
                            print("Script timed out (300s) - agent_v2.py:2804")
                        except Exception as e:
                            print(f"Error: {e} - agent_v2.py:2806")
                    continue

                elif cmd == "skill":
                    if not agent.skill_manager:
                        print("Skill Manager not available - agent_v2.py:2811")
                    elif not args:
                        skills = agent.skill_manager.list_skills() if hasattr(
                            agent.skill_manager, 'list_skills') else []
                        print(
                            f"Available skills: {', '.join(skills) if skills else 'none'}")
                    else:
                        print(f"Skill set to: {args[0]} - agent_v2.py:2818")
                    continue

                elif cmd == "robin":
                    # Robin tool-calling loop: real tools, no narration.
                    # Usage: /robin <message>           — continue current task
                    #        /robin new <message>      — start a new task (clear history)
                    # Note: /tools is reserved for the Kali security tools list above.
                    if not args:
                        print(
                            "Usage: /robin <message>   |   /robin new <message>")
                        continue
                    new_task = False
                    if args[0].lower() == "new":
                        new_task = True
                        args = args[1:]
                    if not args:
                        print("Provide a message after 'new'. - agent_v2.py:2835")
                        continue
                    message = " ".join(args)
                    response = agent.process_tool_query(
                        message, new_task=new_task)
                    print(f"\n🦜 Robin:\n{response} - agent_v2.py:2840")
                    continue

                else:
                    print(f"Unknown command: /{cmd} - agent_v2.py:2844")
                    continue

            # Auto-detect URLs
            if user_input.startswith("http://") or user_input.startswith("https://"):
                if "youtube.com" in user_input or "youtu.be" in user_input:
                    if agent.youtube:
                        print(
                            "📺 YouTube URL detected  fetching transcript...")
                        result = agent.execute_web_command(
                            "youtube", [user_input])
                        print(result[:4000])
                        continue
                elif agent.web_scraper:
                    print("🌐 URL detected  scraping... - agent_v2.py:2858")
                    result = agent.execute_web_command("web", [user_input])
                    print(result[:4000])
                    continue

            # Auto-route operational requests to the Robin tool-calling loop.
            # Triggers on execution verbs or scheduling intent so things like
            # "start the pipeline" or "schedule a health check every 60s" get
            # real tool calls instead of narrated chat.
            if AGENT_TOOLS_AVAILABLE:
                _low = user_input.lower()
                _op_phrases = (
                    "run script", "run the script", "execute script",
                    "start background", "start the pipeline", "start pipeline",
                    "stop background", "kill background", "kill job",
                    "schedule a", "schedule interval", "schedule health",
                    "health check", "health-check",
                    "list jobs", "list scheduled", "remove scheduled",
                )
                if any(p in _low for p in _op_phrases):
                    print()
                    response = agent.process_tool_query(user_input)
                    print(f"\n🦜 Robin:\n{response} - agent_v2.py:2880")
                    continue

            # Process query
            print()
            response = await agent.process_query(user_input)
            # Wrap long lines for terminal display
            import textwrap
            terminal_width = shutil.get_terminal_size(
                fallback=(100, 24)).columns
            wrapped = []
            for line in response.splitlines():
                if len(line) > terminal_width:
                    wrapped.extend(textwrap.wrap(
                        line, width=terminal_width - 2) or [""])
                else:
                    wrapped.append(line)
            print(f"\n🤖 Assistant:\n - agent_v2.py:2897" + "\n".join(wrapped))

        except KeyboardInterrupt:
            if readline:
                readline.write_history_file(history_file)
            print("\n👋 Goodbye! - agent_v2.py:2902")
            break
        except EOFError:
            if readline:
                readline.write_history_file(history_file)
            print("\n👋 Goodbye! - agent_v2.py:2907")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ Error: {e} - agent_v2.py:2911")


if __name__ == "__main__":
    asyncio.run(main())
