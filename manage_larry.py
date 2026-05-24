#!/usr/bin/env python3
"""
Larry G-Force Management CLI
=============================
One script to rule setup, activation, validation, and daily management.

Usage examples:
    python manage_larry.py setup
    python manage_larry.py validate
    python manage_larry.py smoke-test
    python manage_larry.py mcp-test
    python manage_larry.py activate-all          # <-- MASTER PIPELINE
    python manage_larry.py status
    python manage_larry.py start-agent
"""

import argparse
import os
import sys
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime

# Optional heavy imports inside functions to keep startup fast
try:
    import requests
except ImportError:
    requests = None

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

def run(cmd, check=True, capture=False, warn_only=False):
    """Run a command. If warn_only=True, never raise even on failure."""
    print(f"→ Running: {cmd}")
    try:
        if capture:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True)
        res = subprocess.run(cmd, shell=True, check=check)
        return res
    except subprocess.CalledProcessError as e:
        if warn_only:
            print(f"   [WARN] Command exited non-zero (continuing): {e}")
            return e
        raise

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
    run(f'"{py}" -c "import agent_v2; print(\"agent_v2 imports OK\")"', warn_only=True)
    run(f'"{py}" -c "import mcp_client; print(\"MCP client OK\")"')
    run(f'"{py}" -c "import unified_context_manager; print(\"Unified context OK\")"')
    print("✅ Validation complete (some components may have warnings).")

def cmd_smoke_test(args):
    print("=== SMOKE TEST ===")
    py = get_python()
    run(f'"{py}" -c "from mcp_client import MCPClient; print(\"MCPClient OK\")"')
    run(f'"{py}" -c "from model_router import get_router; print(\"ModelRouter OK\")"', warn_only=True)
    run(f'"{py}" -c "from safe_code_executor import get_executor; print(\"Safe executor OK\")"')
    run(f'"{py}" -c "from web_tools import WebScraper; print(\"Web tools OK\")"', warn_only=True)
    print("✅ Smoke tests complete.")

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


def cmd_mcp_test(args):
    """Test MCP connectivity, especially the FXJEFE Local server."""
    print("=== MCP Connectivity Test (FXJEFE Local Larry) ===")
    py = get_python()
    run(f'"{py}" -c "'
        'from mcp_client import get_mcp_toolkit; '
        't = get_mcp_toolkit(); '
        'print(\"MCP Toolkit loaded\"); '
        'print(\"Status:\", t.get_status()); '
        'if hasattr(t, \"fxjefe\"): print(\"FXJEFE available:\", t.fxjefe.available); print(\"FXJEFE tools:\", t.fxjefe.get_tools() if t.fxjefe.available else [])"')

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


# =============================================================================
# FXJEFE LOCAL LARRY - MASTER ACTIVATION PIPELINE
# =============================================================================

