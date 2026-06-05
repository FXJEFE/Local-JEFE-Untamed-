#!/usr/bin/env python3
"""
Local Larry - Master Service Launcher
=========================================
Starts all services, agents, and MCP servers in the correct order.

Usage:
    python launch_all.py              # Start everything
    python launch_all.py --check      # Check status only
    python launch_all.py --stop       # Stop all services
    python launch_all.py --services   # List all services
"""

import os
import sys
import time
import signal
import subprocess
import threading
import argparse
import socket
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

def _enable_windows_ansi():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        return

_enable_windows_ansi()

# ============================================================
# CONFIGURATION
# ============================================================

@dataclass
class ServiceConfig:
    name: str
    description: str
    check_command: Optional[str] = None
    start_command: Optional[str] = None
    port: Optional[int] = None
    required: bool = True
    process: Optional[subprocess.Popen] = None


SERVICES: Dict[str, ServiceConfig] = {
    # External Services
    "ollama": ServiceConfig(
        name="Ollama LLM Server",
        description="Local LLM inference server",
        check_command="curl -s http://localhost:11434/api/tags",
        start_command="ollama serve",
        port=11434,
        required=True
    ),
    
    # Optional External Services
    "n8n": ServiceConfig(
        name="n8n Workflow Engine",
        description="Workflow automation platform",
        check_command="curl -s http://localhost:5678/healthz",
        start_command=None,  # User starts manually
        port=5678,
        required=False
    ),
    
    "podman": ServiceConfig(
        name="Podman Container Runtime",
        description="Container management",
        check_command="podman info --format json",
        start_command=None,
        required=False
    ),
}


def _load_env():
    if load_dotenv is None:
        return
    try:
        load_dotenv()
    except Exception:
        return

# Python modules to initialize
PYTHON_MODULES = [
    ("mcp_servers", "MCP Server Toolkit"),
    ("model_router", "Model Router (22 models)"),
    ("vector_enhanced", "ChromaDB Vector Store"),
    ("file_browser", "File Browser"),
    ("web_tools", "Web Tools (Scraping/YouTube)"),
]

# MCP Servers
MCP_SERVERS = [
    ("github", "GitHub API operations"),
    ("filesystem", "File system operations"),
    ("memory", "Knowledge graph memory"),
    ("sqlite", "SQLite database"),
    ("brave_search", "Brave web search"),
    ("context7", "Library documentation"),
    ("playwright", "Browser automation"),
    ("n8n", "Workflow automation"),
    ("podman", "Container management"),
]


# ============================================================
# UTILITIES
# ============================================================

class Colors:
    """Rich color palette for expensive terminal styling."""
    # Premium Palette
    GOLD = '\033[38;2;255;215;0m'
    GOLD_DIM = '\033[38;2;184;134;11m'
    
    NEON_BLUE = '\033[38;2;0;255;255m'
    SKY_BLUE = '\033[38;2;135;206;250m'
    DEEP_SKY = '\033[38;2;30;144;255m'
    
    NEON_PURPLE = '\033[38;2;180;0;255m'
    LAVENDER = '\033[38;2;230;230;250m'
    
    LIME = '\033[38;2;50;255;50m'
    EMERALD = '\033[38;2;80;200;120m'
    
    CRIMSON = '\033[38;2;220;20;60m'
    HOT_PINK = '\033[38;2;255;105;180m'
    
    # Grays
    GREY_100 = '\033[38;2;245;245;245m'
    GREY_70 = '\033[38;2;179;179;179m'
    GREY_50 = '\033[38;2;128;128;128m'
    GREY_30 = '\033[38;2;77;77;77m'
    GREY_10 = '\033[38;2;26;26;26m'

    # Standard
    BLACK = '\033[30m'
    WHITE = '\033[97m'
    END = '\033[0m'

    # Modifiers
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    
    @staticmethod
    def gradient(text: str, start_rgb: tuple, end_rgb: tuple) -> str:
        """Create a gradient string."""
        length = len(text)
        result = ""
        for i, char in enumerate(text):
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * i / length)
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * i / length)
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * i / length)
            result += f"\033[38;2;{r};{g};{b}m{char}"
        return result + Colors.END


