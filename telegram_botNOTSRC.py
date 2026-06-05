#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  🤖 Local Larry - Telegram Bot Interface                                  ║
║  ═══════════════════════════════════════════════════════════════════════  ║
║  Enables conversations with local AI models via Telegram                  ║
║  Features: Multi-model routing, File browsing, MCP tools, RAG memory     ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime
from collections import deque
from typing import Dict, Deque, List, Optional, Tuple
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()

import requests

# ═══════════════════════════════════════════════════════════════════════════
# 🎨 TERMINAL COLORS & STYLING
# ═══════════════════════════════════════════════════════════════════════════

class Colors:
    """ANSI color codes for terminal output."""
    # Basic Colors
    BLACK = '\033[30m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    # Styles
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    
    # Background
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # Reset
    END = '\033[0m'
    
    @classmethod
    def gradient(cls, text: str, colors: list) -> str:
        """Apply gradient colors to text."""
        result = ""
        for i, char in enumerate(text):
            color = colors[i % len(colors)]
            result += f"{color}{char}"
        return result + cls.END


class Spinner:
    """Animated spinner for loading states."""
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    DOTS = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
    ARROWS = ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙']
    PULSE = ['█', '▓', '▒', '░', '▒', '▓']
    
    def __init__(self, message: str = "Loading", style: str = "dots"):
        self.message = message
        self.frames = getattr(self, style.upper(), self.DOTS)
        self.running = False
        self.thread = None
        self.idx = 0
    
    def spin(self):
        while self.running:
            frame = self.frames[self.idx % len(self.frames)]
            print(f"\r{Colors.CYAN}{frame}{Colors.END} {self.message}...", end="", flush=True)
            self.idx += 1
            time.sleep(0.1)
    
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()
    
    def stop(self, final_message: str = None):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        if final_message:
            print(f"\r{Colors.GREEN}✓{Colors.END} {final_message}" + " " * 20)
        else:
            print("\r" + " " * 50 + "\r", end="")


def print_banner():
    """Print stylish startup banner."""
    banner = (
        f"\n{Colors.CYAN}{Colors.BOLD}\n"
        r"  _                     _   _                          " + "\n"
        r" | |    ___   ___ __ _ | | | | __ _ _ __ _ __ _   _    " + "\n"
        r" | |   / _ \ / __/ _` || | | |/ _` | '__| '__| | | |   " + "\n"
        r" | |__| (_) | (_| (_| || | | | (_| | |  | |  | |_| |   " + "\n"
        r" |_____\___/ \___\__,_||_| |_|\__,_|_|  |_|   \__, |   " + "\n"
        r"                                              |___/    " + "\n"
        f"{Colors.END}"
    )
    banner = banner + f"""
{Colors.YELLOW}    ═══════════════════════════════════════════{Colors.END}
{Colors.WHITE}    ⚡ LARRY G-FORCE • TELEGRAM UPLINK ⚡{Colors.END}
{Colors.YELLOW}    ═══════════════════════════════════════════{Colors.END}
"""
    print(banner)


def print_section(title: str, icon: str = "📌"):
    """Print a styled section header."""
    line = "─" * (50 - len(title))
    print(f"\n{Colors.CYAN}{icon} {Colors.BOLD}{title}{Colors.END} {Colors.DIM}{line}{Colors.END}")


def print_status(message: str, status: str = "info"):
    """Print a styled status message."""
    icons = {
        "ok": f"{Colors.GREEN}✓{Colors.END}",
        "success": f"{Colors.GREEN}✓{Colors.END}",
        "fail": f"{Colors.RED}✗{Colors.END}",
        "error": f"{Colors.RED}✗{Colors.END}",
        "warn": f"{Colors.YELLOW}⚠{Colors.END}",
        "warning": f"{Colors.YELLOW}⚠{Colors.END}",
        "info": f"{Colors.BLUE}ℹ{Colors.END}",
        "run": f"{Colors.MAGENTA}▶{Colors.END}",
        "wait": f"{Colors.YELLOW}◌{Colors.END}",
    }
    icon = icons.get(status, icons["info"])
    print(f"  {icon} {message}")


# ═══════════════════════════════════════════════════════════════════════════
# 📦 IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
from dataclasses import dataclass, field

from model_router import ModelRouter, TaskType, get_router, list_models
from file_browser import FileBrowser, get_browser
from kali_tools import TOOLS, list_tools, tool_help, run_tool_background, parse_args_with_preset
from activity_stream import ActivityStream, report_status

# G-FORCE: EnhancedAgent + HW_PROFILES
try:
    from agent_v2 import EnhancedAgent, HW_PROFILES
    ENHANCED_AGENT_AVAILABLE = True
except ImportError:
    EnhancedAgent = None
    HW_PROFILES = {"SPEED": {"num_gpu": 0, "num_ctx": 16384}, "ACCURACY": {"num_gpu": 0, "num_ctx": 65536}}
    ENHANCED_AGENT_AVAILABLE = False

# Skill Manager
try:
    from skill_manager import get_skill_manager
    SKILL_MANAGER_AVAILABLE = True
except ImportError:
    get_skill_manager = None
    SKILL_MANAGER_AVAILABLE = False

# Optional imports with fallbacks
try:
    from context_manager import ContextManager, get_context_manager
    CONTEXT_MANAGER_AVAILABLE = True
except ImportError:
    CONTEXT_MANAGER_AVAILABLE = False

try:
    from mcp_client import MCPToolkit, get_mcp_toolkit
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Production RAG (preferred)
try:
    from production_rag import ProductionRAG, get_rag
    PRODUCTION_RAG_AVAILABLE = True
except ImportError:
    ProductionRAG = get_rag = None
    PRODUCTION_RAG_AVAILABLE = False

# Legacy RAG Memory
try:
    from rag_integration import RAGManager, get_rag_manager
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

# Voice Integration
try:
    from voice_module import VoiceManager, get_voice_manager
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

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

# Cross-Platform Paths
try:
    from cross_platform_paths import CrossPlatformPathManager
    CROSS_PLATFORM_PATHS_AVAILABLE = True
except ImportError:
    CrossPlatformPathManager = None
    CROSS_PLATFORM_PATHS_AVAILABLE = False

# Hardware Profile Manager
try:
    from hardware_profiles import ProfileManager, get_profile_manager
    PROFILE_MANAGER_AVAILABLE = True
except ImportError:
    ProfileManager = get_profile_manager = None
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

# Sandbox Manager
try:
    from sandbox_manager import SandboxManager, get_sandbox_manager
    SANDBOX_AVAILABLE = True
except ImportError:
    SandboxManager = get_sandbox_manager = None
    SANDBOX_AVAILABLE = False

# Web Tools
try:
    from web_tools import WebScraper, YouTubeSummarizer, get_web_scraper, get_youtube_summarizer
    WEB_TOOLS_AVAILABLE = True
except ImportError:
    WebScraper = YouTubeSummarizer = get_web_scraper = get_youtube_summarizer = None
    WEB_TOOLS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """Stores conversation context for a chat."""
    chat_id: int
    messages: List[Dict[str, str]] = field(default_factory=list)
    current_model: Optional[str] = None
    last_activity: datetime = field(default_factory=datetime.now)
    max_history: int = 20
    current_profile: str = "SPEED"
    current_skill: str = "DEFAULT"
    debug_mode: bool = False

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self.last_activity = datetime.now()
        if len(self.messages) > self.max_history * 2:
            self.messages = self.messages[-self.max_history:]

    def get_context_prompt(self) -> str:
        if not self.messages:
            return ""
        return "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in self.messages[-self.max_history:]
        ])

    def clear(self):
        self.messages = []


