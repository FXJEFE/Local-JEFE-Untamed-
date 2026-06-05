#!/usr/bin/env python3
"""
Kali / Security Tool Runner for Agent-Larry
Wraps common recon, web, network, and password tools with timeout handling.
"""

import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─── Tool Registry ────────────────────────────────────────────────────────────

@dataclass
class Tool:
    name: str
    cmd: str                        # base binary name
    desc: str
    category: str
    default_timeout: int = 120      # seconds
    presets: Dict[str, str] = field(default_factory=dict)  # preset_name → extra args


TOOLS: Dict[str, Tool] = {
    # ── Recon / Network ──────────────────────────────────────────────────────
    "nmap": Tool(
        name="nmap", cmd="nmap",
        desc="Network/port scanner",
        category="recon",
        default_timeout=300,
        presets={
            "quick":   "-T4 -F --open",
            "full":    "-T4 -p- --open",
            "service": "-T4 -sV -sC --open",
            "vuln":    "-T4 --script vuln",
            "udp":     "-T4 -sU --top-ports 100",
            "os":      "-T4 -O --open",
            "stealth": "-T2 -sS --open",
        },
    ),
    "masscan": Tool(
        name="masscan", cmd="masscan",
        desc="Fast async port scanner",
        category="recon",
        default_timeout=120,
        presets={
            "quick": "--rate=1000 -p1-1000",
            "full":  "--rate=10000 -p1-65535",
            "web":   "--rate=1000 -p80,443,8080,8443",
        },
    ),
    "arp-scan": Tool(
        name="arp-scan", cmd="arp-scan",
        desc="ARP host discovery on local network",
        category="recon",
        default_timeout=60,
        presets={
            "local": "--localnet",
            "iface": "-I eth0 --localnet",
        },
    ),
    # ── DNS / OSINT ──────────────────────────────────────────────────────────
    "dig": Tool(
        name="dig", cmd="dig",
        desc="DNS lookup",
        category="dns",
        default_timeout=30,
        presets={
            "any":  "ANY",
            "mx":   "MX",
            "txt":  "TXT",
            "axfr": "AXFR",
        },
    ),
    "host": Tool(
        name="host", cmd="host",
        desc="DNS hostname/IP lookup",
        category="dns",
        default_timeout=15,
    ),
    "whois": Tool(
        name="whois", cmd="whois",
        desc="Domain / IP whois lookup",
        category="osint",
        default_timeout=30,
    ),
    "dnsenum": Tool(
        name="dnsenum", cmd="dnsenum",
        desc="DNS enumeration",
        category="dns",
        default_timeout=120,
        presets={
            "basic": "--nocolor",
        },
    ),
    # ── Web ──────────────────────────────────────────────────────────────────
    "nikto": Tool(
        name="nikto", cmd="nikto",
        desc="Web server vulnerability scanner",
        category="web",
        default_timeout=300,
        presets={
            "basic": "-nointeractive",
            "ssl":   "-nointeractive -ssl",
            "fast":  "-nointeractive -maxtime 60",
        },
    ),
    "whatweb": Tool(
        name="whatweb", cmd="whatweb",
        desc="Web technology fingerprinter",
        category="web",
        default_timeout=60,
        presets={
            "quiet":   "-q",
            "verbose": "-v",
            "aggro":   "-a 3",
        },
    ),
    "gobuster": Tool(
        name="gobuster", cmd="gobuster",
        desc="Directory/DNS/vhost brute-forcer",
        category="web",
        default_timeout=300,
        presets={
            "dir":   "dir -w /usr/share/wordlists/dirb/common.txt",
            "dns":   "dns -w /usr/share/wordlists/dnsmap.txt",
            "vhost": "vhost -w /usr/share/wordlists/dirb/common.txt",
        },
    ),
    "dirb": Tool(
        name="dirb", cmd="dirb",
        desc="Web directory brute-forcer",
        category="web",
        default_timeout=300,
    ),
    "wfuzz": Tool(
        name="wfuzz", cmd="wfuzz",
        desc="Web fuzzer",
        category="web",
        default_timeout=300,
        presets={
            "basic": "-w /usr/share/wordlists/dirb/common.txt --hc 404",
        },
    ),
    "sqlmap": Tool(
        name="sqlmap", cmd="sqlmap",
        desc="SQL injection scanner",
        category="web",
        default_timeout=300,
        presets={
            "basic":  "--batch --level=1",
            "full":   "--batch --level=3 --risk=2",
            "forms":  "--batch --forms",
        },
    ),
    "curl": Tool(
        name="curl", cmd="curl",
        desc="HTTP request tool",
        category="web",
        default_timeout=30,
        presets={
            "headers": "-I",
            "verbose": "-v",
            "post":    "-X POST",
        },
    ),
    # ── Exploitation ─────────────────────────────────────────────────────────
    "searchsploit": Tool(
        name="searchsploit", cmd="searchsploit",
        desc="Exploit-DB search",
        category="exploit",
        default_timeout=30,
    ),
    # ── SMB / Samba ──────────────────────────────────────────────────────────
    "enum4linux": Tool(
        name="enum4linux", cmd="enum4linux",
        desc="SMB/NetBIOS enumeration",
        category="smb",
        default_timeout=120,
        presets={
            "all":   "-a",
            "users": "-U",
            "shares":"-S",
        },
    ),
    "smbclient": Tool(
        name="smbclient", cmd="smbclient",
        desc="SMB client",
        category="smb",
        default_timeout=60,
        presets={
            "list": "-L",
            "anon": "-N -L",
        },
    ),
    # ── Password ─────────────────────────────────────────────────────────────
    "hydra": Tool(
        name="hydra", cmd="hydra",
        desc="Login brute-forcer",
        category="password",
        default_timeout=300,
        presets={
            "ssh":  "-t 4 ssh",
            "ftp":  "-t 4 ftp",
            "http": "-t 4 http-get",
        },
    ),
    "hashcat": Tool(
        name="hashcat", cmd="hashcat",
        desc="GPU password cracker",
        category="password",
        default_timeout=600,
    ),
    "john": Tool(
        name="john", cmd="john",
        desc="CPU password cracker",
        category="password",
        default_timeout=600,
        presets={
            "wordlist": "--wordlist=/usr/share/wordlists/rockyou.txt",
            "show":     "--show",
        },
    ),
}