def _glow_block(block: str, fg_hex: str = None) -> str:
    """Create a glowing block effect with manual shadows."""
    color = fg_hex if fg_hex else Colors.NEON_BLUE
    lines = block.splitlines()
    # Shadow logic (simple right-down offset)
    shadow_lines = [f" {line}" for line in lines]
    shadow_content = "\n".join(f"{Colors.GREY_30}{l}{Colors.END}" for l in shadow_lines)
    main_content = "\n".join(f"{color}{l}{Colors.END}" for l in lines)
    return f"{shadow_content}\n\033[{len(lines)}A{main_content}"


class Spinner:
    """Animated spinner for loading states."""
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    
    def __init__(self, message: str = "Loading"):
        self.message = message
        self.running = False
        self.thread = None
        self.idx = 0
    
    def spin(self):
        import threading
        while self.running:
            frame = self.FRAMES[self.idx % len(self.FRAMES)]
            print(f"\r  {Colors.LIME}{frame}{Colors.END} {Colors.GREY_70}{self.message}{Colors.END}...", end="", flush=True)
            self.idx += 1
            time.sleep(0.1)
    
    def start(self):
        import threading
        self.running = True
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()
    
    def stop(self, final_message: str = None):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        if final_message:
            print(f"\r  {Colors.LIME}✓{Colors.END} {Colors.GREY_70}{final_message}{Colors.END}" + " " * 20)
        else:
            print("\r" + " " * 60 + "\r", end="")


def print_banner():
    """Print stylish ASCII art banner."""
    art = r"""
  _                     _   _                          
 | |    ___   ___ __ _ | | | | __ _ _ __ _ __ _   _    
 | |   / _ \ / __/ _` || | | |/ _` | '__| '__| | | |   
 | |__| (_) | (_| (_| || | | | (_| | |  | |  | |_| |   
 |_____\___/ \___\__,_||_| |_|\__,_|_|  |_|   \__, |   
                                              |___/    
""".rstrip("\n")

    header = _glow_block(art, Colors.SKY_BLUE)
    
    # Vibrant gradient title
    title_text = "   🚀 Local Larry Master Launcher"
    title = Colors.gradient(title_text, (0, 255, 255), (180, 0, 255))
    
    sep_line = "═" * 50
    sep = f"{Colors.GREY_30}    {sep_line}{Colors.END}"

    stats = (
        f"{Colors.GREY_30}    ╔═════════════════════════════════════════╗{Colors.END}\n"
        f"{Colors.GREY_30}    ║ {Colors.NEON_BLUE}•{Colors.GREY_50} 9 Native MCP Servers  {Colors.NEON_BLUE}•{Colors.GREY_50} 22+ Models   ║{Colors.END}\n"
        f"{Colors.GREY_30}    ║ {Colors.NEON_BLUE}•{Colors.GREY_50} ChromaDB RAG          {Colors.NEON_BLUE}•{Colors.GREY_50} Playwright   ║{Colors.END}\n"
        f"{Colors.GREY_30}    ║ {Colors.NEON_BLUE}•{Colors.GREY_50} n8n Workflows         {Colors.NEON_BLUE}•{Colors.GREY_50} Containers   ║{Colors.END}\n"
        f"{Colors.GREY_30}    ╚═════════════════════════════════════════╝{Colors.END}"
    )

    print(f"\n{header}\n{sep}\n{title}\n{sep}\n\n{stats}\n")


def print_step(msg: str, status: str = ""):
    """Print a styled, vibrant status step."""
    icons = {
        "ok": f"{Colors.LIME}●{Colors.END}",
        "success": f"{Colors.LIME}●{Colors.END}",
        "fail": f"{Colors.CRIMSON}✖{Colors.END}",
        "error": f"{Colors.CRIMSON}✖{Colors.END}",
        "warn": f"{Colors.GOLD}▲{Colors.END}",
        "run": f"{Colors.NEON_BLUE}›{Colors.END}",
        "wait": f"{Colors.GREY_50}◌{Colors.END}",
        "info": f"{Colors.DEEP_SKY}ℹ{Colors.END}",
    }
    icon = icons.get(status, f"{Colors.GREY_50}•{Colors.END}")
    print(f"  {icon} {Colors.WHITE}{msg}{Colors.END}")