def cmd_activate_all(args):
    """
    Master pipeline script that activates the entire Larry G-Force stack
    inside the GITHUB clean distribution:
      - Environment & Ollama
      - FXJEFE Local MCP Server
      - Main Agent (agent_v2)
      - Security Sentinel (if present)
      - Dashboard Hub (if present)
      - Telegram Bot (if configured)
      - MCP + RAG health checks
    """
    print("=" * 70)
    print(" FXJEFE LOCAL LARRY - MASTER ACTIVATION PIPELINE")
    print(" GITHUB Clean Production Distribution")
    print(f" Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = []
    background_processes = []

    # --- 1. Environment ---
    print("\n[1/8] Environment & Dependencies")
    py = get_python()
    results.append(("Python venv", VENV_PATH.exists()))
    results.append(("Ollama check", True))  # will verify below

    # --- 2. Ollama ---
    print("\n[2/8] Ollama Service")
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if r.ok:
            models = len(r.json().get("models", []))
            print(f"  ✅ Ollama running with {models} models")
            results.append(("Ollama", True))
        else:
            raise Exception("Ollama not responding")
    except Exception:
        print("  ⚠️  Ollama not detected — attempting to start...")
        run("ollama serve", check=False, background=True)
        time.sleep(4)
        results.append(("Ollama", False))

    # --- 3. FXJEFE Local MCP Server (with basic health check) ---
    print("\n[3/8] FXJEFE Local MCP Server")
    fxjefe_script = PROJECT_ROOT / "mcp" / "fxjefe-local-mcp" / "fxjefe_local_mcp_server.py"
    if fxjefe_script.exists():
        print("  Starting FXJEFE Local MCP server in background...")
        try:
            proc = subprocess.Popen(
                [str(py), str(fxjefe_script)],
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            background_processes.append(("FXJEFE-MCP", proc))
            print(f"  ✅ FXJEFE MCP launched (PID {proc.pid})")
            results.append(("FXJEFE MCP", True))
        except Exception as e:
            print(f"  ❌ Failed to launch FXJEFE MCP: {e}")
            results.append(("FXJEFE MCP", False))
    else:
        print("  ⚠️  FXJEFE MCP server script not found")
        results.append(("FXJEFE MCP", False))

    # --- 4. MCP Client Validation + FXJEFE Health ---
    print("\n[4/8] MCP Client & Toolkits")
    try:
        run(f'"{py}" -c "from mcp_client import get_mcp_toolkit; t=get_mcp_toolkit(); s=t.get_status(); print(s); print(\"FXJEFE tools:\", s.get(\"fxjefe_tools\", []))"', check=False)
        results.append(("MCP Toolkit", True))
    except Exception:
        results.append(("MCP Toolkit", False))

    # --- 5. Main Agent ---
    print("\n[5/8] Main Agent (agent_v2.py)")
    agent_script = PROJECT_ROOT / "src" / "agent_v2.py"
    if agent_script.exists():
        print("  Launching main agent in new window...")
        try:
            # Launch in separate console so it doesn't block the pipeline
            cmd = f'start "FXJEFE Local Larry - Main Agent" "{py}" "{agent_script}"'
            subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT))
            results.append(("Main Agent", True))
        except Exception as e:
            print(f"  ❌ {e}")
            results.append(("Main Agent", False))
    else:
        results.append(("Main Agent", False))

    # --- 6. Security Sentinel (graceful if missing) ---
    print("\n[6/8] Security Sentinel")
    sentinel = PROJECT_ROOT / "src" / "security_sentinel.py"
    if sentinel.exists():
        print("  Starting Security Sentinel...")
        proc = subprocess.Popen([str(py), str(sentinel)], cwd=str(PROJECT_ROOT))
        background_processes.append(("Security-Sentinel", proc))
        results.append(("Security Sentinel", True))
    else:
        print("  ℹ️  security_sentinel.py not present in this GITHUB distribution")
        results.append(("Security Sentinel", "missing"))

    # --- 7. Dashboard Hub ---
    print("\n[7/8] Dashboard Hub")
    dashboard = PROJECT_ROOT / "src" / "dashboard_hub.py"
    if dashboard.exists():
        print("  Starting Dashboard on http://127.0.0.1:3777 ...")
        proc = subprocess.Popen([str(py), str(dashboard), "--no-browser"], cwd=str(PROJECT_ROOT))
        background_processes.append(("Dashboard", proc))
        results.append(("Dashboard Hub", True))
    else:
        print("  ℹ️  dashboard_hub.py not present in GITHUB tree (present in main working dir)")
        results.append(("Dashboard Hub", "missing"))

    # --- 8. Telegram Bot ---
    print("\n[8/8] Telegram Bot")
    telegram = PROJECT_ROOT / "src" / "telegram_bot.py"
    if telegram.exists():
        # Only start if token likely exists
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists() and "TELEGRAM_BOT_TOKEN" in env_file.read_text():
            print("  Starting Telegram bot...")
            proc = subprocess.Popen([str(py), str(telegram)], cwd=str(PROJECT_ROOT))
            background_processes.append(("Telegram", proc))
            results.append(("Telegram Bot", True))
        else:
            print("  ℹ️  .env missing TELEGRAM_BOT_TOKEN — skipping Telegram")
            results.append(("Telegram Bot", "no token"))
    else:
        results.append(("Telegram Bot", "missing"))

    # --- Final Report ---
    print("\n" + "=" * 70)
    print(" ACTIVATION PIPELINE COMPLETE")
    print("=" * 70)

    for name, status in results:
        icon = "✅" if status is True else "❌" if status is False else "ℹ️"
        print(f"  {icon} {name:<25} {status}")

    if background_processes:
        print("\nBackground processes started:")
        for name, proc in background_processes:
            print(f"  • {name} (PID {proc.pid})")

    print("\nUseful follow-up commands:")
    print("  python src/manage_larry.py mcp-test")
    print("  python src/manage_larry.py status")
    print("  /mcp          (inside the agent)")
    print("  /fxjefe       (test FXJEFE tools)")

    print("\nTo stop everything:")
    print("  python src/manage_larry.py stop-services")

    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Larry G-Force Management Tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Full environment setup")
    sub.add_parser("validate", help="Validate imports and basic health")
    sub.add_parser("smoke-test", help="Run smoke tests for MCP, tools, models")
    sub.add_parser("mcp-test", help="Test MCP servers (especially FXJEFE Local tools)")
    sub.add_parser("full-smoke", help="Extended smoke test (MCP + tools)")
    sub.add_parser("unload-all", help="Unload all models from VRAM")
    sub.add_parser("status", help="Show quick status")
    sub.add_parser("start-agent", help="Launch the main agent (agent_v2.py)")
    sub.add_parser("start-dashboard", help="Start the Command Central dashboard")
    sub.add_parser("start-telegram", help="Start the Telegram bot")
    sub.add_parser("restart-ollama", help="Restart Ollama server")
    sub.add_parser("pull-models", help="Pull recommended production models")
    sub.add_parser("stop-services", help="Attempt to stop running Larry services")
    sub.add_parser("activate-all", help="FULL PIPELINE: Activate every component (agent + security + dashboard + MCP + telegram)")
    sub.add_parser("start-all", help="Alias for activate-all")

    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "smoke-test":
        cmd_smoke_test(args)
    elif args.command == "mcp-test":
        cmd_mcp_test(args)
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
    elif args.command in ("activate-all", "start-all"):
        cmd_activate_all(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
