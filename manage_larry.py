#!/usr/bin/env python3
"""
Larry G-Force Management CLI
=============================
One script to rule setup, activation, validation, and daily management.

Usage examples:
    python manage_larry.py setup
    python manage_larry.py validate
    python manage_larry.py smoke-test
    python manage_larry.py status
    python manage_larry.py unload-all
    python manage_larry.py start-agent
"""

import argparse
import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Bootstrap using our canonical path system
try:
    import larry_paths
    larry_paths.bootstrap(chdir=True, add_to_sys_path=True)
    PROJECT_ROOT = larry_paths.BASE_DIR
except Exception:
    PROJECT_ROOT = Path(__file__).parent.resolve()

VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

def get_python():
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable

def run(cmd, check=True, capture=False):
    print(f"→ Running: {cmd}")
    if capture:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return subprocess.run(cmd, shell=True, check=check)

def cmd_setup(args):
    print("=== LARRY G-FORCE SETUP ===")
    py = get_python()
    if not (PROJECT_ROOT / ".venv").exists():
        run(f'"{sys.executable}" -m venv .venv')
    run(f'"{get_python()}" -m pip install --upgrade pip')
    run(f'"{get_python()}" -m pip install -r requirements.txt')
    run(f'"{get_python()}" -m playwright install chromium --with-deps')
    run(f'"{get_python()}" setup_larry.py')
    print("\n✅ Setup complete. Edit .env then run 'python manage_larry.py validate'")

def cmd_validate(args):
    print("=== VALIDATION ===")
    py = get_python()
    run(f'"{py}" -c "import larry_paths; print(\"larry_paths OK\")"')
    run(f'"{py}" -c "import agent_v2; print(\"agent_v2 imports OK\")"')
    run(f'"{py}" -c "import mcp_client; print(\"MCP client OK\")"')
    run(f'"{py}" -c "import unified_context_manager; print(\"Unified context OK\")"')
    print("✅ Basic imports validated.")

def cmd_smoke_test(args):
    print("=== SMOKE TEST ===")
    py = get_python()
    # Test MCP
    run(f'"{py}" -c "from mcp_client import MCPClient; print(\"MCPClient OK\")"')
    # Test model router
    run(f'"{py}" -c "from model_router import get_router; print(\"ModelRouter OK\")"')
    # Test safe executor
    run(f'"{py}" -c "from safe_code_executor import get_executor; print(\"Safe executor OK\")"')
    # Test web tools
    run(f'"{py}" -c "from web_tools import WebScraper; print(\"Web tools OK\")"')
    print("✅ Smoke tests passed (imports + basic objects).")

def cmd_unload_all(args):
    print("Unloading all models from VRAM...")
    py = get_python()
    # This calls the dashboard endpoint if running, otherwise uses direct ollama
    try:
        run(f'"{py}" -c "'
            'import requests; '
            'r = requests.post(\"http://127.0.0.1:3777/api/ollama/stop\", timeout=30); '
            'print(r.json())"')
    except Exception as e:
        print(f"Dashboard not reachable or error: {e}")
        print("Trying direct ollama stop for common models...")
        for model in ["dolphin-mixtral:8x7b", "qwen2.5:14b-instruct", "llama3.3:70b"]:
            run(f"ollama stop {model}", check=False)

def cmd_status(args):
    print("=== LARRY STATUS ===")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Venv python: {VENV_PYTHON} (exists={VENV_PYTHON.exists()})")
    print(f"Ollama running check: ", end="")
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        print("YES" if r.ok else "NO")
    except:
        print("NO (Ollama not reachable)")

def cmd_start_agent(args):
    py = get_python()
    print("Starting Larry Agent (agent_v2.py)...")
    run(f'"{py}" agent_v2.py')

def cmd_full_smoke(args):
    """More thorough smoke test including MCP and basic tool calls."""
    print("=== FULL SMOKE TEST ===")
    py = get_python()
    smoke_script = PROJECT_ROOT / "smoke_test.py"
    if smoke_script.exists():
        run(f'"{py}" "{smoke_script}"')
    else:
        cmd_smoke_test(args)
        run(f'"{py}" -c "'
            'from mcp_client import MCPClient; '
            'c = MCPClient(); '
            'print(\"MCP servers loaded:\", len(c.servers) if hasattr(c, \"servers\") else \"N/A\")"')
    print("✅ Extended smoke test finished.")

def cmd_start_dashboard(args):
    print("Starting Dashboard via launcher...")
    bat = PROJECT_ROOT / "launch_dashboard.bat"
    if bat.exists():
        run(f'start "" "{bat}"', check=False)
    else:
        py = get_python()
        run(f'"{py}" dashboard_hub.py --no-browser')

def cmd_start_telegram(args):
    py = get_python()
    print("Starting Telegram Bot...")
    run(f'"{py}" telegram_bot.py')

def cmd_restart_ollama(args):
    print("Restarting Ollama service...")
    run("ollama serve", check=False)  # Will fail if already running, that's ok
    print("If Ollama was running, you may need to stop it manually first (taskkill /F /IM ollama.exe)")

def cmd_pull_models(args):
    print("Pulling recommended production models...")
    models = [
        "dolphin-mixtral:8x7b",
        "nomic-embed-text",
        "qwen2.5:14b-instruct",
        "qwen3-coder:14b",
        "llama3.2:latest"
    ]
    for m in models:
        run(f"ollama pull {m}", check=False)
    print("✅ Model pull complete (some may have failed if already present).")

def cmd_stop_services(args):
    print("Attempting to stop known Larry-related processes...")
    run('taskkill /F /IM python.exe /FI "WINDOWTITLE eq *agent_v2*"', check=False)
    run('taskkill /F /IM python.exe /FI "WINDOWTITLE eq *telegram_bot*"', check=False)
    run('taskkill /F /IM ollama.exe', check=False)
    print("Note: This is best-effort on Windows.")

def main():
    parser = argparse.ArgumentParser(description="Larry G-Force Management Tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Full environment setup")
    sub.add_parser("validate", help="Validate imports and basic health")
    sub.add_parser("smoke-test", help="Run smoke tests for MCP, tools, models")
    sub.add_parser("full-smoke", help="Extended smoke test (MCP + tools)")
    sub.add_parser("unload-all", help="Unload all models from VRAM")
    sub.add_parser("status", help="Show quick status")
    sub.add_parser("start-agent", help="Launch the main agent (agent_v2.py)")
    sub.add_parser("start-dashboard", help="Start the Command Central dashboard")
    sub.add_parser("start-telegram", help="Start the Telegram bot")
    sub.add_parser("restart-ollama", help="Restart Ollama server")
    sub.add_parser("pull-models", help="Pull recommended production models")
    sub.add_parser("stop-services", help="Attempt to stop running Larry services")

    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "smoke-test":
        cmd_smoke_test(args)
    elif args.command == "full-smoke":
        cmd_full_smoke(args)
    elif args.command == "unload-all":
        cmd_unload_all(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "start-agent":
        cmd_start_agent(args)
    elif args.command == "start-dashboard":
        cmd_start_dashboard(args)
    elif args.command == "start-telegram":
        cmd_start_telegram(args)
    elif args.command == "restart-ollama":
        cmd_restart_ollama(args)
    elif args.command == "pull-models":
        cmd_pull_models(args)
    elif args.command == "stop-services":
        cmd_stop_services(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