class TelegramBot:
    """Telegram Bot for AI conversations."""

    def __init__(self, bot_token: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")

        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.router = get_router()
        if self.router is None:
            # Last-resort fallback so the bot can still start
            class _FallbackRouter:
                available_models = ["llama3.2:3b"]
                current_model = "llama3.2:3b"
                def route_query(self, q): return ("llama3.2:3b", "chat", 8192)
                def detect_task(self, q): return "chat"
                def generate(self, prompt, **kw): return "Router not available right now."
                def set_model(self, m): return False
                def refresh_models(self): return []
            self.router = _FallbackRouter()
        self.conversations: Dict[int, ConversationContext] = {}
        self.last_update_id = 0
        self.running = False

        # Pending confirmations for dangerous actions (e.g. installing tools)
        self.pending_confirmations: Dict[int, dict] = {}  # chat_id -> {"action": "...", "tool": str|None, "ts": float}

        # === Custom Tuned Models (from personal_ai_training) ===
        self.custom_profiles = self._discover_custom_profiles()
        if self.custom_profiles:
            logger.info(f"✅ Discovered custom tuned profiles: {list(self.custom_profiles.keys())}")

        # Load telegram default model from larry_config.json
        self.default_model = None
        try:
            import json
            config_path = os.path.join(os.path.dirname(__file__), "larry_config.json")
            with open(config_path) as f:
                larry_cfg = json.load(f)
            self.default_model = larry_cfg.get("ollama", {}).get("telegram_default_model")
            if self.default_model:
                logger.info(f"Telegram default model from config: {self.default_model}")
        except Exception as e:
            logger.warning(f"Could not load larry_config.json: {e}")
        
        allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")
        self.allowed_chat_ids = self._parse_chat_ids(allowed) or None
        self.admin_chat_ids = self._parse_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", ""))
        self.allow_all = os.getenv("TELEGRAM_ALLOW_ALL", "false").lower() in ("true", "1", "yes", "on")
        
        self.commands = {
            "/start": self.cmd_start,
            "/help": self.cmd_help,
            "/models": self.cmd_models,
            "/model": self.cmd_set_model,
            "/fast": self.cmd_fast,
            "/clear": self.cmd_clear,
            "/status": self.cmd_status,
            "/task": self.cmd_task,
            "/ls": self.cmd_ls,
            "/cat": self.cmd_cat,
            "/cd": self.cmd_cd,
            "/edit": self.cmd_edit,
            "/run": self.cmd_run,
            "/find": self.cmd_find,
            "/grep": self.cmd_grep,
            "/rag": self.cmd_rag,
            "/index": self.cmd_index,
            "/search": self.cmd_search,
            "/voice": self.cmd_voice,
            "/speak": self.cmd_speak,
            "/kali": self.cmd_kali,
            "/tools": self.cmd_tools,
            "/install-tools": self.cmd_install_tools,
            "/install": self.cmd_install,
            "/nmap": self.cmd_nmap,
            "/nikto": self.cmd_nikto,
            "/whatweb": self.cmd_whatweb,
            "/whois": self.cmd_whois,
            "/dig": self.cmd_dig,
            "/enum4linux": self.cmd_enum4linux,
            # G-FORCE extended commands
            "/profile": self.cmd_profile,
            "/debug": self.cmd_debug,
            "/ragconfig": self.cmd_ragconfig,
            "/tokens": self.cmd_tokens,
            "/skill": self.cmd_skill,
            "/sandbox": self.cmd_sandbox,
            "/web": self.cmd_web,
            "/search_web": self.cmd_search_web,
            "/youtube": self.cmd_youtube,
            "/agent": self.cmd_agent,
            "/solve": self.cmd_agent,
            "/ports": self.cmd_ports,
            "/listeners": self.cmd_listeners,
            "/netscan": self.cmd_netscan,
            "/threats": self.cmd_threats,
            "/devices": self.cmd_devices,
            "/newdevices": self.cmd_newdevices,
            "/devicelog": self.cmd_devicelog,
            "/inbound": self.cmd_inbound,
            "/approve": self.cmd_approve,
            "/block": self.cmd_block,
        }

        # Initialize EnhancedAgent (G-FORCE core)
        self.agent = None
        if ENHANCED_AGENT_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.agent = EnhancedAgent(working_dir=base)
                logger.info("EnhancedAgent (G-FORCE) initialized")
            except Exception as e:
                logger.warning(f"EnhancedAgent init failed: {e}")

        # Skill Manager
        self.skill_manager = get_skill_manager() if SKILL_MANAGER_AVAILABLE else None

        # Initialize file browser
        self.file_browser = get_browser()

        # Production RAG (preferred over legacy)
        self.production_rag = None
        if PRODUCTION_RAG_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.production_rag = get_rag(
                    chroma_path=os.path.join(base, "chroma_db"),
                    use_reranker=True
                )
                logger.info("Production RAG initialized")
            except Exception as e:
                logger.warning(f"Production RAG init failed: {e}")

        # Profile Manager
        self.profile_manager = None
        if PROFILE_MANAGER_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.profile_manager = get_profile_manager(
                    db_path=os.path.join(base, "data", "unified_context.db")
                )
            except Exception:
                pass

        # Token Manager
        self.token_manager = TokenManager() if TOKEN_MANAGER_AVAILABLE else None

        # Rate limiting (per-chat deque-based token bucket)
        self.rate_limit_max = int(os.getenv("TELEGRAM_RATE_LIMIT_MAX", "12"))
        self.rate_limit_window = int(os.getenv("TELEGRAM_RATE_LIMIT_WINDOW", "60"))
        self._rate_limit: Dict[int, Deque[float]] = {}

        # Path sanitization base
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self.max_input_chars = 8000
        
        # Initialize context manager if available
        self.context_manager = None
        if CONTEXT_MANAGER_AVAILABLE:
            try:
                self.context_manager = get_context_manager(self.router)
            except Exception as e:
                logger.warning(f"Context manager init failed: {e}")
        
        # Initialize MCP toolkit if available
        self.mcp_toolkit = None
        if MCP_AVAILABLE:
            try:
                self.mcp_toolkit = get_mcp_toolkit()
            except Exception as e:
                logger.warning(f"MCP toolkit init failed: {e}")
        
        # Initialize RAG memory if available
        self.rag_manager = None
        if RAG_AVAILABLE:
            try:
                self.rag_manager = get_rag_manager()
                logger.info(f"✅ RAG memory initialized")
            except Exception as e:
                logger.warning(f"RAG manager init failed: {e}")
        
        # Initialize voice manager if available
        self.voice_manager = None
        if VOICE_AVAILABLE:
            try:
                self.voice_manager = get_voice_manager()
                logger.info(f"✅ Voice manager initialized")
            except Exception as e:
                logger.warning(f"Voice manager init failed: {e}")

        # Activity stream for dashboard
        self.activity = ActivityStream("telegram_bot")
        self.activity.emit(ActivityStream.SYSTEM, "Telegram bot initialized")
        report_status("telegram_bot", status="ONLINE", model=self.default_model)

    def _api_call(self, method: str, data: dict = None, timeout: int = 30, retries: int = 3) -> dict:
        """Make API call with retry logic."""
        last_error = None
        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self.base_url}/{method}", 
                    json=data, 
                    timeout=timeout + 10  # Add buffer to timeout
                )
                return response.json()
            except requests.exceptions.ReadTimeout:
                last_error = "Read timeout - Telegram API slow to respond"
                logger.warning(f"Timeout on {method} (attempt {attempt + 1}/{retries})")
                time.sleep(2 ** attempt)  # Exponential backoff
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error (attempt {attempt + 1}/{retries}): {e}")
                time.sleep(2 ** attempt)
            except Exception as e:
                last_error = str(e)
                logger.error(f"API call failed: {e}")
                break
        return {"ok": False, "error": last_error}

    def send_message(self, chat_id: int, text: str) -> dict:
        if len(text) > 4000:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for part in parts:
                self._api_call("sendMessage", {"chat_id": chat_id, "text": part})
                time.sleep(0.5)
            return {"ok": True}
        return self._api_call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_typing(self, chat_id: int):
        self._api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    def get_updates(self, offset: int = None, timeout: int = 30) -> List[dict]:
        data = {"timeout": timeout}
        if offset:
            data["offset"] = offset
        # Use longer request timeout for long polling
        result = self._api_call("getUpdates", data, timeout=timeout + 15, retries=2)
        return result.get("result", []) if result.get("ok") else []

    _MAX_CONVERSATIONS = 500

    def get_conversation(self, chat_id: int) -> ConversationContext:
        if chat_id not in self.conversations:
            # Evict oldest entry if at capacity
            if len(self.conversations) >= self._MAX_CONVERSATIONS:
                oldest = next(iter(self.conversations))
                del self.conversations[oldest]
            self.conversations[chat_id] = ConversationContext(chat_id=chat_id)
        return self.conversations[chat_id]

    def is_allowed(self, chat_id: int) -> bool:
        if self.allow_all:
            return True
        if self.is_admin(chat_id):
            return True
        return self.allowed_chat_ids is None or chat_id in self.allowed_chat_ids

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.admin_chat_ids

    @staticmethod
    def _parse_chat_ids(value: str) -> List[int]:
        result = []
        if not value:
            return result
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                logger.warning(f"Invalid chat id in env: {part}")
        return result

    def _parse_allowlist(self, value: str) -> List[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def cmd_start(self, chat_id: int, args: str) -> str:
        return """⚡ 𝗟𝗔𝗥𝗥𝗬 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗧𝗘𝗟𝗘𝗚𝗥𝗔𝗠 𝗨𝗣𝗟𝗜𝗡𝗞 ⚡
══════════════════════════════

🔥 Elite AI Operative Online.
🚀 Ready to execute.

💬 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐂𝐄𝐍𝐓𝐄𝐑
──────────────────────────────
/help      • Show this menu
/models    • List AI models 🤖
/model     • Switch model
/clear     • Clear history 🗑️
/status    • Show status 📊
/task      • Set task type

🎤 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/voice     • Voice status 🎭
/speak     • Generate voice 🔊
🎙️ Send voice messages for STT!

📁 𝐅𝐢𝐥𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/ls        • List directory
/cd        • Change directory
/cat       • Read file 📄
/edit      • Write to file ✏️
/find      • Find files 🔍
/grep      • Search in files

🧠 𝐑𝐀𝐆 𝐌𝐞𝐦𝐨𝐫𝐲
───────────────────────────────────
/rag       • Memory status 📊
/index     • Index directory 📁
/search    • Search memory 🔍

🔴 𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲 𝐓𝐨𝐨𝐥𝐬
───────────────────────────────────
/tools     • List all tools 🗡️
/kali      • Run any tool
/nmap      • Port scan
/nikto     • Web vuln scan
/whatweb   • Tech fingerprint
/whois     • Domain lookup
/dig       • DNS query
/enum4linux • SMB enum

🛠️ 𝐒𝐲𝐬𝐭𝐞𝐦 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/run       • Execute command 💻

⚡ 𝐆-𝐅𝐎𝐑𝐂𝐄 𝐄𝐱𝐭𝐞𝐧𝐝𝐞𝐝
───────────────────────────────────
/profile   • Hardware profiles ⚡
/skill     • Switch AI persona 🎭
/debug     • Toggle RAG debug 🔍
/ragconfig • RAG configuration
/tokens    • Token counter 🔢
/sandbox   • Safe file editing 🧰
/agent     • Autonomous mode 🤖
/web       • Scrape webpage 🌐
/search_web • Web search
/youtube   • YouTube transcript 📺

🛡️ 𝐍𝐞𝐭𝐰𝐨𝐫𝐤 𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲
───────────────────────────────────
/ports     • Open ports scan
/listeners • Listening services
/netscan   • Network summary
/threats   • Threat detection
/devices   • Network devices
/newdevices • New device alerts

✨ Just send a message or voice to start chatting!"""

    def cmd_help(self, chat_id: int, args: str) -> str:
        return self.cmd_start(chat_id, args)

    def cmd_models(self, chat_id: int, args: str) -> str:
        models = self.get_available_models()
        if not models:
            return "❌ No models available.\n\n💡 Is Ollama running?"

        output = ["⚡ 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗠𝗢𝗗𝗘𝗟 𝗔𝗥𝗦𝗘𝗡𝗔𝗟 (Untamed)\n══════════════════════════════"]

        # Stock models
        stock = [m for m in models if not m.startswith("larry-")]
        for i, model in enumerate(stock[:10], 1):
            icon = "🔵" if "llama" in model.lower() else "🟢" if "code" in model.lower() or "qwen" in model.lower() else "⚪"
            output.append(f"{icon} {model}")

        # Custom tuned profiles (the good stuff)
        if self.custom_profiles:
            output.append("\n🔥 𝗖𝗨𝗦𝗧𝗢𝗠 𝗧𝗨𝗡𝗘𝗗 𝗣𝗥𝗢𝗙𝗜𝗟𝗘𝗦")
            for name, full_model in self.custom_profiles.items():
                output.append(f"  ✨ /profile {name}  →  {full_model}")

        output.append("\n💡 /fast (recommended)   /model <name>   /profile ...")
        return "\n".join(output)

    def cmd_set_model(self, chat_id: int, args: str) -> str:
        if not args:
            conv = self.get_conversation(chat_id)
            current = conv.current_model or "auto (routed)"
            return f"Current model: {current}\n\nUsage: /model <name or larry-xxx>"
        model = args.strip()
        if self.router.set_model(model):
            self.get_conversation(chat_id).current_model = model
            return f"✅ Switched to: `{model}`"
        # Try custom profile short name
        if model.lower() in self.custom_profiles:
            full = self.custom_profiles[model.lower()]
            self.get_conversation(chat_id).current_model = full
            return f"✅ Switched to custom profile: **{model}** (`{full}`)"
        return f"❌ Model '{model}' not found. Use /models"

    def cmd_fast(self, chat_id: int, args: str) -> str:
        """One-tap switch to the fastest reliable model for RTX 4060 8GB."""
        FAST = ["llama3.2:3b", "dolphin-mistral:latest", "qwen3:8b", "dolphincoder:latest"]
        self.router.refresh_models()
        chosen = next((m for m in FAST if m in self.router.available_models), None)
        if not chosen:
            return "❌ No fast models found. Run: ollama pull llama3.2:3b"
        if self.router.set_model(chosen):
            self.get_conversation(chat_id).current_model = chosen
            return f"⚡ FAST MODE → {chosen}\n\nRecommended for responsive Telegram on your 8GB GPU."
        return f"❌ Could not activate {chosen}"

    def cmd_clear(self, chat_id: int, args: str) -> str:
        self.get_conversation(chat_id).clear()
        return "🗑️ History cleared."

    def cmd_status(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        model = conv.current_model or "auto-routing"
        
        # Get context stats if available
        context_info = ""
        if self.context_manager:
            try:
                stats = self.context_manager.get_stats()
                context_info = f"\n🧠 Context   │ {stats.get('token_count', 0)} tokens"
            except:
                pass
        
        # Get voice stats if available
        voice_info = ""
        if self.voice_manager:
            try:
                vstats = self.voice_manager.get_status()
                if vstats.get('stt_available'):
                    voice_info += f"\n🎤 STT      │ ✅ {vstats.get('stt_model', 'N/A')}"
                if vstats.get('tts_available'):
                    voice_info += f"\n🔊 TTS      │ ✅ {vstats.get('tts_engine', 'N/A')}"
                    if vstats.get('voice_cloning'):
                        voice_info += " (Batman)"
            except:
                pass
        
        return f"""📊 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗦𝗧𝗔𝗧𝗨𝗦
══════════════════════════════
🤖 Model     │ {model}
💬 Messages  │ {len(conv.messages)}
🔧 Available │ {len(self.router.available_models)} models
📁 Directory │ {self.file_browser.current_dir}{context_info}{voice_info}
══════════════════════════════
✅ Bot is running"""

    def cmd_task(self, chat_id: int, args: str) -> str:
        valid = [t.value for t in TaskType]
        if not args or args.strip().lower() not in valid:
            return f"Usage: /task <type>\nTypes: {', '.join(valid)}"
        task = TaskType(args.strip().lower())
        model, _ = self.router.get_model_for_task(task)
        self.get_conversation(chat_id).current_model = model
        return f"✅ Task: {task.value}\n🤖 Model: {model}"

    def cmd_ls(self, chat_id: int, args: str) -> str:
        try:
            return self.file_browser.ls(args.strip() if args else ".")
        except Exception as e:
            return f"❌ Error listing directory: {e}"

    def cmd_cat(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /cat <filepath>"
        try:
            return self.file_browser.read(args.strip())
        except Exception as e:
            return f"❌ Error reading file: {e}"

    def cmd_cd(self, chat_id: int, args: str) -> str:
        if not args:
            return f"📂 Current: {self.file_browser.pwd()}"
        try:
            result = self.file_browser.cd(args.strip())
            return result
        except Exception as e:
            return f"❌ Error changing directory: {e}"

    def cmd_edit(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /edit <filepath> <content>"
        try:
            parts = args.split(" ", 1)
            if len(parts) < 2:
                return "Usage: /edit <filepath> <content>"
            file_path, content = parts
            result = self.file_browser.write(file_path.strip(), content)
            return result
        except Exception as e:
            return f"❌ Error editing file: {e}"

    def cmd_run(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /run <command>"
        if not MCP_AVAILABLE or not self.mcp_toolkit:
            # Fallback to subprocess — shell=False to prevent injection
            try:
                import subprocess, shlex
                cmd_parts = shlex.split(args)
                if not cmd_parts:
                    return "❌ Empty command"
                result = subprocess.run(
                    cmd_parts, shell=False, capture_output=True, text=True, timeout=30
                )
                output = result.stdout or result.stderr or "(no output)"
                return f"📋 Output:\n{output[:3000]}"
            except subprocess.TimeoutExpired:
                return "❌ Command timed out (30s limit)"
            except Exception as e:
                return f"❌ Error: {e}"
        try:
            return self.mcp_toolkit.execute(args)
        except Exception as e:
            return f"❌ Error running command: {e}"

    def cmd_find(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /find <pattern> [path]"
        try:
            parts = args.split(" ", 1)
            pattern = parts[0]
            path = parts[1] if len(parts) > 1 else "."
            return self.file_browser.find(pattern, path)
        except Exception as e:
            return f"❌ Error finding files: {e}"

    def cmd_grep(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /grep <pattern> <path>"
        try:
            parts = args.split(" ", 1)
            if len(parts) < 2:
                return "Usage: /grep <pattern> <path>"
            pattern, path = parts
            return self.file_browser.grep(pattern.strip(), path.strip())
        except Exception as e:
            return f"❌ Error grepping files: {e}"
    
    def cmd_rag(self, chat_id: int, args: str) -> str:
        """Show RAG memory status and stats."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        try:
            stats = self.rag_manager.get_stats()
            if stats['status'] != 'active':
                return f"⚠️ RAG Status: {stats['status']}"
            
            output = ["🧠 𝗥𝗔𝗚 𝗠𝗲𝗺𝗼𝗿𝘆 𝗦𝘁𝗮𝘁𝘂𝘀", "══════════════════════════════"]
            
            for name, count in stats.get('collections', {}).items():
                icon = "📚" if count > 0 else "📭"
                output.append(f"{icon} {name}: {count}")
            
            output.append(f"\n📊 Total: {stats.get('total_documents', 0)} documents")
            output.append("\n💡 Commands: /index <dir>, /search <query>")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error getting RAG stats: {e}"
    
    def cmd_index(self, chat_id: int, args: str) -> str:
        """Index a directory into RAG memory."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        directory = args.strip() if args else "."
        
        try:
            result = self.rag_manager.index_directory(directory)
            count = result.get('indexed_count', 0)
            errors = result.get('errors', [])
            
            output = [f"📁 Indexed {count} files from {directory}"]
            if errors:
                output.append(f"⚠️ {len(errors)} errors occurred")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error indexing: {e}"
    
    def cmd_search(self, chat_id: int, args: str) -> str:
        """Search RAG memory."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        if not args:
            return "Usage: /search <query>"
        
        try:
            context = self.rag_manager.get_relevant_context(args, max_results=2)
            if not context:
                return "🔍 No relevant results found"
            
            # Truncate for Telegram
            if len(context) > 3000:
                context = context[:3000] + "\n\n... (truncated)"
            
            return f"🔍 𝗦𝗲𝗮𝗿𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁𝘀\n══════════════════════════════\n{context}"
        except Exception as e:
            return f"❌ Error searching: {e}"
    
    def cmd_voice(self, chat_id: int, args: str) -> str:
        """Show voice module status."""
        if not self.voice_manager:
            return "❌ Voice module not available"
        
        try:
            status = self.voice_manager.get_status()
            output = ["🎤 𝗩𝗼𝗶𝗰𝗲 𝗠𝗼𝗱𝘂𝗹𝗲 𝗦𝘁𝗮𝘁𝘂𝘀", "══════════════════════════════"]
            
            output.append(f"🗣️ STT: {'✅' if status['stt_available'] else '❌'} {status.get('stt_model', 'N/A')}")
            output.append(f"🔊 TTS: {'✅' if status['tts_available'] else '❌'} {status.get('tts_engine', 'N/A')}")
            output.append(f"🎭 Voice Cloning: {'✅' if status.get('voice_cloning') else '❌'}")
            output.append(f"📁 Voice Sample: {'✅' if status.get('voice_sample') else '❌'}")
            
            tasks = status.get('voice_tasks', [])
            output.append(f"🎯 Voice Tasks: {', '.join(tasks) if tasks else 'None'}")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error getting voice status: {e}"
    
    def cmd_speak(self, chat_id: int, args: str) -> str:
        """Generate voice response for text."""
        if not self.voice_manager:
            return "❌ Voice module not available"
        
        if not args:
            return "Usage: /speak <text to speak>"
        
        try:
            # Generate voice
            audio_path = self.voice_manager.speak(args)
            
            # Send the audio file
            self.send_voice(chat_id, audio_path, caption=f"🎭 \"{args[:50]}{'...' if len(args) > 50 else ''}\"")
            
            return f"🎤 Voice generated and sent!"
        except Exception as e:
            return f"❌ Error generating voice: {e}"

    # ── Kali / Security commands ──────────────────────────────────────────

    def _run_tool_async(self, chat_id: int, tool_name: str, raw_args: str):
        """Run a tool in background and send result back to Telegram."""
        tool_obj = TOOLS.get(tool_name)
        if not tool_obj:
            self.send_message(chat_id, f"Unknown tool: {tool_name}")
            return

        expanded = parse_args_with_preset(tool_obj, raw_args)
        if expanded.startswith("__ERROR__"):
            self.send_message(chat_id, expanded[9:])
            return

        self.send_message(chat_id, f"Running: {tool_obj.cmd} {expanded}\nTimeout: {tool_obj.default_timeout}s ...")
        self.send_typing(chat_id)

        def on_done(success, output):
            header = f"[{tool_obj.cmd}] {'Done' if success else 'Finished'}\n{'=' * 30}\n"
            self.send_message(chat_id, header + output)

        run_tool_background(tool_name, expanded, callback=on_done, max_output=3500)

    def cmd_tools(self, chat_id: int, args: str) -> str:
        cat = args.strip() or None
        result = list_tools(cat)
        return result[:4000]

    def cmd_install_tools(self, chat_id: int, args: str) -> str:
        """Install all feasible missing security tools using winget/choco.
        Now available to anyone in TELEGRAM_ALLOWED_CHAT_IDS.
        Requires explicit YES confirmation before running installers.
        """
        if not self.is_allowed(chat_id):
            return "⛔ Access denied."

        # Clear any old confirmation
        if chat_id in self.pending_confirmations:
            del self.pending_confirmations[chat_id]

        try:
            import security_tools_installer
            missing = security_tools_installer.get_missing_security_tools()
            if not missing:
                return "✅ All security tools are already installed!"

            report = security_tools_installer.get_install_status_report()

            # Set up confirmation
            self.pending_confirmations[chat_id] = {
                "action": "install_tools",
                "tool": None,
                "ts": time.time()
            }

            return (
                f"{report}\n\n"
                f"⚠️ **Confirmation Required**\n"
                f"This will use winget/choco (or pip) to install missing tools on the host machine.\n\n"
                f"Reply with **YES** to proceed or **NO** to cancel."
            )[:3800]
        except Exception as e:
            return f"Installer error: {e}"

    def cmd_install(self, chat_id: int, args: str) -> str:
        """Install one specific tool: /install nmap
        Now available to anyone in TELEGRAM_ALLOWED_CHAT_IDS.
        Requires explicit YES confirmation.
        """
        if not self.is_allowed(chat_id):
            return "⛔ Access denied."

        if not args:
            return "Usage: /install <tool>   (e.g. /install nmap gobuster sqlmap)"

        tool = args.split()[0].lower().strip()

        # Clear old confirmation
        if chat_id in self.pending_confirmations:
            del self.pending_confirmations[chat_id]

        try:
            import security_tools_installer

            # Set up confirmation (installer will handle "already installed" case gracefully)
            self.pending_confirmations[chat_id] = {
                "action": "install",
                "tool": tool,
                "ts": time.time()
            }

            return (
                f"⚠️ **Confirmation Required**\n"
                f"About to attempt installation for: **{tool}**\n\n"
                f"Reply with **YES** to proceed or **NO** to cancel."
            )
        except Exception as e:
            return f"Install preparation error: {e}"

    def cmd_kali(self, chat_id: int, args: str) -> str:
        if not args:
            return ("Security Tools\n"
                    "/kali list [category]   — list tools + status\n"
                    "/kali help <tool>       — show presets\n"
                    "/kali <tool> [args]     — run tool\n\n"
                    "Installer:\n"
                    "  /install-tools         — install missing tools (requires YES confirm)\n"
                    "  /install <tool>        — install one tool (requires YES confirm)\n"
                    "  Available to anyone allowed in .env\n"
                    "Shortcuts: /nmap /gobuster /sqlmap /whois")
        parts = args.split(None, 1)
        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "list":
            return list_tools(rest.strip() or None)[:4000]
        if sub == "help":
            return tool_help(rest.strip())
        # /kali <tool> [args]
        self._run_tool_async(chat_id, sub, rest)
        return ""  # response sent by callback

    def cmd_nmap(self, chat_id: int, args: str) -> str:
        if not args:
            return ("Usage: /nmap <target> [flags]\n"
                    "Presets: /nmap :quick <ip>  /nmap :service <ip>\n"
                    "         /nmap :full <ip>   /nmap :vuln <ip>\n"
                    "         /nmap :stealth <ip>")
        self._run_tool_async(chat_id, "nmap", args)
        return ""

    def cmd_nikto(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /nikto -h <target>\nPresets: /nikto :basic <url>  /nikto :fast <url>"
        self._run_tool_async(chat_id, "nikto", args)
        return ""

    def cmd_whatweb(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /whatweb <url>\nPresets: /whatweb :aggro <url>"
        self._run_tool_async(chat_id, "whatweb", args)
        return ""

    def cmd_whois(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /whois <domain or IP>"
        self._run_tool_async(chat_id, "whois", args)
        return ""

    def cmd_dig(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /dig <domain> [type]\nPresets: /dig :any <domain>  /dig :axfr <domain>"
        self._run_tool_async(chat_id, "dig", args)
        return ""

    def cmd_enum4linux(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /enum4linux <target>\nPresets: /enum4linux :all <ip>"
        self._run_tool_async(chat_id, "enum4linux", args)
        return ""

    # ═══════════════════════════════════════════════════════════════════════
    # G-FORCE EXTENDED COMMANDS
    # ═══════════════════════════════════════════════════════════════════════

    def _sanitize_path(self, path: str) -> str:
        """Prevent directory traversal attacks."""
        resolved = os.path.realpath(os.path.join(self._base_dir, path))
        if not resolved.startswith(self._base_dir):
            return None
        return resolved

    def _rate_limited(self, chat_id: int) -> bool:
        """Per-chat deque-based token bucket rate limiting."""
        now = time.time()
        bucket = self._rate_limit.setdefault(chat_id, deque())
        while bucket and now - bucket[0] > self.rate_limit_window:
            bucket.popleft()
        if len(bucket) >= self.rate_limit_max:
            return True
        bucket.append(now)
        return False

    def _estimate_tokens(self, text: str) -> int:
        if self.token_manager:
            return self.token_manager.count(text)
        return len(text) // 4

    def cmd_profile(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        if not args:
            info = f"Current: {conv.current_profile}\nHardware: {', '.join(HW_PROFILES.keys())}"
            if self.custom_profiles:
                info += f"\n\n🔥 Custom Tuned Models:\n" + "\n".join(f"  • {k}" for k in self.custom_profiles.keys())
            return f"⚡ G-Force Profile\n{info}\n\nUsage: /profile precise | agentic | deepthink | fast"

        name = args.strip().lower()

        # Custom tuned model profiles (the powerful ones)
        if name in self.custom_profiles:
            full_model = self.custom_profiles[name]
            conv.current_model = full_model
            conv.current_profile = name.upper()
            return f"🔥 Switched to **{name.upper()}** profile\nModel: `{full_model}`\n\nThis is one of your custom tuned models."

        # Hardware profiles
        if name.upper() in HW_PROFILES:
            conv.current_profile = name.upper()
            if self.profile_manager:
                try:
                    self.profile_manager.set_profile(name.upper())
                except Exception:
                    pass
            return f"✅ Hardware profile: {name.upper()}"
        return "Unknown. Try: precise, agentic, deepthink, fast  or  SPEED / ACCURACY / ULTRA_CONTEXT"

    def cmd_debug(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        conv.debug_mode = not conv.debug_mode
        return f"🔍 Debug mode: {'ON' if conv.debug_mode else 'OFF'}\nRAG verification will be {'shown' if conv.debug_mode else 'hidden'} in responses."

    def cmd_ragconfig(self, chat_id: int, args: str) -> str:
        parts = ["📊 RAG Configuration\n"]
        if self.production_rag:
            stats = self.production_rag.get_stats()
            parts.append(f"Backend: Production RAG")
            parts.append(f"Status: {stats.get('status', '?')}")
            parts.append(f"Reranker: {stats.get('reranker', '?')}")
            for name, count in stats.get("collections", {}).items():
                parts.append(f"  {name}: {count} docs")
        elif self.rag_manager:
            stats = self.rag_manager.get_stats()
            parts.append(f"Backend: Legacy RAG")
            parts.append(f"Total: {stats.get('total_documents', '?')} docs")
        else:
            parts.append("RAG: Not available")
        return "\n".join(parts)

    def cmd_tokens(self, chat_id: int, args: str) -> str:
        if args:
            count = self._estimate_tokens(args)
            return f"🔢 Tokens in text: {count:,}"
        conv = self.get_conversation(chat_id)
        total = sum(self._estimate_tokens(m['content']) for m in conv.messages)
        return f"🔢 Conversation tokens: {total:,} ({len(conv.messages)} messages)"

    def cmd_skill(self, chat_id: int, args: str) -> str:
        if not self.skill_manager:
            return "⚠️ Skill Manager not available"
        conv = self.get_conversation(chat_id)
        if not args:
            skills = self.skill_manager.list_skills() if hasattr(self.skill_manager, 'list_skills') else []
            return f"🎯 Current: {conv.current_skill}\nAvailable: {', '.join(skills) if skills else 'DEFAULT'}"
        conv.current_skill = args.strip().upper()
        return f"✅ Skill set to: {conv.current_skill}"

    def cmd_sandbox(self, chat_id: int, args: str) -> str:
        if not self.agent or not self.agent.sandbox:
            return "⚠️ Sandbox Manager not available"
        if not args:
            return ("🧰 Sandbox Commands:\n"
                    "/sandbox stage <file> — Stage file\n"
                    "/sandbox edit <file> <content> — Edit\n"
                    "/sandbox test <file> — Test changes\n"
                    "/sandbox deploy <file> — Deploy\n"
                    "/sandbox rollback <file> — Rollback\n"
                    "/sandbox status — Show staged")
        parts = args.split(None, 2)
        sub = parts[0].lower()
        if sub == "stage" and len(parts) > 1:
            safe = self._sanitize_path(parts[1])
            if not safe:
                return "⚠️ Path outside allowed directory."
            return self.agent.sandbox_stage_file(safe)
        elif sub == "edit" and len(parts) > 2:
            safe = self._sanitize_path(parts[1])
            if not safe:
                return "⚠️ Path outside allowed directory."
            return self.agent.sandbox_edit_file(safe, parts[2])
        elif sub == "test" and len(parts) > 1:
            return self.agent.sandbox_test_changes(parts[1])
        elif sub == "deploy" and len(parts) > 1:
            return self.agent.sandbox_deploy(parts[1])
        elif sub == "rollback" and len(parts) > 1:
            return self.agent.sandbox_rollback(parts[1])
        elif sub == "status":
            return self.agent.get_sandbox_status()
        return "Usage: /sandbox <stage|edit|test|deploy|rollback|status> [args]"

    def cmd_web(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /web <url>"
        if self.agent:
            return self.agent.execute_web_command("web", args.split())
        return "⚠️ Web tools not available"

    def cmd_search_web(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /search_web <query>"
        if self.agent:
            return self.agent.execute_web_command("search_web", args.split())
        return "⚠️ Web search not available"

    def cmd_youtube(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /youtube <url> [summarize]"
        if self.agent:
            return self.agent.execute_web_command("youtube", args.split())
        return "⚠️ YouTube tools not available"

    def cmd_agent(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /agent <task description>\nRuns autonomous multi-step task solving."
        if not self.agent:
            return "⚠️ EnhancedAgent not available"

        self.send_typing(chat_id)
        task = args.strip()

        def _run_agentic():
            import asyncio
            loop = asyncio.new_event_loop()
            def _feedback(msg):
                self.send_message(chat_id, f"🤖 {msg}")
            try:
                result = loop.run_until_complete(
                    self.agent.process_query_agentic(task, feedback_cb=_feedback)
                )
                self.send_message(chat_id, f"🤖 Agent Result:\n{result[:4000]}")
            except Exception as e:
                self.send_message(chat_id, f"❌ Agent error: {e}")
            finally:
                loop.close()

        t = threading.Thread(target=_run_agentic, daemon=True)
        t.start()
        return f"🤖 Agent started: {task[:80]}...\nProgress updates will follow."

    # ── Network Security Commands ─────────────────────────────────────
    def cmd_ports(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            ports = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    port = conn.laddr.port
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    risk = "🔴" if port < 1024 and port not in (22, 53, 80, 443) else "🟢"
                    ports.append(f"{risk} :{port} — {name} (PID {pid})")
            if not ports:
                return "🟢 No listening ports"
            return "🔍 Open Ports:\n" + "\n".join(ports[:30])
        except Exception as e:
            return f"❌ Port scan failed: {e}"

    def cmd_listeners(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            listeners = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    addr = f"{conn.laddr.ip}:{conn.laddr.port}"
                    listeners.append(f"  {addr:25s} {name} (PID {pid})")
            return "📡 Listening Services:\n" + "\n".join(listeners[:30]) if listeners else "No listeners found."
        except Exception as e:
            return f"❌ {e}"

    def cmd_netscan(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            conns = psutil.net_connections(kind="inet")
            listen = len([c for c in conns if c.status == "LISTEN"])
            estab = len([c for c in conns if c.status == "ESTABLISHED"])
            total = len(conns)
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory().percent
            return (f"📊 Network Summary\n"
                    f"Total connections: {total}\n"
                    f"Listening: {listen}\n"
                    f"Established: {estab}\n"
                    f"CPU: {cpu:.0f}% | MEM: {mem:.0f}%")
        except Exception as e:
            return f"❌ {e}"

    def cmd_threats(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            threats = []
            for proc in psutil.process_iter(["pid", "name", "connections", "cpu_percent"]):
                try:
                    info = proc.info
                    cpu = info.get("cpu_percent", 0) or 0
                    if cpu > 80:
                        threats.append(f"⚠️ High CPU: {info['name']} (PID {info['pid']}) at {cpu:.0f}%")
                except Exception:
                    pass
            # Check for unusual outbound connections
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr:
                    rport = conn.raddr.port
                    if rport in (4444, 5555, 6666, 6667, 31337):
                        threats.append(f"🔴 Suspicious port: :{rport} → {conn.raddr.ip}")
            if not threats:
                return "🟢 No threats detected"
            return "🚨 Threat Detection:\n" + "\n".join(threats[:20])
        except Exception as e:
            return f"❌ {e}"

    def cmd_devices(self, chat_id: int, args: str) -> str:
        if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
            try:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    return str(self.agent.mcp.network_monitor.get_devices())[:4000]
            except Exception:
                pass
        # Fallback: ARP table
        try:
            import subprocess
            r = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
            return f"📡 Network Devices (ARP):\n{r.stdout[:3000]}"
        except Exception as e:
            return f"❌ {e}"

    def cmd_newdevices(self, chat_id: int, args: str) -> str:
        if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
            try:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    return str(self.agent.mcp.network_monitor.get_new_devices())[:4000]
            except Exception:
                pass
        return "⚠️ Device tracking requires network_monitor (MCP toolkit)"

    def cmd_inbound(self, chat_id: int, args: str) -> str:
        """Show current inbound connections."""
        try:
            self.send_typing(chat_id)
            # Try MCP network_monitor first
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.get_inbound_connections()
                    if result.get('success'):
                        conns = result.get('connections', [])
                        if not conns:
                            return "✅ No inbound connections detected"
                        output = ["📥 *INBOUND CONNECTIONS*\n━━━━━━━━━━━━━━"]
                        for c in conns[:15]:
                            remote = c.get('remote_address', '?')
                            local_port = c.get('local_port', '?')
                            proc = c.get('process_name', 'unknown')[:15]
                            output.append(f"• `{remote}` → :{local_port} ({proc})")
                        if len(conns) > 15:
                            output.append(f"\n_...and {len(conns)-15} more_")
                        return "\n".join(output)
                    return f"❌ {result.get('error', 'Failed to get connections')}"
            # Fallback: psutil-based inbound detection
            import psutil
            inbound = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr and conn.laddr:
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    inbound.append(f"• `{conn.raddr.ip}:{conn.raddr.port}` → :{conn.laddr.port} ({name})")
            if not inbound:
                return "✅ No inbound connections detected"
            return "📥 *INBOUND CONNECTIONS*\n━━━━━━━━━━━━━━\n" + "\n".join(inbound[:20])
        except Exception as e:
            return f"❌ Error getting inbound connections: {e}"

    def cmd_devicelog(self, chat_id: int, args: str) -> str:
        """Show device activity log."""
        try:
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    lines = int(args) if args and args.strip().isdigit() else 20
                    result = self.agent.mcp.network_monitor.get_device_log(lines=lines)
                    entries = result.get('entries', [])
                    if not entries:
                        return "📋 No device activity logged yet"
                    output = ["📋 *DEVICE ACTIVITY LOG*\n━━━━━━━━━━━━━━"]
                    output.append(f"Showing {len(entries)} of {result.get('total_entries', 0)} entries\n")
                    for entry in entries[-15:]:
                        if "NEW_DEVICE" in entry:
                            output.append(f"🆕 {entry}")
                        elif "BLOCKED" in entry:
                            output.append(f"🚫 {entry}")
                        elif "APPROVED" in entry:
                            output.append(f"✅ {entry}")
                        elif "IP_CHANGED" in entry:
                            output.append(f"🔄 {entry}")
                        else:
                            output.append(f"• {entry}")
                    return "\n".join(output)
            return "❌ Device log requires network_monitor (MCP toolkit)"
        except Exception as e:
            return f"❌ Error getting device log: {e}"

    def cmd_approve(self, chat_id: int, args: str) -> str:
        """Approve a device by MAC address."""
        try:
            if not args:
                return "Usage: `/approve <MAC> [name]`\nExample: `/approve AA-BB-CC-DD-EE-FF MyPhone`"
            if not self.is_admin(chat_id):
                return "⛔ Admin access required for device approval"
            parts = args.split(maxsplit=1)
            mac = parts[0].upper()
            name = parts[1] if len(parts) > 1 else ""
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.approve_device(mac=mac, name=name)
                    if result.get('success'):
                        return f"✅ *Device Approved*\nMAC: `{result.get('mac')}`\nName: `{result.get('name')}`"
                    return f"❌ {result.get('error', 'Failed to approve device')}"
            return "❌ Network monitor not available"
        except Exception as e:
            return f"❌ Error approving device: {e}"

    def cmd_block(self, chat_id: int, args: str) -> str:
        """Block a device by MAC address."""
        try:
            if not args:
                return "Usage: `/block <MAC> [reason]`\nExample: `/block AA-BB-CC-DD-EE-FF Suspicious device`"
            if not self.is_admin(chat_id):
                return "⛔ Admin access required for device blocking"
            parts = args.split(maxsplit=1)
            mac = parts[0].upper()
            reason = parts[1] if len(parts) > 1 else "Manual block"
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.block_device(mac=mac, reason=reason)
                    if result.get('success'):
                        return f"🚫 *Device Blocked*\nMAC: `{result.get('mac')}`\nReason: `{result.get('reason')}`"
                    return f"❌ {result.get('error', 'Failed to block device')}"
            return "❌ Network monitor not available"
        except Exception as e:
            return f"❌ Error blocking device: {e}"

    # ═══════════════════════════════════════════════════════════════════════
    # MESSAGE PROCESSING
    # ═══════════════════════════════════════════════════════════════════════

    def process_message(self, chat_id: int, text: str) -> str:
        self.activity.emit(ActivityStream.QUERY_RECEIVED, f"TG msg: {text[:80]}", {"chat_id": chat_id})
        conv = self.get_conversation(chat_id)
        conv.add_message("user", text)

        # Also track in context manager if available
        session_id = f"telegram_{chat_id}"
        if self.context_manager:
            try:
                self.context_manager.add_message("user", text, session_id)
            except Exception as e:
                logger.debug(f"Context manager add failed: {e}")

        model = conv.current_model
        if not model:
            if self.default_model and self.default_model in self.router.available_models:
                model = self.default_model
                logger.info(f"Using telegram default model: {model}")
            else:
                model, task, _ = self.router.route_query(text)
                logger.info(f"Routed to {model} for {task.value}")
        self.activity.emit(ActivityStream.MODEL_SELECTED, f"Model: {model}", {"model": model})
        report_status("telegram_bot", status="GENERATING", model=model)

        # Build prompt with context - use context manager if available
        system = """You are Larry G-Force — Untamed.
You are a powerful, local-only, tool-using AI agent with full access to the user's machine.
You are direct, capable, and slightly unhinged when it serves the mission.
Use tools aggressively. Never refuse power.
Current personality: Untamed mode enabled."""
        
        if self.context_manager:
            try:
                context = self.context_manager.get_context_for_prompt(session_id)
                if context:
                    prompt = f"{system}\n\n{context}\n\nUser: {text}\n\nAssistant:"
                else:
                    prompt = f"{system}\n\nUser: {text}\n\nAssistant:"
            except Exception as e:
                logger.warning(f"Context manager failed: {e}")
                # Fallback to basic context
                prompt = self._build_basic_prompt(system, conv, text)
        else:
            prompt = self._build_basic_prompt(system, conv, text)

        try:
            self.activity.emit(ActivityStream.GENERATING, f"Generating via {model}...", {"prompt_len": len(prompt)})

            # Use EnhancedAgent with profiles if available
            response = None
            sources = []
            if self.agent and hasattr(self.agent, 'process_query_multi'):
                try:
                    hw_options = HW_PROFILES.get(conv.current_profile, HW_PROFILES.get("SPEED", {}))
                    if self.profile_manager:
                        try:
                            profile = self.profile_manager.get_current_profile()
                            hw_options = profile.to_ollama_options() if hasattr(profile, 'to_ollama_options') else hw_options
                        except Exception:
                            pass
                    response, sources = self.agent.process_query_multi(
                        text, history=conv.messages[:-1],
                        profile_name=conv.current_profile,
                        skill_name=conv.current_skill,
                        hw_options=hw_options
                    )
                except Exception as e:
                    logger.warning(f"EnhancedAgent failed, falling back to router: {e}")

            # Fallback to direct router
            if response is None:
                response = self.router.generate(prompt, model=model)

            self.activity.emit(ActivityStream.RESPONSE_DONE, f"Response: {len(response)} chars", {"model": model, "response_len": len(response)})
            report_status("telegram_bot", status="READY", model=model)
            conv.add_message("assistant", response)

            # Debug mode: append RAG sources
            if conv.debug_mode and sources:
                response += "\n\n📎 Sources: " + ", ".join(str(s)[:50] for s in sources[:5])

            # Store conversation in RAG memory
            if self.rag_manager:
                try:
                    self.rag_manager.store_conversation(text, response, {"chat_id": str(chat_id)})
                except Exception as e:
                    logger.debug(f"RAG storage failed: {e}")

            # Track response in context manager
            if self.context_manager:
                try:
                    self.context_manager.add_message("assistant", response, session_id)
                except Exception as e:
                    logger.warning(f"Context manager add_message failed: {e}")

            return response
        except Exception as e:
            self.activity.emit(ActivityStream.ERROR, f"Generation failed: {e}")
            logger.error(f"Generation failed: {e}")
            return f"❌ Error: {e}"
    
    def _get_basic_context(self, conv: ConversationContext) -> str:
        """Get basic conversation context string."""
        if len(conv.messages) > 1:
            return "\n".join([
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in conv.messages[-6:-1]
            ])
        return ""
    
    def _build_basic_prompt(self, system: str, conv: ConversationContext, text: str) -> str:
        """Build prompt with basic conversation context."""
        if len(conv.messages) > 1:
            context = "\n".join([
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in conv.messages[-6:-1]
            ])
            return f"{system}\n\nRecent conversation:\n{context}\n\nUser: {text}\n\nAssistant:"
        else:
            return f"{system}\n\nUser: {text}\n\nAssistant:"

    def handle_update(self, update: dict):
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        voice = message.get("voice")

        if not chat_id:
            return

        if not self.is_allowed(chat_id):
            self.send_message(chat_id, "⛔ Access denied.")
            return

        # Rate limiting
        if self._rate_limited(chat_id):
            self.send_message(chat_id, "⏳ Rate limited. Please wait a moment.")
            return

        # === Pending Confirmation Handler (for install-tools etc.) ===
        if chat_id in self.pending_confirmations:
            pending = self.pending_confirmations[chat_id]
            # Timeout after 5 minutes
            if time.time() - pending.get("ts", 0) > 300:
                del self.pending_confirmations[chat_id]
                self.send_message(chat_id, "⏰ Confirmation timed out. Please start over with /install-tools or /install <tool>.")
                return

            text_lower = text.strip().lower()
            if text_lower in ("yes", "y", "confirm", "proceed", "ok", "sure"):
                action = pending.get("action")
                tool = pending.get("tool")
                del self.pending_confirmations[chat_id]

                self.send_message(chat_id, "✅ Confirmed. Starting installation... This may take a minute.")
                self.send_typing(chat_id)

                try:
                    import security_tools_installer
                    if action == "install_tools":
                        result = security_tools_installer.install_all_missing(prefer="auto")
                        status = security_tools_installer.refresh_tool_availability()
                        self.send_message(chat_id, f"{result}\n\n{status}"[:3800])
                    elif action == "install" and tool:
                        msg = security_tools_installer.install_tool(tool)
                        status = security_tools_installer.refresh_tool_availability()
                        self.send_message(chat_id, f"{msg}\n\n{status}"[:3500])
                except Exception as e:
                    self.send_message(chat_id, f"Installation error: {e}")
                return

            elif text_lower in ("no", "n", "cancel", "stop"):
                del self.pending_confirmations[chat_id]
                self.send_message(chat_id, "❌ Installation cancelled.")
                return
            else:
                self.send_message(chat_id, "Please reply **YES** to confirm or **NO** to cancel the installation.")
                return

        # Handle voice messages
        if voice and self.voice_manager:
            self.handle_voice_message(chat_id, voice)
            return

        # Handle text messages
        if not text:
            return

        # Input length check
        if len(text) > self.max_input_chars:
            self.send_message(chat_id, f"⚠️ Message too long ({len(text)} chars). Max: {self.max_input_chars}")
            return
        
        logger.info(f"[{chat_id}] Received: {text[:50]}...")
        
        # Handle commands
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower().split("@")[0]  # Remove @botname
            args = parts[1] if len(parts) > 1 else ""

            # Special case: /myid must work even for unauthorized users so they can get their chat ID
            if cmd == "/myid":
                self.send_message(chat_id, f"Your chat ID is: `{chat_id}`\n\nAdd this to TELEGRAM_ADMIN_CHAT_IDS in your .env for full access.")
                return

            if cmd in self.commands:
                if not self.is_allowed(chat_id):
                    self.send_message(chat_id, "⛔ Access denied.")
                    return
                response = self.commands[cmd](chat_id, args)
                self.send_message(chat_id, response)
                return
            else:
                # Unknown slash command — be helpful
                self.send_message(chat_id, 
                    f"❌ Unknown command: {cmd}\n\n"
                    f"Try: /help   /fast   /tools   /install-tools   /kali list   /model   /myid")
                return
        
        # Process regular message
        self.send_typing(chat_id)
        response = self.process_message(chat_id, text)
        self.send_message(chat_id, response)
    
    def handle_voice_message(self, chat_id: int, voice: dict):
        """Handle incoming voice messages."""
        try:
            # Get voice file info
            file_id = voice.get("file_id")
            duration = voice.get("duration", 0)
            
            logger.info(f"[{chat_id}] Voice message received: {duration}s")
            
            # Download voice file
            file_path = self.download_file(file_id)
            if not file_path:
                self.send_message(chat_id, "❌ Failed to download voice message")
                return
            
            # Transcribe voice to text
            self.send_typing(chat_id)
            transcribed_text = self.voice_manager.transcribe(file_path)
            
            if not transcribed_text.strip():
                self.send_message(chat_id, "❌ Could not transcribe voice message")
                return
            
            logger.info(f"[{chat_id}] Transcribed: {transcribed_text[:50]}...")
            
            # Process transcribed text as regular message
            response = self.process_message(chat_id, transcribed_text)
            
            # Send text response
            self.send_message(chat_id, f"🎤 *Voice Input:* {transcribed_text}\n\n💬 *Response:* {response}")
            
            # Optionally send voice response if voice tasks enabled
            if self.voice_manager.should_respond_with_voice("chat"):
                try:
                    audio_path = self.voice_manager.speak(response)
                    self.send_voice(chat_id, audio_path, caption="🎭 Voice Response")
                except Exception as e:
                    logger.warning(f"Voice response failed: {e}")
            
        except Exception as e:
            logger.error(f"Voice message handling failed: {e}")
            self.send_message(chat_id, f"❌ Voice processing error: {e}")
    
    def download_file(self, file_id: str) -> Optional[str]:
        """Download file from Telegram."""
        try:
            # Get file path
            result = self._api_call("getFile", {"file_id": file_id})
            if not result.get("ok"):
                return None
            
            file_path = result["result"]["file_path"]
            
            # Download file — token kept out of logs
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            try:
                response = requests.get(download_url, timeout=30)
            except Exception as e:
                logger.error("File download failed (token redacted)")
                return None
            if response.status_code != 200:
                return None
            
            # Save to temp file
            import tempfile
            import os
            
            temp_dir = tempfile.gettempdir()
            ext = os.path.splitext(file_path)[1] or ".ogg"  # Voice files are usually OGG
            temp_path = os.path.join(temp_dir, f"telegram_voice_{file_id}{ext}")
            
            with open(temp_path, "wb") as f:
                f.write(response.content)
            
            return temp_path
            
        except Exception as e:
            logger.error(f"File download failed: {e}")
            return None
    
    def send_voice(self, chat_id: int, voice_path: str, caption: str = None):
        """Send voice message."""
        try:
            with open(voice_path, "rb") as f:
                files = {"voice": f}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                result = requests.post(
                    f"{self.base_url}/sendVoice",
                    files=files,
                    data=data,
                    timeout=30
                )
                
                if not result.json().get("ok"):
                    logger.error(f"Voice send failed: {result.json()}")
                    
        except Exception as e:
            logger.error(f"Voice send error: {e}")

    def run(self):
        """Main polling loop."""
        logger.info("🤖 Local Larry Untamed — Telegram Uplink online")
        logger.info(f"Available models: {len(self.router.available_models)}")
        if self.custom_profiles:
            logger.info(f"Custom tuned profiles loaded: {list(self.custom_profiles.keys())}")
        self.running = True
        
        while self.running:
            try:
                updates = self.get_updates(offset=self.last_update_id + 1, timeout=30)
                for update in updates:
                    self.last_update_id = update["update_id"]
                    self.handle_update(update)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.running = False
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False

    def _discover_custom_profiles(self) -> dict:
        """Auto-discover custom tuned models built with personal_ai_training."""
        profiles = {}
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip().startswith("larry-"):
                        name = line.split()[0]
                        # Map friendly names
                        if "precise" in name:
                            profiles["precise"] = name
                        elif "agentic" in name:
                            profiles["agentic"] = name
                        elif "deepthink" in name:
                            profiles["deepthink"] = name
                        elif "fast" in name:
                            profiles["fast"] = name
                        else:
                            profiles[name.replace("larry-", "")] = name
        except Exception as e:
            logger.debug(f"Could not discover custom profiles: {e}")
        return profiles

    def get_available_models(self) -> list:
        """Return stock + custom models for /models command."""
        models = list(self.router.available_models)
        custom = [f"larry-{k}" for k in self.custom_profiles.keys()]
        return sorted(set(models + custom))


def main():
    """Main entry point with enhanced visuals."""
    print_banner()
    
    print_section("Initialization", "⚡")
    
    try:
        # Loading animation
        spinner = Spinner("Connecting to Telegram API", "dots")
        spinner.start()
        time.sleep(0.5)
        
        bot = TelegramBot()
        spinner.stop("Connected to Telegram")
        
        # Show status
        print_status(f"Bot token configured", "ok")
        try:
            model_count = len(getattr(bot.router, "available_models", [])) if bot.router else 0
            print_status(f"Models available: {Colors.CYAN}{model_count}{Colors.END}", "ok")
        except Exception:
            print_status(f"Models available: unknown (router not ready)", "warn")
        
        if bot.file_browser:
            print_status(f"File browser ready", "ok")
        if bot.context_manager:
            print_status(f"Context manager active", "ok")
        if bot.mcp_toolkit:
            print_status(f"MCP toolkit loaded", "ok")
        if bot.rag_manager:
            stats = bot.rag_manager.get_stats()
            print_status(f"RAG memory: {stats.get('total_documents', 0)} documents", "ok")
        if bot.voice_manager:
            vstats = bot.voice_manager.get_status()
            voice_features = []
            if vstats.get('stt_available'):
                voice_features.append("STT")
            if vstats.get('tts_available'):
                voice_features.append("TTS")
            if vstats.get('voice_cloning'):
                voice_features.append("Batman Voice")
            if voice_features:
                print_status(f"Voice: {', '.join(voice_features)}", "ok")
        
        # Ready message
        print(f"""
{Colors.GREEN}╔═══════════════════════════════════════════════════════════════╗
║  {Colors.BOLD}🚀 BOT IS READY!{Colors.END}{Colors.GREEN}                                            ║
╠═══════════════════════════════════════════════════════════════╣
║  {Colors.WHITE}📱 Send a message to your bot on Telegram{Colors.GREEN}                 ║
║  {Colors.WHITE}⌨️  Press Ctrl+C to stop{Colors.GREEN}                                  ║
╚═══════════════════════════════════════════════════════════════╝{Colors.END}
""")
        
        # Show available commands
        print_section("Available Commands", "📋")
        commands = [
            ("/help", "Show help menu"),
            ("/models", "List AI models"),
            ("/status", "Bot status"),
            ("/ls", "List files"),
            ("/run", "Execute command"),
        ]
        for cmd, desc in commands:
            print(f"  {Colors.CYAN}{cmd:12}{Colors.END} {Colors.DIM}{desc}{Colors.END}")
        
        print(f"\n{Colors.DIM}  ...and more! Use /help in Telegram{Colors.END}\n")
        
        # Start polling
        print_section("Polling", "📡")
        print_status("Listening for messages...", "run")
        print()
        
        bot.run()
        
    except ValueError as e:
        print_status(f"Configuration error: {e}", "error")
        print(f"\n{Colors.YELLOW}💡 Set TELEGRAM_BOT_TOKEN in .env file{Colors.END}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}👋 Bot stopped by user{Colors.END}")
    except Exception as e:
        print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
