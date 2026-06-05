#!/usr/bin/env python3
"""
Larry Agent - Complete Setup Script
====================================
Sets up the entire environment from scratch:
1. Creates/activates virtual environment
2. Installs all dependencies
3. Initializes databases
4. Sets up MCP servers
5. Validates system
6. Optionally starts services

Usage:
    python setup_larry.py                    # Full setup
    python setup_larry.py --venv-only        # Just create venv
    python setup_larry.py --deps-only        # Just install deps
    python setup_larry.py --validate         # Validate existing setup
    python setup_larry.py --start            # Setup and start services
"""

import os
import sys

# Disable telemetry before any other imports
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import subprocess
import shutil
import json
import argparse
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.resolve()
VENV_NAME = ".venv"
VENV_PATH = PROJECT_ROOT / VENV_NAME
PYTHON_VERSION_MIN = (3, 10)

# Directories to create
REQUIRED_DIRS = [
    "data",
    "logs",
    "sandbox",
    "chroma_db",
    "context7_cache",
    "screenshots",
    "exports",
    "imports",
    "voice_cache",
]

# Required config files
CONFIG_FILES = [
    ("larry_config.json", "Main configuration"),
    ("mcp.json", "MCP server configuration"),
    (".env", "Environment variables"),
]

# Required Python modules
REQUIRED_MODULES = [
    "unified_context_manager.py",
    "production_rag.py",
    "model_router.py",
    "hardware_profiles.py",
    "mcp_client.py",
    "agent_v2.py",
    "web_tools.py",
    "safe_code_executor.py",
    "universal_file_handler.py",
    "cross_platform_paths.py",
    "skill_manager.py",
    "file_browser.py",
    "telegram_bot.py",
]

