#!/usr/bin/env python3
"""
Build script for the locked / obfuscated Larry G-Force distribution.

What this produces
------------------
A self-contained FOLDER you can ship:

    dist/LarryGForce-Locked/
        LarryGForce.exe          (interactive agent CLI)
        LarryDashboard.exe       (Flask dashboard on :3777)
        _internal/               (PyInstaller bundle + PyArmor-obfuscated *.py)
        prompts/LARRY_SYSTEM_PROMPT.md
        config/larry_config.json
        config/mcp.json
        mcp/fxjefe-local-mcp/    (stdio MCP server the agent spawns)
        user_config.json         (per-machine secrets — edit on each target box)
        RUN.bat                  (one-click: start dashboard then agent)

What is and is not protected
----------------------------
PROTECTED  — every *.py from src/ and a selected set of root files is run
             through PyArmor, then bundled into the PyInstaller archive. The
             plain source code is NOT in the dist folder.
NOT SECRET — prompts/LARRY_SYSTEM_PROMPT.md and config/*.json are shipped as
             plain text on purpose (they are operator-tunable). Put credentials
             in user_config.json, never in the protected source.
DEFEATABLE — Determined attackers can run pyinstxtractor on the bundle and
             attempt to strip PyArmor. This raises the bar against casual
             viewing/editing, not against motivated reverse engineers.

Build cost
----------
First run downloads PyInstaller (~70 MB) + PyArmor (~5 MB). PyInstaller takes
~5-15 minutes depending on machine and how many heavy deps (langchain,
chromadb, sentence-transformers, playwright) get walked. ~400-700 MB on disk.

Usage
-----
    python build_locked.py                  # full build
    python build_locked.py --skip-deps      # don't pip-install pyinstaller/pyarmor
    python build_locked.py --clean          # wipe dist/ build/ obfuscated/ first
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "src"
DIST = ROOT / "dist" / "LarryGForce-Locked"
BUILD = ROOT / "build"
OBF = ROOT / "obfuscated"

# Python files to obfuscate. Anything imported by the bundle that is not in
# this list will end up as plain .pyc inside _internal/ — still not readable
# source, but not PyArmor-protected either. Add to this list as the codebase
# grows.
OBFUSCATE_TARGETS = [
    # Root-level
    ROOT / "agent_v2.py",
    ROOT / "embeddings.py",
    ROOT / "dashboard_hub.py",
    ROOT / "dashboard_auth.py",
    ROOT / "mcp_client.py",
    # src/ — every .py except junk we don't want
    *[p for p in SRC.glob("*.py") if p.name not in {"__init__.py"} and not p.name.startswith("__")],
]

# Non-Python assets that must travel with the binary.
ASSETS = [
    (ROOT / "prompts" / "LARRY_SYSTEM_PROMPT.md", DIST / "prompts" / "LARRY_SYSTEM_PROMPT.md"),
    (ROOT / "config" / "larry_config.json",        DIST / "config" / "larry_config.json"),
    (ROOT / "config" / "mcp.json",                 DIST / "config" / "mcp.json"),
    # Whole FXJEFE MCP server directory — the agent spawns it via stdio.
    (ROOT / "mcp" / "fxjefe-local-mcp",            DIST / "mcp" / "fxjefe-local-mcp"),
]

# Two entry points -> two PyInstaller builds.
ENTRY_POINTS = [
    {"name": "LarryGForce",    "script": "agent_v2.py"},
    {"name": "LarryDashboard", "script": "dashboard_hub.py"},
]


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print("  " + title)
    print("=" * 72)


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd)


def ensure_tools() -> None:
    section("[1/6] Install / verify build tools")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller", "pyarmor"])


def clean() -> None:
    section("[2/6] Clean prior build artefacts")
    for p in (DIST, BUILD, OBF):
        if p.exists():
            print(f"  rm  {p}")
            shutil.rmtree(p, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)


def obfuscate() -> None:
    section("[3/6] PyArmor obfuscate source")
    OBF.mkdir(parents=True, exist_ok=True)
    existing = [str(p) for p in OBFUSCATE_TARGETS if p.exists()]
    missing = [str(p) for p in OBFUSCATE_TARGETS if not p.exists()]
    if missing:
        print("  (skipping non-existent targets:)")
        for m in missing:
            print(f"    - {m}")
    if not existing:
        raise SystemExit("No source files to obfuscate — check OBFUSCATE_TARGETS.")
    # `pyarmor gen --recursive` walks each entry's directory; we list explicit
    # files so we don't accidentally pull in venvs or build artefacts.
    cmd = [sys.executable, "-m", "pyarmor", "gen", "--output", str(OBF), *existing]
    run(cmd)


def pyinstaller_build(entry: dict) -> None:
    section(f"[4/6] PyInstaller bundle: {entry['name']}")
    script_obf = OBF / entry["script"]
    if not script_obf.exists():
        # Fall back to plain source if obfuscation skipped this entry
        script_obf = ROOT / entry["script"]
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",                  # FOLDER output, not single-file
        "--name", entry["name"],
        "--distpath", str(DIST.parent),   # writes into dist/<name>/
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--paths", str(OBF),         # so cross-imports resolve to obfuscated copies
        "--paths", str(SRC),
        "--paths", str(ROOT),
        "--collect-submodules", "langchain",
        "--collect-submodules", "langchain_ollama",
        "--collect-submodules", "langchain_chroma",
        "--collect-submodules", "chromadb",
        str(script_obf),
    ]
    run(cmd)
    # PyInstaller produces dist/<name>/ — fold it into LarryGForce-Locked/
    produced = DIST.parent / entry["name"]
    if produced != DIST and produced.exists():
        for item in produced.iterdir():
            target = DIST / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
        produced.rmdir()


def copy_assets() -> None:
    section("[5/6] Copy runtime assets (prompts, configs, MCP servers)")
    for src, dst in ASSETS:
        if not src.exists():
            print(f"  SKIP (missing): {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  copytree  {src.relative_to(ROOT)} -> {dst.relative_to(DIST)}")
        else:
            shutil.copy2(src, dst)
            print(f"  copy      {src.relative_to(ROOT)} -> {dst.relative_to(DIST)}")


def write_user_config_and_launchers() -> None:
    section("[6/6] Per-machine user_config.json + RUN.bat launcher")
    user_cfg = {
        "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
        "allowed_chat_ids": [123456789],
        "brave_api_key":     "YOUR_BRAVE_API_KEY",
        "github_token":      "YOUR_GITHUB_TOKEN",
        "default_model":     "dolphin-mixtral:8x7b",
        "ollama_host":       "http://127.0.0.1:11434",
    }
    (DIST / "user_config.json").write_text(
        json.dumps(user_cfg, indent=2), encoding="utf-8"
    )

    run_bat = (
        "@echo off\r\n"
        "REM Larry G-Force launcher. Edit user_config.json before first run.\r\n"
        "cd /d \"%~dp0\"\r\n"
        "start \"Larry Dashboard\" cmd /c LarryDashboard.exe\r\n"
        "timeout /t 3 >NUL\r\n"
        "LarryGForce.exe\r\n"
    )
    (DIST / "RUN.bat").write_text(run_bat, encoding="ascii")

    readme = (
        "Larry G-Force - Locked Distribution\r\n"
        "===================================\r\n\r\n"
        "1. Edit user_config.json for this machine (tokens, default model).\r\n"
        "2. Double-click RUN.bat. Dashboard opens on http://127.0.0.1:3777,\r\n"
        "   then the agent CLI starts in this window.\r\n\r\n"
        "Files in this folder you may edit:\r\n"
        "  user_config.json                         - per-machine settings\r\n"
        "  prompts/LARRY_SYSTEM_PROMPT.md           - agent persona / rules\r\n"
        "  config/larry_config.json                 - model + hardware profile\r\n"
        "  config/mcp.json                          - MCP server registry\r\n\r\n"
        "Files you should NOT edit:\r\n"
        "  LarryGForce.exe, LarryDashboard.exe      - compiled entry points\r\n"
        "  _internal/                               - PyArmor-protected bytecode\r\n"
    )
    (DIST / "README.txt").write_text(readme, encoding="ascii")


def summary() -> None:
    section("Done")
    print(f"  Output folder: {DIST}")
    print()
    print("  Contents:")
    for p in sorted(DIST.iterdir()):
        size_kb = p.stat().st_size // 1024 if p.is_file() else None
        tag = f"({size_kb} KB)" if size_kb is not None else "(dir)"
        print(f"    {p.name:30}  {tag}")
    print()
    print("  Next steps:")
    print("    1. Edit dist/LarryGForce-Locked/user_config.json")
    print("    2. Run dist/LarryGForce-Locked/RUN.bat")
    print()
    print("  To ship to another machine: zip the entire LarryGForce-Locked/")
    print("  folder and copy. Recipient edits user_config.json and runs RUN.bat.")


# ─────────────────────────────────────────────────────────────────────────────
# Code signing (Authenticode)
# ─────────────────────────────────────────────────────────────────────────────
# "Maximum protection" pairs obfuscation (above) with a code signature so the
# binaries can't be silently tampered with. By default we use a SELF-SIGNED dev
# certificate (good for testing the pipeline; other machines still see "unknown
# publisher"). To sign with a real Authenticode cert instead, set:
#     set LARRY_CODESIGN_PFX=C:\path\to\cert.pfx
#     set LARRY_CODESIGN_PASS=its-password
# and the build will use that .pfx automatically.

SIGN_SUBJECT = "CN=Larry G-Force Dev Code Signing"
TIMESTAMP_URL = "http://timestamp.digicert.com"
SIGN_EXES = ("LarryGForce.exe", "LarryDashboard.exe")


def find_signtool() -> str | None:
    """Locate signtool.exe (PATH first, then the Windows 10/11 SDK)."""
    found = shutil.which("signtool")
    if found:
        return found
    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Kits" / "10" / "bin",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            for arch in ("x64", "arm64", "x86"):
                candidates += list(root.glob(f"*/{arch}/signtool.exe"))
    # Highest SDK version (lexically-sortable 10.0.x folders) wins.
    candidates.sort()
    return str(candidates[-1]) if candidates else None


def ensure_self_signed_cert() -> str:
    """Create (or reuse) a self-signed code-signing cert in CurrentUser\\My.
    Returns its SHA1 thumbprint."""
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$subject='{SIGN_SUBJECT}';"
        "$c=Get-ChildItem Cert:\\CurrentUser\\My | "
        "Where-Object { $_.Subject -eq $subject -and $_.HasPrivateKey } | Select-Object -First 1;"
        "if(-not $c){$c=New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject "
        "-CertStoreLocation Cert:\\CurrentUser\\My -KeyExportPolicy Exportable "
        "-KeyUsage DigitalSignature -NotAfter (Get-Date).AddYears(5)};"
        "$c.Thumbprint"
    )
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        text=True,
    )
    return out.strip().splitlines()[-1].strip()


def sign_binaries(exes: list[Path], *, thumbprint: str | None = None,
                  pfx: str | None = None, pfx_pass: str | None = None) -> None:
    signtool = find_signtool()
    if not signtool:
        print("  signtool.exe not found. Install the Windows SDK "
              "(https://developer.microsoft.com/windows/downloads/windows-sdk/) "
              "then re-run with --sign-only. Skipping.")
        return

    base = [signtool, "sign", "/fd", "SHA256"]
    if pfx:
        base += ["/f", pfx]
        if pfx_pass:
            base += ["/p", pfx_pass]
    elif thumbprint:
        base += ["/sha1", thumbprint]
    else:
        base += ["/a"]

    for exe in exes:
        print(f"  signing {exe.name}")
        try:
            run(base + ["/tr", TIMESTAMP_URL, "/td", "SHA256", str(exe)])
        except subprocess.CalledProcessError:
            print("    timestamp server unreachable — signing without a timestamp.")
            run(base + [str(exe)])

    # Informational verify. A self-signed cert fails the trust check unless its
    # root is imported into Trusted Root / Trusted Publishers — that's expected.
    for exe in exes:
        print(f"  verify {exe.name}:")
        subprocess.call([signtool, "verify", "/pa", "/v", str(exe)])


def sign_step() -> None:
    section("[7/7] Code sign executables (Authenticode)")
    if os.name != "nt":
        print("  Not Windows — code signing skipped.")
        return
    exes = [DIST / name for name in SIGN_EXES if (DIST / name).exists()]
    if not exes:
        print(f"  No signable .exe in {DIST} — run the build first.")
        return

    pfx = os.environ.get("LARRY_CODESIGN_PFX")
    if pfx:
        print(f"  Using real certificate from LARRY_CODESIGN_PFX: {pfx}")
        sign_binaries(exes, pfx=pfx, pfx_pass=os.environ.get("LARRY_CODESIGN_PASS"))
    else:
        print(f"  Using self-signed dev certificate ({SIGN_SUBJECT}).")
        thumb = ensure_self_signed_cert()
        print(f"  Thumbprint: {thumb}")
        sign_binaries(exes, thumbprint=thumb)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Larry G-Force locked distribution.")
    parser.add_argument("--skip-deps", action="store_true",
                        help="Don't pip-install pyinstaller/pyarmor.")
    parser.add_argument("--clean", action="store_true",
                        help="Wipe dist/ build/ obfuscated/ before building.")
    parser.add_argument("--no-sign", action="store_true",
                        help="Skip the Authenticode code-signing step.")
    parser.add_argument("--sign-only", action="store_true",
                        help="Only (re)sign the existing dist .exe files, no rebuild.")
    args = parser.parse_args()

    if args.sign_only:
        sign_step()
        return

    if not args.skip_deps:
        ensure_tools()

    if args.clean or DIST.exists():
        clean()
    else:
        DIST.mkdir(parents=True, exist_ok=True)

    obfuscate()
    for entry in ENTRY_POINTS:
        pyinstaller_build(entry)
    copy_assets()
    write_user_config_and_launchers()
    if not args.no_sign:
        sign_step()
    summary()


if __name__ == "__main__":
    main()
