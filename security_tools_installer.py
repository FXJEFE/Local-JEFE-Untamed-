#!/usr/bin/env python3
"""
Security Tools Installer for Local Larry (Windows-first)
- Uses winget (preferred, built-in on Win10/11)
- Falls back to Chocolatey (choco)
- Handles Python tools via pip
- Clear guidance for tools that need WSL Kali

Commands exposed to the agent:
    install_security_tools(all_missing=False, specific_tool=None)
    get_missing_security_tools()
    refresh_tool_availability()
"""

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# Import the canonical TOOLS registry (this file lives next to kali_tools.py)
try:
    from kali_tools import TOOLS, is_installed as _is_installed
except ImportError:
    # Fallback if imported differently
    TOOLS = {}
    def _is_installed(t): return False

# ─────────────────────────────────────────────────────────────────────────────
# Package mappings (Windows)
# ─────────────────────────────────────────────────────────────────────────────

WINGET_MAP: Dict[str, str] = {
    "nmap": "nmap",
    "gobuster": "gobuster",           # community package or Go
    "sqlmap": "sqlmap",               # some manifests have it
    "john": "john-the-ripper",
    "hashcat": "hashcat",
    "curl": "curl",                   # usually already present
    "whois": "whois",                 # sysinternals or others
    "dig": "bind",                    # BIND tools
    "host": "bind",
}

CHOCO_MAP: Dict[str, str] = {
    "nmap": "nmap",
    "gobuster": "gobuster",
    "sqlmap": "sqlmap",
    "john": "john-the-ripper",
    "hashcat": "hashcat",
    "curl": "curl",
    "dig": "bind-tools",
    "host": "bind-tools",
    "masscan": "masscan",
}

PYTHON_TOOLS = {"sqlmap"}  # sqlmap can be installed via pip as well

# Tools that are realistically best run via WSL Kali on Windows
WSL_RECOMMENDED = {
    "nikto", "dirb", "wfuzz", "enum4linux", "smbclient",
    "arp-scan", "dnsenum", "searchsploit", "masscan"
}

# Tools that have decent native Windows builds or Python ports
NATIVE_FRIENDLY = {"nmap", "gobuster", "sqlmap", "john", "hashcat", "curl", "whois", "dig", "host"}


def _has_winget() -> bool:
    return shutil.which("winget") is not None


def _has_choco() -> bool:
    return shutil.which("choco") is not None