# =============================================================================
# UTILITIES
# =============================================================================

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def log(msg: str, level: str = "info"):
    colors = {"info": Colors.CYAN, "success": Colors.GREEN, 
              "warn": Colors.YELLOW, "error": Colors.RED}
    prefix = {"info": "ℹ", "success": "✓", "warn": "⚠", "error": "✗"}
    color = colors.get(level, Colors.CYAN)
    print(f"{color}{prefix.get(level, '•')} {msg}{Colors.END}")


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> Tuple[int, str, str]:
    """Run command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def get_venv_python() -> Path:
    """Get path to venv Python executable."""
    if sys.platform == "win32":
        return VENV_PATH / "Scripts" / "python.exe"
    return VENV_PATH / "bin" / "python"


def get_venv_pip() -> Path:
    """Get path to venv pip executable."""
    if sys.platform == "win32":
        return VENV_PATH / "Scripts" / "pip.exe"
    return VENV_PATH / "bin" / "pip"


# =============================================================================
# SETUP STEPS
# =============================================================================

def check_python_version() -> bool:
    """Check Python version is sufficient."""
    version = sys.version_info[:2]
    if version < PYTHON_VERSION_MIN:
        log(f"Python {PYTHON_VERSION_MIN[0]}.{PYTHON_VERSION_MIN[1]}+ required, found {version[0]}.{version[1]}", "error")
        return False
    log(f"Python {version[0]}.{version[1]} ✓", "success")
    return True


def create_directories() -> bool:
    """Create required directories."""
    log("Creating directories...")
    for dir_name in REQUIRED_DIRS:
        dir_path = PROJECT_ROOT / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
    log(f"Created {len(REQUIRED_DIRS)} directories", "success")
    return True


def create_venv(force: bool = False) -> bool:
    """Create virtual environment."""
    if VENV_PATH.exists():
        if force:
            log("Removing existing venv...", "warn")
            shutil.rmtree(VENV_PATH)
        else:
            log(f"Virtual environment exists at {VENV_PATH}", "info")
            return True
    
    log(f"Creating virtual environment at {VENV_PATH}...")
    code, out, err = run_cmd([sys.executable, "-m", "venv", str(VENV_PATH)])
    
    if code != 0:
        log(f"Failed to create venv: {err}", "error")
        return False
    
    log("Virtual environment created", "success")
    return True


def upgrade_pip() -> bool:
    """Upgrade pip in venv."""
    log("Upgrading pip...")
    pip = get_venv_pip()
    python = get_venv_python()
    
    code, out, err = run_cmd([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    if code != 0:
        log(f"Failed to upgrade pip: {err}", "warn")
        return False
    
    log("Pip upgraded", "success")
    return True


def install_requirements() -> bool:
    """Install the most appropriate requirements file for the current platform."""
    candidates = []
    if sys.platform == "win32":
        candidates = [
            PROJECT_ROOT / "requirements.txt",
            PROJECT_ROOT / "config" / "requirements.txt",
            PROJECT_ROOT / "requirements-production.txt",
            PROJECT_ROOT / "config" / "requirements-production.txt",
        ]
    else:
        candidates = [
            PROJECT_ROOT / "requirements-linux.txt",
            PROJECT_ROOT / "requirements.txt",
            PROJECT_ROOT / "config" / "requirements.txt",
        ]

    req_file = None
    for cand in candidates:
        if cand.exists():
            req_file = cand
            break

    if not req_file:
        log("No suitable requirements*.txt found", "error")
        return False

    log(f"Installing dependencies from {req_file.name} (this may take a few minutes)...")
    pip = get_venv_pip()

    code, out, err = run_cmd([str(pip), "install", "-r", str(req_file)])
    if code != 0:
        log(f"Failed to install requirements: {err[:500]}", "error")
        return False

    log("Dependencies installed", "success")
    return True


def install_playwright() -> bool:
    """Install Playwright browsers."""
    log("Installing Playwright browsers...")
    python = get_venv_python()
    
    code, out, err = run_cmd([str(python), "-m", "playwright", "install", "chromium"])
    if code != 0:
        log(f"Playwright install failed (optional): {err[:200]}", "warn")
        return False
    
    log("Playwright browsers installed", "success")
    return True


def create_env_file() -> bool:
    """Create .env file from template if it doesn't exist."""
    env_file = PROJECT_ROOT / ".env"
    template_file = PROJECT_ROOT / ".env.template"
    example_file = PROJECT_ROOT / ".env.example"
    
    if env_file.exists():
        log(".env file exists", "info")
        return True
    
    if template_file.exists():
        shutil.copy(template_file, env_file)
        log("Created .env from .env.template - please edit with your tokens", "warn")
    elif example_file.exists():
        shutil.copy(example_file, env_file)
        log("Created .env from .env.example - please edit with your API keys", "warn")
    else:
        # Create complete .env
        env_content = """# Larry Agent Environment Variables
# ===================================

# HuggingFace Token (for downloading models)
# Get yours at: https://huggingface.co/settings/tokens
HF_TOKEN=
HUGGINGFACE_TOKEN=

# Brave Search (for web search)
BRAVE_API_KEY=

# GitHub (for GitHub MCP server)
GITHUB_TOKEN=

# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN=

# Ollama
OLLAMA_HOST=http://localhost:11434

# OpenRouter API (optional)
OPENROUTER_API_KEY=
OPENROUTER_MODEL=

# RAG Backend (chroma or postgres)
RAG_BACKEND=chroma

# Disable Telemetry
ANONYMIZED_TELEMETRY=False
CHROMA_TELEMETRY=False
POSTHOG_DISABLED=1
DO_NOT_TRACK=1
TF_ENABLE_ONEDNN_OPTS=0
TF_CPP_MIN_LOG_LEVEL=2
"""
        env_file.write_text(env_content)
        log("Created .env file - add your API keys and HF token", "warn")
    
    return True


def init_databases() -> bool:
    """Initialize SQLite and ChromaDB."""
    log("Initializing databases...")
    python = get_venv_python()
    
    init_code = '''
import sys
sys.path.insert(0, ".")

# Initialize unified context DB
try:
    from unified_context_manager import UnifiedContextManager
    ctx = UnifiedContextManager()
    print("SQLite context DB initialized")
except Exception as e:
    print(f"Context DB: {e}")

# Initialize ChromaDB
try:
    from production_rag import ProductionRAG
    rag = ProductionRAG()
    config = rag.get_config()
    print(f"ChromaDB initialized at {config['chroma_path']}")
except Exception as e:
    print(f"ChromaDB: {e}")
'''
    
    code, out, err = run_cmd([str(python), "-c", init_code])
    if out:
        for line in out.strip().split('\n'):
            log(line, "success" if "initialized" in line.lower() else "info")
    
    return True


