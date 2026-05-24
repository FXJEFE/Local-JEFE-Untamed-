#!/usr/bin/env python3
"""
Comprehensive activation script for the Local Larry runtime.

This script:
1. Syncs refactored modules from REFACTORclaude to the live tree
2. Creates a fresh virtual environment on each run
3. Installs all production dependencies
4. Initializes databases (SQLite for context, ChromaDB for RAG)
5. Runs setup, integration tests, and validation suites
6. Performs network security scans (ports, remote connections)
7. Validates all MCP servers
8. Launches agent and Telegram bot runtimes

Usage:
    python activate_runtime.py                 # Full activation with runtime launch
    python activate_runtime.py --test-only     # Just tests, no runtime
    python activate_runtime.py --sync-only     # Only sync refactored modules
    python activate_runtime.py --verbose       # Detailed output
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Canonical Larry path bootstrap (ensures correct BASE_DIR, chdir, and imports) ---
try:
    import larry_paths
    larry_paths.bootstrap(chdir=True, add_to_sys_path=True)
except Exception as _bp:
    print(f"[activate_runtime] Warning: could not bootstrap larry_paths: {_bp}")

# Modules to sync from REFACTORclaude to root (source modules)
REFACTOR_SOURCE_DIR = "REFACTORclaude"
REFACTOR_MODULES = [
    "file_browser.py",
    "skill_manager.py",
    "setup_refactored.py",
    "validate_system.py",
]

# Core production modules that must exist in root (already present or synced)
REQUIRED_MODULES = [
    "unified_context_manager.py",
    "sandbox_manager.py",
    "token_manager.py",
    "model_router.py",
    "production_rag.py",
    "safe_code_executor.py",
    "universal_file_handler.py",
    "hardware_profiles.py",
    "cross_platform_paths.py",
    "mcp_client.py",
    "file_browser.py",
    "skill_manager.py",
]

RUNTIME_TARGETS = [
    ("agent", "agent_v2.py"),
    ("telegram", "telegram_bot.py")
]


class ActivationManager:
    """Coordinate environment setup, validation, and runtime start."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = Path(__file__).resolve().parent
        self.venv_path = self.root / args.venv_name
        scripts_dir = "Scripts" if os.name == "nt" else "bin"
        self.venv_python = self.venv_path / scripts_dir / ("python.exe" if os.name == "nt" else "python")
        self.report: List[Tuple[str, bool, str]] = []
        self.runtime_processes: List[Tuple[str, int, Path]] = []

    def log(self, message: str) -> None:
        print(f"[activate] {message}")

    def record(self, name: str, success: bool, detail: str = "") -> None:
        self.report.append((name, success, detail))
        status = "OK" if success else "FAIL"
        self.log(f"{status} :: {name}")
        if detail and (self.args.verbose or not success):
            for line in detail.splitlines():
                self.log(f"    {line}")

    def sync_refactored_modules(self) -> None:
        """Sync modules from REFACTORclaude to root for unified codebase."""
        if self.args.no_sync:
            self.record("Sync refactored modules", True, "Skipped by flag")
            return
        
        source_dir = self.root / REFACTOR_SOURCE_DIR
        if not source_dir.exists():
            self.record("Sync refactored modules", True, "No REFACTORclaude dir - using existing modules")
            return
        
        synced = []
        for module in REFACTOR_MODULES:
            src = source_dir / module
            dst = self.root / module
            if src.exists():
                shutil.copy2(src, dst)
                synced.append(module)
        
        if synced:
            self.record("Sync refactored modules", True, f"Synced {len(synced)} modules: {', '.join(synced)}")
        else:
            self.record("Sync refactored modules", True, "No new modules to sync")

    def check_required_modules(self) -> None:
        """Check that all required production modules are present."""
        missing = []
        for module in REQUIRED_MODULES:
            path = self.root / module
            if not path.exists():
                missing.append(module)
        if missing:
            detail = "Missing modules: " + ", ".join(missing)
            self.record("Required modules check", False, detail)
        else:
            self.record("Required modules check", True, f"All {len(REQUIRED_MODULES)} required modules present")

    def recreate_venv(self) -> None:
        if self.venv_path.exists():
            shutil.rmtree(self.venv_path)
            self.log(f"Removed existing venv at {self.venv_path}")
        subprocess.run([sys.executable, "-m", "venv", str(self.venv_path)], check=True)
        self.record("Virtual environment", True, f"Created at {self.venv_path}")

    def install_dependencies(self) -> None:
        candidates = [
            self.root / "requirements-production.txt",
            self.root / "requirements.txt"
        ]
        requirements = next((p for p in candidates if p.exists()), None)
        if not requirements:
            self.record("Dependency install", False, "No requirements file found")
            raise FileNotFoundError("requirements file missing")
        subprocess.run([str(self.venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True, cwd=self.root)
        subprocess.run([str(self.venv_python), "-m", "pip", "install", "-r", str(requirements)], check=True, cwd=self.root)
        self.record("Dependency install", True, f"Installed from {requirements.name}")

    def run_script(self, script: str, description: str, extra_args: Optional[List[str]] = None) -> None:
        target = self.root / script
        if not target.exists():
            self.record(description, True, f"Skipped (no {script})")
            return  # Don't fail, just skip if script doesn't exist
        cmd = [str(self.venv_python), str(target)]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True)
        success = result.returncode == 0
        detail = result.stdout.strip() or result.stderr.strip()
        self.record(description, success, detail[-2000:])
        if not success:
            raise RuntimeError(f"{description} failed")

    def run_inline(self, code: str, description: str, parse_json: bool = False) -> Tuple[bool, Optional[Dict]]:
        cmd = [str(self.venv_python), "-c", textwrap.dedent(code)]
        result = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True)
        success = result.returncode == 0
        detail = result.stdout.strip() or result.stderr.strip()
        data: Optional[Dict] = None
        if parse_json and success and detail:
            try:
                data = json.loads(detail.splitlines()[-1])
            except json.JSONDecodeError:
                data = None
        self.record(description, success, detail[-2000:])
        if not success:
            raise RuntimeError(f"{description} failed")
        return success, data

    def validate_rag(self) -> None:
        code = """
        import json
        from production_rag import get_rag
        rag = get_rag()
        print(json.dumps(rag.get_stats()))
        """
        _, data = self.run_inline(code, "RAG health check", parse_json=True)
        if data:
            self.log(f"RAG documents: {data.get('total_documents')}")

    def network_scan(self) -> None:
        """Network security scan - checks open ports, remote connections, and suspicious activity."""
        if self.args.skip_network:
            self.record("Network scan", True, "Skipped by flag")
            return
        
        # Run PowerShell network diagnostics on Windows
        ps_script = self.root / "check-network.ps1"
        ran_script = False
        if os.name == "nt" and ps_script.exists() and shutil.which("pwsh"):
            cmd = [
                "pwsh", "-ExecutionPolicy", "Bypass", "-File", str(ps_script),
                "-ScanTarget", self.args.scan_target,
                "-Ports", self.args.ports
            ]
            result = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True)
            ran_script = True
            self.record("Network diagnostics (PowerShell)", result.returncode == 0, result.stdout[-2000:])
        
        # Python-based network analysis (works on all platforms)
        code = """
        import json
        try:
            import psutil
        except ImportError:
            print(json.dumps({"error": "psutil missing"}))
        else:
            summary = {
                "listening": 0,
                "listening_ports": [],
                "remote": [],
                "suspicious": [],
                "established": 0
            }
            # Known safe remote IPs (localhost, private ranges)
            safe_prefixes = ["127.", "192.168.", "10.", "172.16.", "172.17.", "172.18.", 
                           "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                           "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31."]
            
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN":
                    summary["listening"] += 1
                    summary["listening_ports"].append(conn.laddr.port)
                elif conn.status == "ESTABLISHED":
                    summary["established"] += 1
                    if conn.raddr:
                        remote_ip = conn.raddr.ip
                        is_safe = any(remote_ip.startswith(p) for p in safe_prefixes)
                        conn_info = {
                            "local": f"{conn.laddr.ip}:{conn.laddr.port}",
                            "remote": f"{remote_ip}:{conn.raddr.port}",
                            "status": conn.status,
                            "pid": conn.pid
                        }
                        summary["remote"].append(conn_info)
                        if not is_safe:
                            # Flag external connections as potentially suspicious
                            try:
                                proc = psutil.Process(conn.pid) if conn.pid else None
                                conn_info["process"] = proc.name() if proc else "unknown"
                            except:
                                conn_info["process"] = "unknown"
                            summary["suspicious"].append(conn_info)
            
            summary["listening_ports"] = sorted(set(summary["listening_ports"]))[:20]
            summary["remote_count"] = len(summary["remote"])
            summary["suspicious_count"] = len(summary["suspicious"])
            summary["remote"] = summary["remote"][:15]  # Limit output
            summary["suspicious"] = summary["suspicious"][:10]
            print(json.dumps(summary))
        """
        success, data = self.run_inline(code, "Network diagnostics (Python)", parse_json=True)
        if success and data:
            if data.get("error"):
                self.log("Consider installing psutil: pip install psutil")
            else:
                self.log(f"Listening ports: {len(data.get('listening_ports', []))} ({', '.join(map(str, data.get('listening_ports', [])[:10]))}...)")
                self.log(f"Established connections: {data.get('established', 0)}")
                
                suspicious = data.get("suspicious", [])
                if suspicious:
                    self.log(f"⚠️  EXTERNAL CONNECTIONS DETECTED: {len(suspicious)}")
                    for conn in suspicious[:5]:
                        self.log(f"   • {conn.get('remote')} via {conn.get('process', 'unknown')}")
                else:
                    self.log("✅ No suspicious external connections detected")
        
        if not ran_script and (not data or data.get("error")):
            self.log("Consider installing PowerShell 7 or psutil for detailed checks")

    def test_mcp(self) -> None:
        """Test all MCP servers defined in mcp.json."""
        if self.args.skip_mcp:
            self.record("MCP validation", True, "Skipped by flag")
            return
        
        code = """
        import json
        from pathlib import Path
        
        # First, load mcp.json to see configured servers
        mcp_config = []
        mcp_path = Path("mcp.json")
        if mcp_path.exists():
            with open(mcp_path) as f:
                mcp_config = json.load(f)
        
        # Test MCP toolkit
        from mcp_client import get_mcp_toolkit
        toolkit = get_mcp_toolkit()
        status = toolkit.get_status()
        
        # Build detailed report
        report = {
            "configured_servers": len(mcp_config),
            "enabled_servers": sum(1 for s in mcp_config if s.get("enabled", False)),
            "toolkit_status": status,
            "available_tools": toolkit.get_available_tools(),
            "server_details": []
        }
        
        for server in mcp_config:
            name = server.get("name", "unknown")
            enabled = server.get("enabled", False)
            transport = server.get("transport", "stdio")
            active = status.get(name, False) or name in report["available_tools"]
            
            report["server_details"].append({
                "name": name,
                "enabled": enabled,
                "transport": transport,
                "active": active
            })
        
        print(json.dumps(report))
        """
        _, data = self.run_inline(code, "MCP validation", parse_json=True)
        if data:
            self.log(f"Configured MCP servers: {data.get('configured_servers', 0)} ({data.get('enabled_servers', 0)} enabled)")
            
            active_tools = data.get("available_tools", [])
            self.log(f"Active MCP tools: {', '.join(active_tools) if active_tools else 'none'}")
            
            # Report on each server
            for server in data.get("server_details", []):
                status_icon = "✅" if server.get("active") else ("⏸️" if not server.get("enabled") else "❌")
                self.log(f"   {status_icon} {server.get('name')}: {'active' if server.get('active') else 'inactive'} ({server.get('transport')})")

    def start_runtime(self) -> None:
        if self.args.test_only or self.args.no_runtime:
            self.record("Runtime launch", True, "Skipped (test-only)")
            return
        started = []
        for name, script in RUNTIME_TARGETS:
            target = self.root / script
            if not target.exists():
                self.record(f"Start {name}", False, f"Missing {script}")
                continue
            log_path = self.root / "logs" / f"{name}_activation.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(
                [str(self.venv_python), str(target)],
                cwd=self.root,
                stdout=log_file,
                stderr=log_file
            )
            log_file.close()
            time.sleep(self.args.runtime_grace)
            if proc.poll() is None:
                started.append((name, proc.pid, log_path))
            else:
                with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                    tail = " | ".join(handle.read().strip().splitlines()[-10:])
                self.record(f"Start {name}", False, f"Exited early: {tail}")
        if started:
            detail = ", ".join(f"{name}(pid={pid})" for name, pid, _ in started)
            self.runtime_processes = started
            self.record("Runtime launch", True, detail)
        else:
            self.record("Runtime launch", False, "No processes running")

    def run(self) -> None:
        steps = [
            ("Sync refactored modules", self.sync_refactored_modules),
            ("Required modules check", self.check_required_modules),
            ("Virtual environment", self.recreate_venv),
            ("Dependency install", self.install_dependencies),
            ("Setup script (unified)", lambda: self.run_script("setup_unified.py", "Setup script (unified)")),
            ("Setup script (refactored)", lambda: self.run_script("setup_refactored.py", "Setup script (refactored)")),
            ("Integration tests", lambda: self.run_script("test_integration.py", "Integration tests")),
            ("Validation suite", lambda: self.run_script("validate_system.py", "Validation suite")),
            ("RAG health", self.validate_rag),
            ("Network diagnostics", self.network_scan),
            ("MCP validation", self.test_mcp),
            ("Runtime launch", self.start_runtime),
        ]
        
        if self.args.sync_only:
            # Only run sync step
            steps = [("Sync refactored modules", self.sync_refactored_modules)]
        
        for name, func in steps:
            try:
                func()
            except Exception as exc:
                self.log(f"Step '{name}' raised: {exc}")
                if self.args.fail_fast:
                    self.log("Fail-fast enabled; aborting remaining steps")
                    break
        self.print_summary()
        if any(not success for _, success, _ in self.report):
            sys.exit(1)

    def print_summary(self) -> None:
        print("\n" + "=" * 70)
        print("Activation Summary")
        print("=" * 70)
        for name, success, detail in self.report:
            status = "✅" if success else "❌"
            info = f" - {detail}" if detail and self.args.verbose else ""
            print(f"{status} {name}{info}")
        if self.runtime_processes:
            print("\nActive runtime processes:")
            for name, pid, log_path in self.runtime_processes:
                print(f"  • {name}: pid={pid}, log={log_path}")
        print("=" * 70 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Activate Local Larry runtime with full setup, validation, and security checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python activate_runtime.py                    # Full activation
  python activate_runtime.py --test-only        # Tests only, no runtime launch
  python activate_runtime.py --sync-only        # Only sync refactored modules
  python activate_runtime.py --verbose          # Detailed output
  python activate_runtime.py --skip-network     # Skip network security scan
        """
    )
    parser.add_argument("--ports", default="80,443,8080,3000,5432,27017,11434,22,3389", 
                        help="Ports to scan for network diagnostics")
    parser.add_argument("--scan-target", default="localhost", help="Target host for port scan")
    parser.add_argument("--skip-network", action="store_true", help="Skip network diagnostics")
    parser.add_argument("--skip-mcp", action="store_true", help="Skip MCP validation")
    parser.add_argument("--test-only", action="store_true", help="Do not launch agent/telegram runtime")
    parser.add_argument("--no-runtime", action="store_true", help="Alias for --test-only")
    parser.add_argument("--sync-only", action="store_true", help="Only sync refactored modules, no other steps")
    parser.add_argument("--no-sync", action="store_true", help="Skip syncing refactored modules")
    parser.add_argument("--runtime-grace", type=float, default=4.0, 
                        help="Seconds to wait after launching runtime processes")
    parser.add_argument("--venv-name", default=".activation_env", 
                        help="Folder name for the freshly-created virtual environment")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing step")
    parser.add_argument("--verbose", action="store_true", help="Print detailed logs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manager = ActivationManager(args)
    manager.run()


if __name__ == "__main__":
    main()