def _run_command(cmd: List[str], timeout: int = 300, shell: bool = False) -> Tuple[bool, str]:
    """Run a command and return (success, combined_output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def get_missing_security_tools() -> List[str]:
    """Return list of tool names that are not currently available."""
    missing = []
    for name, tool in TOOLS.items():
        if not _is_installed(tool):
            missing.append(name)
    return missing


def refresh_tool_availability() -> str:
    """Force re-detection of all tools (useful after installs)."""
    # The is_installed function already uses shutil.which at call time,
    # so just calling list_tools() later will be fresh.
    missing = get_missing_security_tools()
    if not missing:
        return "✅ All security tools are now detected as installed!"
    return f"Still missing: {', '.join(missing)}"


def _install_with_winget(package: str) -> Tuple[bool, str]:
    if not _has_winget():
        return False, "winget not found on this system"
    cmd = ["winget", "install", "--id", package, "-e", "--accept-source-agreements", "--accept-package-agreements"]
    return _run_command(cmd, timeout=600)


def _install_with_choco(package: str) -> Tuple[bool, str]:
    if not _has_choco():
        return False, "choco (Chocolatey) not found. Install from https://chocolatey.org"
    cmd = ["choco", "install", package, "-y"]
    return _run_command(cmd, timeout=600, shell=True)


def _install_with_pip(package: str) -> Tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", package]
    return _run_command(cmd, timeout=300)


def install_tool(tool_name: str, prefer: str = "auto") -> str:
    """
    Attempt to install a single security tool.
    prefer: "winget", "choco", "pip", or "auto"
    """
    tool_name = tool_name.lower().strip()
    if tool_name not in TOOLS:
        return f"❌ Unknown tool '{tool_name}'. Use /tools to see available names."

    if _is_installed(TOOLS[tool_name]):
        return f"✅ '{tool_name}' is already installed and in PATH."

    # Decide strategy
    if tool_name in PYTHON_TOOLS and prefer in ("auto", "pip"):
        ok, out = _install_with_pip(tool_name)
        if ok:
            return f"✅ Installed {tool_name} via pip.\n{out[-800:]}"
        # fall through to winget/choco

    winget_id = WINGET_MAP.get(tool_name)
    choco_id = CHOCO_MAP.get(tool_name)

    if prefer == "winget" and winget_id:
        ok, out = _install_with_winget(winget_id)
        if ok:
            return f"✅ Installed {tool_name} via winget.\n{out[-800:]}"
        return f"❌ winget install failed for {tool_name}:\n{out[-600:]}"

    if prefer == "choco" and choco_id:
        ok, out = _install_with_choco(choco_id)
        if ok:
            return f"✅ Installed {tool_name} via choco.\n{out[-800:]}"
        return f"❌ choco install failed:\n{out[-600:]}"

    # AUTO strategy
    if winget_id and _has_winget():
        ok, out = _install_with_winget(winget_id)
        if ok:
            return f"✅ Installed {tool_name} via winget.\n{out[-800:]}"

    if choco_id and _has_choco():
        ok, out = _install_with_choco(choco_id)
        if ok:
            return f"✅ Installed {tool_name} via Chocolatey.\n{out[-800:]}"

    if tool_name in PYTHON_TOOLS:
        ok, out = _install_with_pip(tool_name)
        if ok:
            return f"✅ Installed {tool_name} via pip.\n{out[-800:]}"

    # Give honest advice for hard tools
    if tool_name in WSL_RECOMMENDED:
        return (
            f"⚠️ '{tool_name}' is best installed inside WSL Kali:\n"
            f"  wsl -d kali-linux\n"
            f"  sudo apt update && sudo apt install {tool_name} -y\n\n"
            f"After installing in WSL, the agent can run it automatically via WSL."
        )

    return (
        f"⚠️ Could not auto-install '{tool_name}' with winget/choco.\n"
        f"Manual options:\n"
        f"  • winget install {winget_id or tool_name}\n"
        f"  • choco install {choco_id or tool_name}\n"
        f"  • Or use WSL: sudo apt install {tool_name}"
    )


def install_all_missing(prefer: str = "auto") -> str:
    """Try to install every missing tool that has a reasonable Windows package."""
    missing = get_missing_security_tools()
    if not missing:
        return "✅ All known security tools are already available!"

    results = []
    easy = [t for t in missing if t in NATIVE_FRIENDLY]
    hard = [t for t in missing if t in WSL_RECOMMENDED]

    results.append(f"Found {len(missing)} missing tools.")
    results.append(f"Easy/native candidates: {', '.join(easy) if easy else 'None'}")
    results.append(f"WSL-recommended: {', '.join(hard) if hard else 'None'}")
    results.append("")

    for tool in easy:
        results.append(f"→ Installing {tool}...")
        msg = install_tool(tool, prefer=prefer)
        results.append(msg)
        results.append("")

    if hard:
        results.append("Harder tools (recommended via WSL Kali):")
        for tool in hard:
            results.append(f"  • {tool}  →  wsl -d kali-linux ; sudo apt install {tool} -y")

    return "\n".join(results)


def get_install_status_report() -> str:
    """Human readable report of what can be auto-installed."""
    missing = get_missing_security_tools()
    if not missing:
        return "✅ Everything looks installed!"

    lines = ["Security Tool Installation Status\n" + "=" * 45]
    lines.append(f"Missing: {len(missing)} tools\n")

    for name in missing:
        if name in NATIVE_FRIENDLY:
            lines.append(f"  [+] {name:<14} → Good candidate for winget / choco")
        elif name in WSL_RECOMMENDED:
            lines.append(f"  [WSL] {name:<12} → Best installed in WSL Kali")
        else:
            lines.append(f"  [?] {name:<14} → Manual investigation needed")

    lines.append("\nCommands you can use:")
    lines.append("  /install-tools          → attempt to install all easy ones")
    lines.append("  /install <name>         → install one specific tool")
    lines.append("  /tools                  → refresh status after installs")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(get_install_status_report())
    print("\n--- Testing single tool install (dry logic) ---")
    print(install_tool("nmap"))
    print("\nDone.")