CATEGORIES = {
    "recon":    "Reconnaissance & Port Scanning",
    "dns":      "DNS & OSINT",
    "osint":    "OSINT",
    "web":      "Web Application Testing",
    "exploit":  "Exploitation",
    "smb":      "SMB / Windows",
    "password": "Password Attacks",
}


# ─── Runner ───────────────────────────────────────────────────────────────────

def _is_wsl_available() -> bool:
    """Check if we can reach a Kali WSL distro from Windows."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["wsl", "-d", "kali-linux", "--", "echo", "ok"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def is_installed(tool: Tool) -> bool:
    if shutil.which(tool.cmd):
        return True
    # On Windows, fall back to checking inside WSL Kali
    if os.name == "nt" and _is_wsl_available():
        try:
            result = subprocess.run(
                ["wsl", "-d", "kali-linux", "--", "which", tool.cmd],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            pass
    return False


def run_tool(
    tool_name: str,
    args: str = "",
    timeout: int = None,
    max_output: int = 8000,
) -> Tuple[bool, str]:
    """
    Run a security tool and return (success, output).
    output is capped at max_output chars.
    """
    tool = TOOLS.get(tool_name.lower())
    if not tool:
        available = ", ".join(sorted(TOOLS.keys()))
        return False, f"Unknown tool '{tool_name}'. Available: {available}"

    if not is_installed(tool):
        if os.name == "nt" and _is_wsl_available():
            # Will run via WSL below
            pass
        else:
            return False, (
                f"'{tool.cmd}' not found. Run this in your Kali WSL:\n"
                f"  ./install_kali_tools.sh\n"
                f"  or: sudo apt install {tool.cmd}"
            )

    effective_timeout = timeout or tool.default_timeout

    # Build command list safely
    try:
        cmd_parts = [tool.cmd] + shlex.split(args) if args.strip() else [tool.cmd]
    except ValueError as e:
        return False, f"Bad argument syntax: {e}"

    # On Windows without local binary, run inside WSL Kali
    use_wsl = False
    if os.name == "nt" and not shutil.which(tool.cmd) and _is_wsl_available():
        use_wsl = True
        cmd_parts = ["wsl", "-d", "kali-linux", "--"] + cmd_parts

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        output = output.strip()
        if not output:
            output = f"(no output, exit code {result.returncode})"
        if len(output) > max_output:
            output = output[:max_output] + f"\n\n... [truncated at {max_output} chars]"
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {effective_timeout}s. Use a longer --timeout or narrow your target."
    except FileNotFoundError:
        return False, f"Binary not found: {tool.cmd}"
    except Exception as e:
        return False, f"Error running {tool.cmd}: {e}"


def run_tool_background(
    tool_name: str,
    args: str = "",
    timeout: int = None,
    callback=None,
    max_output: int = 8000,
):
    """Run a tool in a background thread; calls callback(success, output) when done."""
    def _run():
        success, output = run_tool(tool_name, args, timeout, max_output)
        if callback:
            callback(success, output)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ─── Help / Listing ───────────────────────────────────────────────────────────

def list_tools(category: str = None) -> str:
    """Return formatted tool list, optionally filtered by category."""
    lines = ["Security Tools\n" + "=" * 50]
    cats = {category: CATEGORIES[category]} if category and category in CATEGORIES else CATEGORIES
    for cat_key, cat_name in cats.items():
        cat_tools = [t for t in TOOLS.values() if t.category == cat_key]
        if not cat_tools:
            continue
        lines.append(f"\n{cat_name}:")
        for t in cat_tools:
            status = "+" if is_installed(t) else "-"
            lines.append(f"  [{status}] {t.name:<16} {t.desc}")
    lines.append("\n[+] = installed  [-] = not installed")
    return "\n".join(lines)


def tool_help(tool_name: str) -> str:
    """Return usage info + presets for a tool."""
    tool = TOOLS.get(tool_name.lower())
    if not tool:
        return f"Unknown tool '{tool_name}'"
    installed = "installed" if is_installed(tool) else "NOT installed"
    lines = [
        f"{tool.name} — {tool.desc}  [{installed}]",
        f"Category : {CATEGORIES.get(tool.category, tool.category)}",
        f"Timeout  : {tool.default_timeout}s",
        f"Usage    : /kali {tool.name} <args>",
    ]
    if tool.presets:
        lines.append("Presets:")
        for name, preset_args in tool.presets.items():
            lines.append(f"  /kali {tool.name} :{name} <target>  →  {tool.cmd} {preset_args} <target>")
    return "\n".join(lines)


def parse_args_with_preset(tool: Tool, raw_args: str) -> str:
    """
    Expand preset shorthand. If raw_args starts with :preset_name,
    replace it with the preset's args string.
    Example: ':quick 192.168.1.1' → '-T4 -F --open 192.168.1.1'
    """
    raw_args = raw_args.strip()
    if raw_args.startswith(":"):
        parts = raw_args.split(None, 1)
        preset_name = parts[0][1:]  # strip leading ':'
        rest = parts[1] if len(parts) > 1 else ""
        preset_val = tool.presets.get(preset_name)
        if preset_val is None:
            available = ", ".join(f":{k}" for k in tool.presets)
            return f"__ERROR__Unknown preset ':{preset_name}'. Available: {available}"
        return f"{preset_val} {rest}".strip()
    return raw_args