def validate_mcp_servers() -> bool:
    """Validate MCP servers can be imported."""
    log("Validating MCP servers...")
    python = get_venv_python()
    
    validate_code = '''
import sys
sys.path.insert(0, ".")

servers = []
errors = []

try:
    from mcp_servers import (
        FilesystemServer, MemoryServer, SQLiteServer,
        BraveSearchServer, PlaywrightServer, TimeServer
    )
    servers.extend(["filesystem", "memory", "sqlite", "brave-search", "playwright", "time"])
except Exception as e:
    errors.append(f"MCP import error: {e}")

print(f"MCP Servers available: {len(servers)}")
for s in servers:
    print(f"  ✓ {s}")
for e in errors:
    print(f"  ✗ {e}")
'''
    
    code, out, err = run_cmd([str(python), "-c", validate_code])
    if out:
        for line in out.strip().split('\n'):
            log(line, "success" if "✓" in line else "info")
    
    return True


def validate_ollama() -> bool:
    """Check if Ollama is running."""
    log("Checking Ollama...")
    
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            log(f"Ollama running with {len(models)} models", "success")
            return True
    except Exception:
        pass
    
    log("Ollama not running - start with 'ollama serve'", "warn")
    return False


def run_tests() -> bool:
    """Run integration tests."""
    log("Running integration tests...")
    python = get_venv_python()
    test_file = PROJECT_ROOT / "test_integration.py"
    
    if not test_file.exists():
        log("test_integration.py not found, skipping tests", "warn")
        return True
    
    code, out, err = run_cmd([str(python), str(test_file)])
    
    if code == 0:
        log("All tests passed", "success")
        return True
    else:
        log(f"Some tests failed: {err[:300]}", "warn")
        return False


def validate_core_modules() -> bool:
    """Validate all core Python modules can be imported."""
    log("Validating core modules...")
    python = get_venv_python()
    
    validate_code = '''
import sys
sys.path.insert(0, ".")

modules_ok = []
modules_fail = []

# Test each core module import
test_modules = [
    ("production_rag", "ProductionRAG"),
    ("web_tools", "WebScraper"),
    ("safe_code_executor", "SafeCodeExecutor"),
    ("universal_file_handler", "UniversalFileHandler"),
    ("cross_platform_paths", "CrossPlatformPathManager"),
    ("model_router", "ModelRouter"),
    ("file_browser", "FileBrowser"),
    ("skill_manager", "SkillManager"),
    ("unified_context_manager", "UnifiedContextManager"),
    ("hardware_profiles", "ProfileManager"),
]

for module_name, class_name in test_modules:
    try:
        mod = __import__(module_name)
        if hasattr(mod, class_name):
            modules_ok.append(module_name)
        else:
            modules_ok.append(f"{module_name} (no {class_name})")
    except Exception as e:
        modules_fail.append(f"{module_name}: {str(e)[:50]}")

print(f"OK: {len(modules_ok)} modules")
for m in modules_ok:
    print(f"  ✓ {m}")
    
if modules_fail:
    print(f"FAILED: {len(modules_fail)} modules")
    for m in modules_fail:
        print(f"  ✗ {m}")
'''
    
    code, out, err = run_cmd([str(python), "-c", validate_code])
    if out:
        for line in out.strip().split('\n'):
            if "✓" in line:
                log(line.strip(), "success")
            elif "✗" in line:
                log(line.strip(), "error")
            else:
                log(line.strip(), "info")
    
    if err and "Error" in err:
        log(f"Module validation errors: {err[:200]}", "warn")
    
    return True