def print_section(title: str, icon: str = "�"):
    """Print a premium section header with gradient."""
    # Create a gradient for the title
    title_text = f" {icon} {title} "
    colored_title = Colors.gradient(title_text, (255, 255, 255), (0, 200, 255))
    
    line_len = 60 - len(title_text)
    line = f"{Colors.GREY_30}{'─' * line_len}{Colors.END}"
    
    print(f"\n{colored_title} {line}")


def run_command(cmd: str, timeout: int = 10) -> Tuple[bool, str]:
    """Run a shell command and return (success, output)"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
        else:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def check_postgres() -> Tuple[bool, str]:
    host = os.getenv("PG_HOST", "localhost")
    port_str = os.getenv("PG_PORT", "5432")
    try:
        port = int(port_str)
    except ValueError:
        return False, f"Invalid PG_PORT: {port_str}"
    try:
        with socket.create_connection((host, port), timeout=2):
            return True, f"Reachable at {host}:{port}"
    except Exception as e:
        return False, f"{host}:{port} - {e}"


# ============================================================
# SERVICE CHECKS
# ============================================================

def check_ollama() -> Tuple[bool, str]:
    """Check Ollama server status"""
    try:
        import ollama
        models = ollama.list()
        model_list = models.get('models', [])
        return True, f"{len(model_list)} models available"
    except Exception as e:
        return False, str(e)


def check_python_module(module_name: str) -> Tuple[bool, str]:
    """Check if a Python module can be imported"""
    try:
        __import__(module_name)
        return True, "OK"
    except ImportError as e:
        return False, str(e)


def check_mcp_servers() -> Dict[str, Tuple[bool, str]]:
    """Check all MCP servers"""
    results = {}
    try:
        from mcp_client import MCPToolkit
        toolkit = MCPToolkit()
        
        for server_name, description in MCP_SERVERS:
            try:
                server = getattr(toolkit, server_name, None)
                if server:
                    tools = []
                    if hasattr(server, 'list_tools'):
                        tools = server.list_tools()
                    elif hasattr(server, 'tools'):
                        tools = server.tools
                    
                    results[server_name] = (True, f"{len(tools)} tools")
                else:
                    results[server_name] = (False, "Not found")
            except Exception as e:
                results[server_name] = (False, str(e)[:50])
    except Exception as e:
        for server_name, _ in MCP_SERVERS:
            results[server_name] = (False, f"Toolkit error: {str(e)[:30]}")
    
    return results


def check_chromadb() -> Tuple[bool, str]:
    """Check ChromaDB status"""
    try:
        import chromadb
        db_path = PROJECT_ROOT / "chroma_db"
        client = chromadb.PersistentClient(path=str(db_path))
        collections = client.list_collections()
        return True, f"{len(collections)} collections"
    except Exception as e:
        return False, str(e)


# ============================================================
# SERVICE STARTUP
# ============================================================

def check_all():
    """Check status of all components"""
    print_section("System Status Check", "🔍")
    
    # Ollama
    ok, msg = check_ollama()
    print_step(f"Ollama LLM: {msg}", "ok" if ok else "fail")
    
    # Postgres
    if os.getenv("RAG_BACKEND", "").lower() == "postgres":
        ok, msg = check_postgres()
        print_step(f"Postgres: {msg}", "ok" if ok else "warn")
    
    # Python Modules
    print_section("Python Modules", "📦")
    for module, desc in PYTHON_MODULES:
        ok, msg = check_python_module(module)
        print_step(f"{desc}: {msg}", "ok" if ok else "fail")
        
    # ChromaDB
    ok, msg = check_chromadb()
    print_step(f"ChromaDB: {msg}", "ok" if ok else "fail")
    
    # MCP Servers
    print_section("MCP Servers", "🔌")
    mcp_results = check_mcp_servers()
    for server_name, _ in MCP_SERVERS:
        if server_name in mcp_results:
            ok, msg = mcp_results[server_name]
            print_step(f"{server_name}: {msg}", "ok" if ok else "fail")
        else:
            print_step(f"{server_name}: Not checked", "warn")

def start_ollama() -> bool:
    """Start Ollama server if not running"""
    ok, _ = check_ollama()
    if ok:
        return True
    
    print_step("Starting Ollama server...", "run")
    
    if sys.platform == "win32":
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    else:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    
    # Wait for startup
    for _ in range(10):
        time.sleep(1)
        ok, _ = check_ollama()
        if ok:
            return True
    
    return False


def init_vector_store() -> bool:
    """Initialize ChromaDB vector store"""
    try:
        from vector_enhanced import ChromaDBVectorStore
        db_path = PROJECT_ROOT / "chroma_db"
        store = ChromaDBVectorStore(persist_directory=str(db_path))
        return True
    except Exception as e:
        print_step(f"Vector store error: {e}", "fail")
        return False


def init_rag_manager() -> bool:
    try:
        from rag_integration import get_rag_manager

        backend = os.getenv("RAG_BACKEND", "chroma").lower()
        mgr = get_rag_manager(backend=backend)
        _ = mgr.get_stats()
        return True
    except Exception as e:
        print_step(f"RAG init error: {e}", "fail")
        return False


def init_model_router() -> bool:
    try:
        from model_router import get_router

        router = get_router()
        _ = len(router.available_models)
        return True
    except Exception as e:
        print_step(f"Model router error: {e}", "fail")
        return False


def init_context_manager() -> bool:
    try:
        from model_router import get_router
        from context_manager import get_context_manager

        router = get_router()
        _ = get_context_manager(router)
        return True
    except Exception as e:
        print_step(f"Context manager error: {e}", "warn")
        return False


def init_agent_v2() -> bool:
    try:
        from agent_v2 import EnhancedAgent

        _ = EnhancedAgent()
        return True
    except Exception as e:
        print_step(f"Agent init error: {e}", "fail")
        return False


def _retry(step_name: str, fn, attempts: int = 3, base_sleep: float = 0.75) -> bool:
    for attempt in range(1, attempts + 1):
        if fn():
            return True
        if attempt < attempts:
            time.sleep(base_sleep * attempt)
    print_step(f"{step_name} failed after {attempts} attempts", "fail")
    return False


def init_mcp_toolkit() -> bool:
    """Initialize MCP Toolkit"""
    try:
        from mcp_client import MCPToolkit
        toolkit = MCPToolkit()
        return True
    except Exception as e:
        print_step(f"MCP Toolkit error: {e}", "fail")
        return False


def pull_essential_models():
    """Pull essential Ollama models"""
    essential = ["llama3.2:3b", "nomic-embed-text"]
    
    try:
        import ollama
        existing = [m.get('name', m.get('model', '')) for m in ollama.list().get('models', [])]
        
        for model in essential:
            if not any(model in e for e in existing):
                print_step(f"Pulling {model}...", "run")
                ollama.pull(model)
    except Exception as e:
        print_step(f"Model pull error: {e}", "warn")


def test_mcp_servers(quiet: bool = False) -> Dict[str, bool]:
    """Test all MCP servers and return status"""
    results = {}
    
    if not quiet:
        print(f"\n{Colors.BOLD}Testing MCP Servers...{Colors.END}\n")
    
    try:
        from mcp_client import MCPToolkit
        toolkit = MCPToolkit()
        
        for server_name, description in MCP_SERVERS:
            try:
                server = getattr(toolkit, server_name, None)
                if server:
                    # Try to get tools list
                    tools = []
                    if hasattr(server, 'list_tools'):
                        tools = server.list_tools()
                    elif hasattr(server, 'tools'):
                        tools = server.tools
                    
                    results[server_name] = True
                    if not quiet:
                        print_step(f"{server_name}: {len(tools)} tools - {description}", "ok")
                else:
                    results[server_name] = False
                    if not quiet:
                        print_step(f"{server_name}: Not initialized", "fail")
            except Exception as e:
                results[server_name] = False
                if not quiet:
                    print_step(f"{server_name}: {str(e)[:40]}", "fail")
    except ImportError:
        if not quiet:
            print_step("MCP Toolkit not available", "fail")
        for server_name, _ in MCP_SERVERS:
            results[server_name] = False
    except Exception as e:
        if not quiet:
            print_step(f"MCP Toolkit error: {e}", "fail")
        for server_name, _ in MCP_SERVERS:
            results[server_name] = False
    
    # Summary
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    if not quiet:
        print(f"\n{Colors.BOLD}Results: {passed}/{total} servers ready{Colors.END}")
    else:
        print_step(f"MCP Servers: {passed}/{total} ready", "ok" if passed == total else "warn")
    
    return results


def start_telegram_bot():
    """Start Telegram bot with all services initialized"""
    print_section("📱 Telegram Bot Startup", "🚀")
    
    _load_env()

    # 0. Optional DB check (only when configured)
    if os.getenv("RAG_BACKEND", "chroma").lower() == "postgres":
        print_section("Postgres (optional)", "0️⃣")
        # Try to start Docker Postgres if not running
        try:
            # If Podman is available on Windows, ensure the machine is started first
            try:
                podman_check = subprocess.run(['podman', '--version'], capture_output=True)
                if podman_check.returncode == 0:
                    print_step('Podman detected — ensuring podman machine is started', 'run')
                    subprocess.run(['podman', 'machine', 'start'], check=False)
                    time.sleep(3)
            except FileNotFoundError:
                # podman not present — continue
                pass

            # Try docker-compose, then podman-compose, then docker compose
            started = False
            try:
                subprocess.run(['docker-compose', 'up', '-d', 'postgres'], check=True, capture_output=True)
                started = True
                runtime = 'docker-compose'
            except Exception:
                try:
                    subprocess.run(['podman-compose', 'up', '-d', 'postgres'], check=True, capture_output=True)
                    started = True
                    runtime = 'podman-compose'
                except Exception:
                    try:
                        subprocess.run(['docker', 'compose', 'up', '-d', 'postgres'], check=True, capture_output=True)
                        started = True
                        runtime = 'docker compose'
                    except Exception as e:
                        print_step(f'Docker/Podman compose failed: {e}', 'warn')

            if started:
                print_step(f"Compose started via {runtime}", 'ok')
                # Wait for container health
                for attempt in range(10):
                    # Try both docker and podman exec
                    ok = False
                    try:
                        r = subprocess.run(['docker', 'exec', 'larry-postgres', 'pg_isready', '-U', 'postgres'], capture_output=True)
                        if r.returncode == 0:
                            ok = True
                    except Exception:
                        pass
                    if not ok:
                        try:
                            r = subprocess.run(['podman', 'exec', 'larry-postgres', 'pg_isready', '-U', 'postgres'], capture_output=True)
                            if r.returncode == 0:
                                ok = True
                        except Exception:
                            pass
                    if ok:
                        print_step('Postgres ready', 'ok')
                        break
                    time.sleep(5)
                else:
                    print_step('Postgres health check failed - fallback to Chroma', 'warn')
        except Exception as e:
            print_step(f"Postgres startup error: {e} - fallback to Chroma", "warn")
        
        # Check connection
        ok_db, msg_db = check_postgres()
        print_step(f"Postgres: {msg_db}", "ok" if ok_db else "warn")

    # 1. Check Ollama
    print_section("Ollama LLM Server", "1️⃣")
    spinner = Spinner("Checking Ollama connection")
    spinner.start()
    time.sleep(0.3)
    ok, msg = check_ollama()
    if ok:
        spinner.stop(f"Ollama ready ({msg})")
    else:
        spinner.stop(None)
        print_step("Starting Ollama...", "run")
        if start_ollama():
            print_step("Ollama started", "ok")
        else:
            print_step("Ollama not available - some features limited", "warn")
    
    # 2. Model Router
    print_section("Model Router", "2️⃣")
    spinner = Spinner("Initializing router")
    spinner.start()
    time.sleep(0.3)
    if _retry("Model router", init_model_router, attempts=2):
        spinner.stop("Model router ready")
    else:
        spinner.stop(None)
        print_step("Model router failed - bot may be limited", "warn")

    # 3. RAG
    print_section("RAG", "3️⃣")
    spinner = Spinner("Initializing RAG")
    spinner.start()
    time.sleep(0.3)
    if _retry("RAG", init_rag_manager, attempts=2):
        spinner.stop("RAG ready")
    else:
        spinner.stop(None)
        print_step("RAG init failed - running without memory", "warn")

    # 4. MCP Toolkit
    print_section("MCP Toolkit", "4️⃣")
    spinner = Spinner("Initializing MCP servers")
    spinner.start()
    time.sleep(0.3)
    if _retry("MCP Toolkit", init_mcp_toolkit, attempts=2):
        spinner.stop("MCP Toolkit ready")
    else:
        spinner.stop(None)
        print_step("MCP Toolkit failed - some features limited", "warn")

    # 5. Context Manager
    print_section("Context Manager", "5️⃣")
    _ = init_context_manager()

    # 6. Test MCP Servers
    print_section("MCP Server Tests", "6️⃣")
    _ = test_mcp_servers(quiet=True)
    
    # 7. Start Telegram Bot
    print_section("Telegram Bot", "7️⃣")
    
    try:
        # Check for Telegram token
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print_step("TELEGRAM_BOT_TOKEN not set in .env", "fail")
            print(f"\n{Colors.YELLOW}💡 Setup Instructions:{Colors.END}")
            print(f"  {Colors.DIM}1. Create bot with @BotFather on Telegram{Colors.END}")
            print(f"  {Colors.DIM}2. Add to .env: TELEGRAM_BOT_TOKEN=your_token{Colors.END}")
            return
        
        print_step("Token configured", "ok")
        
        spinner = Spinner("Connecting to Telegram API")
        spinner.start()
        time.sleep(0.5)
        
        # Import and run the bot
        from telegram_bot import TelegramBot
        bot = TelegramBot()
        spinner.stop("Connected to Telegram")
        
        # Success banner
        print(f"""
{Colors.NEON_PURPLE}╔═══════════════════════════════════════════════════════════════╗
║  {Colors.BOLD}{Colors.GOLD}                  ROCKET LAUNCHED! 🚀                        {Colors.END}{Colors.NEON_PURPLE}║
{Colors.NEON_PURPLE}╠═══════════════════════════════════════════════════════════════╣
║  {Colors.GREY_100}🤖 Models: {len(bot.router.available_models)}{Colors.NEON_PURPLE}                                             ║
║  {Colors.GREY_100}📱 Send a message to your bot on Telegram{Colors.NEON_PURPLE}                  ║
║  {Colors.GREY_100}⌨️  Press Ctrl+C to stop{Colors.NEON_PURPLE}                                   ║
╚═══════════════════════════════════════════════════════════════╝{Colors.END}
""")
        
        print(f"{Colors.LIME}✓{Colors.END} {Colors.GREY_70}Bot initialized{Colors.END}")
        print(f"{Colors.LIME}✓{Colors.END} {Colors.GREY_70}Models available: {len(bot.router.available_models)}{Colors.END}")
        print(f"\n{Colors.BOLD}{Colors.GOLD}Bot is running!{Colors.END} {Colors.GREY_50}Press Ctrl+C to stop.{Colors.END}\n")
        
        bot.run()
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Bot stopped by user{Colors.END}")
    except Exception as e:
        print_step(f"Bot error: {e}", "fail")
        import traceback
        traceback.print_exc()


def start_all():
    """Start all services"""
    print(f"\n{Colors.BOLD}Starting All Services...{Colors.END}\n")
    
    _load_env()

    # 0. Optional DB check (only when configured)
    if os.getenv("RAG_BACKEND", "chroma").lower() == "postgres":
        print(f"\n{Colors.BOLD}{Colors.GOLD}[0/7]{Colors.END} {Colors.GREY_100}Postgres (optional){Colors.END}")
        ok_db, msg_db = check_postgres()
        print_step(f"Postgres: {msg_db}", "ok" if ok_db else "warn")

    # 1. Start Ollama
    print(f"\n{Colors.BOLD}{Colors.GOLD}[1/6]{Colors.END} {Colors.GREY_100}Ollama LLM Server{Colors.END}")
    if start_ollama():
        print_step("Ollama running", "ok")
    else:
        print_step("Failed to start Ollama", "fail")
        print_step("Start manually: ollama serve", "warn")
    
    # 2. Pull essential models
    print(f"\n{Colors.BOLD}{Colors.GOLD}[2/6]{Colors.END} {Colors.GREY_100}Ollama Models{Colors.END}")
    pull_essential_models()
    print_step("Essential models ready", "ok")
    
    # 3. Initialize Model Router
    print(f"\n{Colors.BOLD}{Colors.GOLD}[3/7]{Colors.END} {Colors.GREY_100}Model Router{Colors.END}")
    if _retry("Model router", init_model_router, attempts=2):
        print_step("Model router initialized", "ok")
    else:
        print_step("Model router initialization failed", "warn")

    # 4. Initialize RAG
    print(f"\n{Colors.BOLD}{Colors.GOLD}[4/7]{Colors.END} {Colors.GREY_100}RAG Manager{Colors.END}")
    if _retry("RAG", init_rag_manager, attempts=2):
        print_step("RAG initialized", "ok")
    else:
        print_step("RAG initialization failed", "warn")

    # 5. Initialize MCP Toolkit
    print(f"\n{Colors.BOLD}{Colors.GOLD}[5/7]{Colors.END} {Colors.GREY_100}MCP Toolkit{Colors.END}")
    if _retry("MCP Toolkit", init_mcp_toolkit, attempts=2):
        print_step("MCP Toolkit initialized", "ok")
    else:
        print_step("MCP Toolkit initialization failed", "warn")

    # 6. Context Manager
    print(f"\n{Colors.BOLD}{Colors.GOLD}[6/7]{Colors.END} {Colors.GREY_100}Context Manager{Colors.END}")
    _ = init_context_manager()

    # 7. Ready
    print(f"\n{Colors.BOLD}{Colors.GOLD}[7/7]{Colors.END} {Colors.GREY_100}All Services Ready{Colors.END}")
    print_step("Ready to launch agent or Telegram bot", "ok")
    
    # Summary
    print(f"""
{Colors.EMERALD}╔══════════════════════════════════════════════════════════════╗
║                    ALL SERVICES READY!                        ║
╚══════════════════════════════════════════════════════════════╝{Colors.END}