def validate_web_search() -> bool:
    """Test web search functionality."""
    log("Validating web search...")
    python = get_venv_python()
    
    validate_code = '''
import sys
sys.path.insert(0, ".")

try:
    from web_tools import get_web_scraper
    scraper = get_web_scraper()
    if scraper:
        print("✓ Web scraper initialized")
    else:
        print("⚠ Web scraper returned None")
except Exception as e:
    print(f"✗ Web tools error: {e}")

try:
    from mcp_client import get_mcp_toolkit
    mcp = get_mcp_toolkit()
    if mcp:
        tools = mcp.get_available_tools() if hasattr(mcp, "get_available_tools") else []
        print(f"✓ MCP toolkit loaded with {len(tools)} tools")
    else:
        print("⚠ MCP toolkit returned None")
except Exception as e:
    print(f"✗ MCP error: {e}")
'''
    
    code, out, err = run_cmd([str(python), "-c", validate_code])
    if out:
        for line in out.strip().split('\n'):
            if "✓" in line:
                log(line.strip(), "success")
            elif "✗" in line:
                log(line.strip(), "error")
            else:
                log(line.strip(), "warn")
    
    return True


# =============================================================================
# MAIN SETUP FLOW
# =============================================================================

def full_setup(args: argparse.Namespace) -> bool:
    """Run complete setup."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}╔══════════════════════════════════════════════════════════════╗")
    print(f"║         LARRY AGENT - COMPLETE SETUP                         ║")
    print(f"║         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                                   ║")
    print(f"╚══════════════════════════════════════════════════════════════╝{Colors.END}\n")
    
    steps = [
        ("Check Python version", check_python_version),
        ("Create directories", create_directories),
        ("Create virtual environment", lambda: create_venv(args.force_venv)),
        ("Upgrade pip", upgrade_pip),
        ("Install requirements", install_requirements),
        ("Install Playwright", install_playwright),
        ("Create .env file", create_env_file),
        ("Initialize databases", init_databases),
        ("Validate core modules", validate_core_modules),
        ("Validate MCP servers", validate_mcp_servers),
        ("Validate web search", validate_web_search),
        ("Check Ollama", validate_ollama),
    ]
    
    if args.test:
        steps.append(("Run tests", run_tests))
    
    results = []
    for name, func in steps:
        print(f"\n{Colors.BOLD}Step: {name}{Colors.END}")
        try:
            success = func()
            results.append((name, success))
        except Exception as e:
            log(f"Error: {e}", "error")
            results.append((name, False))
    
    # Summary
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}SETUP SUMMARY{Colors.END}")
    print(f"{'='*60}")
    
    passed = sum(1 for _, s in results if s)
    total = len(results)
    
    for name, success in results:
        status = f"{Colors.GREEN}✓{Colors.END}" if success else f"{Colors.RED}✗{Colors.END}"
        print(f"  {status} {name}")
    
    print(f"\n{Colors.BOLD}Result: {passed}/{total} steps completed{Colors.END}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Setup complete!{Colors.END}")
        print(f"\n{Colors.CYAN}Next steps:{Colors.END}")
        print(f"  1. Edit .env with your API keys (BRAVE_API_KEY, GITHUB_TOKEN)")
        print(f"  2. Start Ollama: ollama serve")
        print(f"  3. Run the agent: python agent_v2.py")
        print(f"  4. Or use: python activate_all.py")
        return True
    else:
        print(f"\n{Colors.YELLOW}Some steps failed - check logs above{Colors.END}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Larry Agent Setup")
    parser.add_argument("--force-venv", action="store_true", help="Recreate venv even if exists")
    parser.add_argument("--venv-only", action="store_true", help="Only create venv")
    parser.add_argument("--deps-only", action="store_true", help="Only install dependencies")
    parser.add_argument("--validate", action="store_true", help="Only validate existing setup")
    parser.add_argument("--test", action="store_true", help="Run tests after setup")
    parser.add_argument("--start", action="store_true", help="Start services after setup")
    
    args = parser.parse_args()
    
    os.chdir(PROJECT_ROOT)
    
    if args.venv_only:
        check_python_version()
        create_venv(args.force_venv)
    elif args.deps_only:
        install_requirements()
    elif args.validate:
        validate_mcp_servers()
        validate_ollama()
    else:
        success = full_setup(args)
        
        if success and args.start:
            print(f"\n{Colors.CYAN}Starting services...{Colors.END}")
            python = get_venv_python()
            subprocess.Popen([str(python), "agent_v2.py"], cwd=PROJECT_ROOT)


if __name__ == "__main__":
    main()