{Colors.BOLD}Start options:{Colors.END}
  python agent_v2.py           # Interactive CLI agent
  python telegram_bot.py       # Telegram bot interface
  python launch_all.py --agent # Direct agent launch
  python launch_all.py --telegram # Direct Telegram bot launch

{Colors.BOLD}Test MCP servers:{Colors.END}
  python launch_all.py --test-mcp
  python test_complete_mcp.py
""")


def list_services():
    """List all available services"""
    print(f"\n{Colors.BOLD}Available Services{Colors.END}\n")
    
    print(f"{Colors.BOLD}{Colors.GOLD}External Services:{Colors.END}")
    for name, config in SERVICES.items():
        req = "Required" if config.required else "Optional"
        port = f":{config.port}" if config.port else ""
        print(f"  {Colors.NEON_BLUE}•{Colors.END} {Colors.GREY_100}{config.name}{port} [{req}]{Colors.END}")
        print(f"    {Colors.DIM}{Colors.GREY_70}{config.description}{Colors.END}")
    
    print(f"\n{Colors.BOLD}{Colors.GOLD}MCP Servers (Native Python):{Colors.END}")
    for name, desc in MCP_SERVERS:
        print(f"  {Colors.NEON_BLUE}•{Colors.END} {Colors.GREY_100}{name}: {desc}{Colors.END}")
    
    print(f"\n{Colors.BOLD}{Colors.GOLD}Python Modules:{Colors.END}")
    for name, desc in PYTHON_MODULES:
        print(f"  {Colors.NEON_BLUE}•{Colors.END} {Colors.GREY_100}{name}: {desc}{Colors.END}")


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Local Larry - Master Service Launcher"
    )
    parser.add_argument("--check", action="store_true", help="Check status only")
    parser.add_argument("--services", action="store_true", help="List all services")
    parser.add_argument("--agent", action="store_true", help="Start agent directly")
    parser.add_argument("--telegram", action="store_true", help="Start Telegram bot")
    parser.add_argument("--test-mcp", action="store_true", help="Test MCP servers only")
    
    args = parser.parse_args()
    
    print_banner()
    _load_env()
    
    if args.check:
        check_all()
    elif args.services:
        list_services()
    elif args.test_mcp:
        test_mcp_servers()
    elif args.telegram:
        start_telegram_bot()
    elif args.agent:
        # Quick start - just run agent
        os.chdir(PROJECT_ROOT)
        os.execv(sys.executable, [sys.executable, "agent_v2.py"])
    else:
        start_all()


if __name__ == "__main__":
    main()
